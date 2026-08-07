"""
JALAAKAR — database layer + config accessor.
Owner: Dev B.  Everybody imports this; nobody writes raw SQL for inserts.

Config
------
`config.yaml` is the shared file and its nested shape is authoritative. Rather
than sprinkle `CFG["dates"]["last5_start"]` across five scripts, this module
exposes a flat accessor. If A reshapes a key, it changes in ONE place here.

    from ingest.db import cfg
    cfg.scenario_date      # date from scenario.date
    cfg.splits             # dict from splits.*
    cfg.bbox               # dict from geography.bbox

Database
--------
    from ingest.db import connect, upsert, table_count, log_run, season_of

    with connect() as con:                 # creates + migrates schema on open
        upsert(con, "wells", wells_df)
        print(table_count(con, "wells"))

    with log_run("02_wells.py", rows_in=len(df)) as run:
        ...
        run.rows_out = n
"""

from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, date as _date
from pathlib import Path

import pandas as pd
import yaml

# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "ingest" / "00_schema.sql"
CONFIG_PATH = ROOT / "config.yaml"


# --------------------------------------------------------------------------
# config accessor — the ONLY place that knows config.yaml's nesting
# --------------------------------------------------------------------------
class _Config:
    """Flat, typed view over the nested shared config.

    Every property maps to exactly one place in config.yaml. When A reshapes
    the file, fix it here and no other script changes.
    """

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._raw: dict | None = None

    @property
    def raw(self) -> dict:
        if self._raw is None:
            if not self._path.exists():
                raise FileNotFoundError(f"config.yaml not found at {self._path}")
            self._raw = yaml.safe_load(self._path.read_text())
        return self._raw

    def _get(self, *keys, default="__RAISE__"):
        node = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                if default == "__RAISE__":
                    raise KeyError(
                        f"config.yaml is missing {'.'.join(keys)} — "
                        f"has the shared config been reshaped? Fix the mapping "
                        f"in ingest/db.py::_Config, not in the calling script."
                    )
                return default
            node = node[k]
        return node

    # -- scenario ----------------------------------------------------------
    @property
    def scenario_date(self) -> str:
        return str(self._get("scenario", "date"))

    @property
    def demo_taluka(self) -> str:
        return self._get("scenario", "demo_taluka")

    @property
    def demo_district(self) -> str:
        return self._get("scenario", "demo_district")

    # -- geography ---------------------------------------------------------
    @property
    def state(self) -> str:
        return self._get("geography", "state")

    @property
    def state_aliases(self) -> list:
        return self._get("geography", "state_aliases", default=[self.state])

    @property
    def bbox(self) -> dict:
        return self._get("geography", "bbox")

    # -- dates -------------------------------------------------------------
    @property
    def last5_start(self) -> str:
        return str(self._get("dates", "last5_start"))

    @property
    def gw_end(self) -> str:
        return str(self._get("dates", "gw_end"))

    @property
    def daily_start(self) -> str:
        """First date materialised into gw_daily. Recession fitting still uses
        the full observation record — this only trims the output curve."""
        return str(self._get("dates", "daily_start", default="2000-01-01"))

    @property
    def end_date(self) -> str:
        return str(self._get("dates", "end_date"))

    @property
    def history_floor(self) -> str:
        return str(self._get("dates", "history_floor", default="1990-01-01"))

    # -- seasons -----------------------------------------------------------
    @property
    def seasons(self) -> dict:
        """{'pre_monsoon': [3,4,5], ...} — A's config drives this, not code."""
        return self._get("seasons")

    @property
    def month_to_season(self) -> dict:
        return {m: name for name, months in self.seasons.items() for m in months}

    # -- splits ------------------------------------------------------------
    @property
    def splits(self) -> dict:
        return self._get("splits")

    @property
    def urban_all_test(self) -> bool:
        return bool(self._get("urban", "all_test", default=True))

    # -- features ----------------------------------------------------------
    @property
    def horizon(self) -> int:
        return int(self._get("features", "target_horizon_days", default=30))

    @property
    def lags(self) -> list:
        return self._get("features", "lags", default=[7, 15, 30, 60, 90])

    @property
    def rolling_windows(self) -> list:
        return self._get("features", "rolling_windows", default=[7, 30, 90])

    @property
    def rain_day_mm(self) -> float:
        return float(self._get("features", "rain_day_mm", default=2.5))

    @property
    def monsoon_start_month(self) -> int:
        return int(self._get("features", "monsoon_start_month", default=6))

    # -- sources -----------------------------------------------------------
    @property
    def openmeteo_url(self) -> str:
        return self._get("sources", "openmeteo_archive")

    @property
    def openmeteo_sleep_s(self) -> float:
        return float(self._get("sources", "openmeteo_sleep_s", default=0.5))

    @property
    def coord_precision(self) -> float:
        return float(self._get("sources", "coord_dedupe_deg", default=0.1))

    @property
    def openmeteo_timeout_s(self) -> int:
        return int(self._get("sources", "openmeteo_timeout_s", default=60))

    @property
    def openmeteo_max_retries(self) -> int:
        return int(self._get("sources", "openmeteo_max_retries", default=4))

    @property
    def openmeteo_timezone(self) -> str:
        return self._get("sources", "openmeteo_timezone", default="Asia/Kolkata")

    # -- paths -------------------------------------------------------------
    def path(self, key: str) -> Path:
        return ROOT / self._get("paths", key)

    @property
    def db_path(self) -> Path:
        # JALAAKAR_DB lets you point every script at a scratch DB:
        #     JALAAKAR_DB=data/test.db python ingest/06_features.py
        env = os.environ.get("JALAAKAR_DB")
        return Path(env) if env else self.path("db")


cfg = _Config()

# back-compat for anything still calling config()
def config() -> dict:
    return cfg.raw


DEFAULT_DB = None  # resolved lazily via cfg.db_path; kept for import stability


# --------------------------------------------------------------------------
# connection
# --------------------------------------------------------------------------
def _migrate(con: sqlite3.Connection) -> None:
    """Add columns to tables that already exist.

    `CREATE TABLE IF NOT EXISTS` is a no-op on an existing database, so new
    columns in 00_schema.sql would otherwise never appear and upsert() would
    silently drop that data. Additive only — never drops or retypes.
    """
    wanted = {
        "wells": [("sy_source", "TEXT"), ("well_depth", "REAL")],
    }
    for table, cols in wanted.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue                                # table not created yet
        for name, decl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                print(f"  [db] migrated: {table}.{name} added", file=sys.stderr)


@contextmanager
def connect(db_path: str | Path | None = None, readonly: bool = False):
    """Open the DB, apply the schema (idempotent), yield the connection.

    Commits on clean exit, rolls back on exception. Always closes.
    """
    path = Path(db_path) if db_path else cfg.db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(path)
        con.executescript(SCHEMA_PATH.read_text())
        _migrate(con)

    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        if not readonly:
            con.commit()
    except Exception:
        if not readonly:
            con.rollback()
        raise
    finally:
        con.close()


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def primary_key(con: sqlite3.Connection, table: str) -> list[str]:
    """PK column names in declaration order. Empty list if the table has none."""
    rows = [r for r in con.execute(f"PRAGMA table_info({table})") if r[5]]
    return [r[1] for r in sorted(rows, key=lambda r: r[5])]


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def upsert(
    con: sqlite3.Connection,
    table: str,
    df: pd.DataFrame,
    mode: str = "replace",
    chunk: int = 5_000,
) -> int:
    """Insert a DataFrame into `table`, keyed on the table's PRIMARY KEY.

    mode='replace'  -> INSERT ... ON CONFLICT(pk) DO UPDATE  (the default,
                       because every ingest script must be re-runnable)
    mode='ignore'   -> INSERT OR IGNORE   (first write wins)

    ⚠️  'replace' does NOT use SQLite's INSERT OR REPLACE. That statement is a
    DELETE followed by an INSERT, so with PRAGMA foreign_keys=ON and
    ON DELETE CASCADE it silently destroys child rows. Verified: re-upserting
    an IDENTICAL `wells` row took gw_observations 13 -> 0 and gw_daily 1 -> 0,
    with no error raised; re-running 04_reservoirs.py took the seeded June-2026
    reservoir anchors 3 -> 0. ON CONFLICT DO UPDATE mutates in place instead.
    Do not "simplify" this back to INSERT OR REPLACE.

    Extra DataFrame columns not present in the table are dropped with a
    warning; missing columns are left NULL. Dates/bools are normalised.
    """
    if df is None or len(df) == 0:
        return 0
    if mode not in ("replace", "ignore"):
        raise ValueError("mode must be 'replace' or 'ignore'")

    cols = table_columns(con, table)
    if not cols:
        raise ValueError(f"table {table!r} does not exist — schema not applied?")

    extra = [c for c in df.columns if c not in cols]
    if extra:
        print(f"  [db] warning: dropping columns not in {table}: {extra}", file=sys.stderr)

    use = [c for c in cols if c in df.columns]
    out = _normalise(df[use].copy())

    head = f"INTO {table} ({', '.join(use)}) VALUES ({', '.join('?' * len(use))})"
    if mode == "ignore":
        sql = f"INSERT OR IGNORE {head}"
    else:
        pk = primary_key(con, table)
        setters = ", ".join(f"{c}=excluded.{c}" for c in use if c not in pk)
        if not pk:                       # no PK -> nothing to conflict on
            sql = f"INSERT {head}"
        elif not setters:                # every column is part of the PK
            sql = f"INSERT {head} ON CONFLICT({', '.join(pk)}) DO NOTHING"
        else:
            sql = (f"INSERT {head} ON CONFLICT({', '.join(pk)}) "
                   f"DO UPDATE SET {setters}")

    rows = list(out.itertuples(index=False, name=None))
    n = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        con.executemany(sql, batch)
        n += len(batch)
    return n


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce python/pandas types into things sqlite3 accepts."""
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            df[c] = s.dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_bool_dtype(s):
            df[c] = s.astype("int64")
        elif s.dtype == object:
            df[c] = s.map(
                lambda v: v.strftime("%Y-%m-%d")
                if isinstance(v, (_date, datetime))
                else (bool(v) * 1 if isinstance(v, bool) else v)
            )
    # pandas NA -> None so sqlite writes NULL, not the string 'nan'
    return df.astype(object).where(pd.notnull(df), None)


def replace_table(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    """Wipe and reload a table. Use for `features` — it is fully derived."""
    con.execute(f"DELETE FROM {table}")
    return upsert(con, table, df)


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def read(con: sqlite3.Connection, sql: str, params=()) -> pd.DataFrame:
    return pd.read_sql_query(sql, con, params=params)


def table_count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def summary(con: sqlite3.Connection) -> pd.DataFrame:
    """Row counts for every table — print this after every script."""
    tables = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return pd.DataFrame(
        {"table": tables, "rows": [table_count(con, t) for t in tables]}
    )


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------
class _Run:
    def __init__(self):
        self.rows_in = None
        self.rows_out = None
        self.notes = None


@contextmanager
def log_run(script: str, rows_in: int | None = None, db_path=None):
    """Record a row in ingest_log. DATA_CARD.md is generated from this table."""
    run = _Run()
    run.rows_in = rows_in
    started = datetime.now().isoformat(timespec="seconds")
    status = "ok"
    try:
        yield run
    except Exception as e:
        status = "failed"
        run.notes = f"{type(e).__name__}: {e}"
        raise
    finally:
        try:
            with connect(db_path) as con:
                con.execute(
                    "INSERT INTO ingest_log "
                    "(script, started_at, ended_at, rows_in, rows_out, status, notes) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        script,
                        started,
                        datetime.now().isoformat(timespec="seconds"),
                        run.rows_in,
                        run.rows_out,
                        status,
                        run.notes,
                    ),
                )
        except Exception as e:  # logging must never kill a run
            print(f"  [db] could not write ingest_log: {e}", file=sys.stderr)


# --------------------------------------------------------------------------
# shared domain helpers — A and B must agree on these, so they live here
# --------------------------------------------------------------------------
def season_of(d) -> str:
    """Season for one date, driven by config.yaml `seasons` (not hardcoded)."""
    return cfg.month_to_season[pd.Timestamp(d).month]


def season_series(dates: pd.Series) -> pd.Series:
    """Vectorised season_of for a datetime Series."""
    m = pd.to_datetime(pd.Series(dates)).dt.month
    return m.map(cfg.month_to_season).astype(object)


def is_last_5y(dates: pd.Series) -> pd.Series:
    """1 where the date is inside the last-5-years window. Boundary is
    dates.last5_start — 5 years back from the TRUE data end, not from today."""
    return (pd.to_datetime(pd.Series(dates))
            >= pd.Timestamp(cfg.last5_start)).astype("int64")


def dedupe_coords(df: pd.DataFrame, precision: float | None = None,
                  lat_col: str = "lat", lon_col: str = "lon") -> pd.DataFrame:
    """Snap coordinates to a `precision`-degree grid and return unique cells.

    Many wells share an ERA5 grid cell, so this cuts the number of Open-Meteo
    calls. Returns: grid_lat, grid_lon, members (list of ids), n_members.
    """
    precision = precision or cfg.coord_precision
    d = df.copy()
    d["grid_lat"] = ((d[lat_col] / precision).round() * precision).round(4)
    d["grid_lon"] = ((d[lon_col] / precision).round() * precision).round(4)
    id_col = d.columns[0]
    g = (
        d.groupby(["grid_lat", "grid_lon"])[id_col]
        .apply(list)
        .reset_index(name="members")
    )
    g["n_members"] = g["members"].map(len)
    return g


if __name__ == "__main__":
    # `python ingest/db.py` == smoke test the contract
    print(f"config : {CONFIG_PATH}")
    print(f"  scenario     {cfg.scenario_date}  ({cfg.demo_taluka}, {cfg.demo_district})")
    print(f"  gw data ends {cfg.gw_end}")
    print(f"  last5_start  {cfg.last5_start}")
    print(f"  splits       {cfg.splits}")
    print(f"  seasons      {cfg.month_to_season}")
    print(f"  horizon      t+{cfg.horizon}d  lags={cfg.lags}")
    with connect() as con:
        print()
        print(summary(con).to_string(index=False))
    print(f"\nDB ready at {cfg.db_path}")
