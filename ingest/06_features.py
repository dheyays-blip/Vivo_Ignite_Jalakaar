#!/usr/bin/env python3
"""
JALAAKAR — Stage 6: the feature table.
Owner: Dev B.

Joins wells + gw_daily + weather_daily (rural) and reservoirs +
reservoir_daily + weather_daily (urban) into `features`, the ONLY table the
ML track reads.

Splits are CHRONOLOGICAL. Never random. A random split leaks the future into
training and will silently inflate your reported accuracy — a judge who knows
time series will ask about exactly this.

    train : start        → 2024-06-30
    val   : 2024-07-01   → 2025-06-30
    test  : 2025-07-01   → 2026-06-30   (contains the demo scenario date)
    rows after test_end are dropped — no label horizon for them

Usage
-----
    python ingest/06_features.py                 # both tracks
    python ingest/06_features.py --rural-only    # the Sat-16:00 fallback
    python ingest/06_features.py --keep-warmup   # keep rows with null lags
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import (  # noqa: E402
    cfg, connect, log_run, read, replace_table, season_series, table_count,
)

REQUIRED_NOT_NULL = [
    "entity_id", "entity_type", "date", "level",
    "precip_mm", "rain_30d", "level_lag_30", "target_level_t30", "split",
]


# --------------------------------------------------------------------------
# per-entity feature construction
# --------------------------------------------------------------------------
def build_entity(g: pd.DataFrame) -> pd.DataFrame:
    """g: one entity, daily, sorted by date, columns level + weather."""
    g = g.sort_values("date").set_index("date")

    # SQLite hands back object dtype for all-NULL columns; force numeric so
    # rolling/cumsum work even when a source table is not populated yet
    for c in ("level", "precip_mm", "et0_mm", "soil_moist_0_7",
              "soil_moist_7_28", "temp_max", "rh_mean", "confidence"):
        if c in g.columns:
            g[c] = pd.to_numeric(g[c], errors="coerce")

    # reindex to a gapless daily calendar so lags mean *days*, not *rows*
    full = pd.date_range(g.index.min(), g.index.max(), freq="D")
    g = g.reindex(full)
    g.index.name = "date"

    lvl = g["level"]
    rain = g["precip_mm"]

    for L in cfg.lags:
        g[f"level_lag_{L}"] = lvl.shift(L)

    for W in cfg.rolling_windows:
        g[f"rain_{W}d"] = rain.rolling(W, min_periods=max(1, W // 2)).sum()

    g["et0_30d"] = g["et0_mm"].rolling(30, min_periods=15).sum()

    # days since it last properly rained
    wet = rain >= cfg.rain_day_mm
    idx = pd.Series(np.arange(len(g)), index=g.index)
    last_wet = idx.where(wet.fillna(False)).ffill()
    g["days_since_last_rain"] = (idx - last_wet)

    # cumulative monsoon rainfall, resets on 1 June each year
    m0 = cfg.monsoon_start_month
    wy = g.index.year - (g.index.month < m0).astype(int)   # "water year"
    g["cum_monsoon_rainfall"] = rain.fillna(0).groupby(wy).cumsum()

    g["level_change_7d"] = lvl - lvl.shift(7)
    g["level_change_30d"] = lvl - lvl.shift(30)

    g["month"] = g.index.month
    g["doy"] = g.index.dayofyear
    g["season"] = season_series(pd.Series(g.index, index=g.index))

    h = cfg.horizon
    g["target_level_t30"] = lvl.shift(-h)

    g["is_last_5y"] = (g.index >= pd.Timestamp(cfg.last5_start)).astype(int)
    return g.reset_index()


def assign_split(dates: pd.Series, track: str) -> pd.Series:
    """Chronological split for one track.

    The two tracks have different data coverage, so they get different
    boundaries. Urban is never trained on — every urban row is 'test'.
    """
    d = pd.to_datetime(dates)

    # The urban series is ~1 season of published aggregates — far too short to
    # train on. Labelling it all 'test' means it can never leak into training.
    if track == "urban" and cfg.urban_all_test:
        return pd.Series("test", index=d.index, dtype=object)

    # Rural uses the shared boundaries in config.yaml `splits:`. Those are set
    # to the data's REAL coverage (ends 2023-08), not to the scenario year.
    s = cfg.splits
    out = pd.Series(pd.NA, index=d.index, dtype=object)
    out[d <= pd.Timestamp(s["train_end"])] = "train"
    out[(d > pd.Timestamp(s["train_end"])) & (d <= pd.Timestamp(s["val_end"]))] = "val"
    out[(d > pd.Timestamp(s["val_end"])) & (d <= pd.Timestamp(s["test_end"]))] = "test"
    return out


# --------------------------------------------------------------------------
# track builders
# --------------------------------------------------------------------------
def rural(con) -> pd.DataFrame:
    if table_count(con, "gw_daily") == 0:
        print("[rural] gw_daily is EMPTY — waiting on handoff H3 from Dev A. Skipping.",
              file=sys.stderr)
        return pd.DataFrame()

    df = read(con, """
        SELECT g.well_id AS entity_id, g.date, g.level_mbgl AS level,
               g.is_observed, g.confidence,
               w.precip_mm, w.et0_mm, w.soil_moist_0_7, w.soil_moist_7_28,
               w.temp_max, w.rh_mean
        FROM gw_daily g
        LEFT JOIN weather_daily w
               ON w.well_id = g.well_id AND w.date = g.date
        ORDER BY g.well_id, g.date
    """)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[rural] {len(df):,} daily rows across "
          f"{df.entity_id.nunique()} wells")

    miss = df["precip_mm"].isna().mean()
    if miss > 0.01:
        print(f"  WARNING: {miss:.1%} of well-days have no weather. "
              f"Re-run 03_openmeteo.py — every well needs full coverage.",
              file=sys.stderr)

    out = (df.groupby("entity_id", group_keys=True)
             .apply(build_entity, include_groups=False)
             .reset_index(level=0))
    out["entity_type"] = "well"
    return out


def urban(con) -> pd.DataFrame:
    if table_count(con, "reservoir_daily") == 0:
        print("[urban] reservoir_daily is EMPTY. Skipping.", file=sys.stderr)
        return pd.DataFrame()

    df = read(con, """
        SELECT r.reservoir_id AS entity_id, r.date,
               r.live_storage_pct AS level,
               CASE WHEN r.source IN ('wrd_pravah','manual') THEN 1 ELSE 0 END
                    AS is_observed,
               w.precip_mm, w.et0_mm, w.soil_moist_0_7, w.soil_moist_7_28,
               w.temp_max, w.rh_mean
        FROM reservoir_daily r
        LEFT JOIN weather_daily w
               ON w.well_id = r.reservoir_id AND w.date = r.date
        ORDER BY r.reservoir_id, r.date
    """)
    df["date"] = pd.to_datetime(df["date"])
    df["confidence"] = np.where(df["is_observed"] == 1, 1.0, 0.6)
    print(f"[urban] {len(df):,} daily rows across "
          f"{df.entity_id.nunique()} entities")

    # weather for reservoirs comes from 03_openmeteo.py fed with reservoirs.csv
    if df["precip_mm"].isna().all():
        print("  NOTE: no weather for reservoirs. Run:\n"
              "    python ingest/03_openmeteo.py --source csv "
              "--csv data/interim/reservoirs.csv\n"
              "  (rename reservoir_id → well_id first, or pass it as-is; the "
              "column check is on well_id/lat/lon)", file=sys.stderr)

    out = (df.groupby("entity_id", group_keys=True)
             .apply(build_entity, include_groups=False)
             .reset_index(level=0))
    out["entity_type"] = "reservoir"
    return out


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rural-only", action="store_true")
    ap.add_argument("--urban-only", action="store_true")
    ap.add_argument("--keep-warmup", action="store_true",
                    help="keep rows whose long lags are still null")
    args = ap.parse_args()
    
    with log_run("06_features.py") as run:
        with connect() as con:
            parts = []
            if not args.urban_only:
                parts.append(rural(con))
            if not args.rural_only:
                parts.append(urban(con))
            parts = [p for p in parts if len(p)]
            if not parts:
                sys.exit("ERROR: nothing to build. gw_daily and reservoir_daily "
                         "are both empty.")

            df = pd.concat(parts, ignore_index=True)
            df["split"] = pd.NA
            for track, etype in (("rural", "well"), ("urban", "reservoir")):
                m = df["entity_type"] == etype
                if m.any():
                    df.loc[m, "split"] = assign_split(
                        df.loc[m, "date"], track).values

            before = len(df)
            df = df[df["split"].notna()]
            print(f"\n[trim] dropped {before - len(df):,} rows outside their "
                  f"track's split window "
                  f"(rural test ends {cfg.splits['test_end']})")

            before = len(df)
            df = df[df["target_level_t30"].notna()]
            print(f"[trim] dropped {before - len(df):,} rows with no t+30 label")

            if not args.keep_warmup:
                before = len(df)
                df = df[df["level_lag_30"].notna() & df["rain_30d"].notna()]
                print(f"[trim] dropped {before - len(df):,} warm-up rows "
                      f"(lags not yet filled)")

            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            n = replace_table(con, "features", df)
            print(f"\n[load] {n:,} rows → features")

            # ---------------- acceptance checks ----------------
            ok = True

            dupes = con.execute(
                "SELECT COUNT(*) FROM (SELECT entity_id, date FROM features "
                "GROUP BY entity_id, date HAVING COUNT(*) > 1)").fetchone()[0]
            print(f"\n[check] duplicate (entity_id, date): {dupes} "
                  f"{'OK' if dupes == 0 else '<< FAIL'}")
            ok &= dupes == 0

            print("[check] nulls in required columns:")
            for c in REQUIRED_NOT_NULL:
                k = con.execute(f"SELECT COUNT(*) FROM features "
                                f"WHERE {c} IS NULL").fetchone()[0]
                flag = "OK" if k == 0 else "<< FAIL"
                print(f"    {c:<22} {k:>8,}  {flag}")
                ok &= k == 0

            print("\n[check] split sizes per track "
                  "(the two tracks have different coverage):")
            for et in ("well", "reservoir"):
                rows = con.execute(
                    "SELECT split, COUNT(*) n, MIN(date) a, MAX(date) b, "
                    "COUNT(DISTINCT entity_id) e FROM features "
                    "WHERE entity_type=? GROUP BY split ORDER BY a", (et,)
                ).fetchall()
                if not rows:
                    continue
                print(f"    {et}:")
                for r in rows:
                    print(f"      {r['split']:<6} {r['n']:>9,} rows  "
                          f"{r['a']} → {r['b']}  ({r['e']} entities)")
                if et == "well" and {r["split"] for r in rows} != {"train", "val", "test"}:
                    print("      << FAIL: a split is empty. Check that "
                          "config splits.rural sits inside the data's coverage.")

            print("\n[check] target correlation with lagged level "
                  "(should be strongly positive):")
            fd = read(con, "SELECT entity_type, level_lag_30, level, "
                           "target_level_t30 FROM features")
            for et, g in fd.groupby("entity_type"):
                c1 = g["level"].corr(g["target_level_t30"])
                c2 = g["level_lag_30"].corr(g["target_level_t30"])
                print(f"    {et:<10} corr(level, t+30) = {c1:.3f} | "
                      f"corr(lag30, t+30) = {c2:.3f}")
                if pd.notna(c1) and c1 < 0.3:
                    if et == "well":
                        print("      WARNING: weak persistence in the rural track. "
                              "Check the sign convention on level_mbgl (bigger = "
                              "deeper = worse) before trusting any model.",
                              file=sys.stderr)
                    else:
                        print("      NOTE: urban series spans roughly one season, "
                              "so a monotonic drawdown-then-refill anti-correlates "
                              "at t+30. Expected with this much data — do not read "
                              "it as a bug, and do not train on it alone.",
                              file=sys.stderr)

            urban_rows = con.execute(
                "SELECT COUNT(*) FROM features WHERE entity_type='reservoir'"
            ).fetchone()[0]
            if 0 < urban_rows < 2000:
                print(f"\n[check] urban track has only {urban_rows:,} rows "
                      f"(~1 season of public aggregates).")
                print("        Use it for the demo narrative and the stress score.")
                print("        Do NOT claim a trained urban forecast on this alone.")

            obs = con.execute(
                "SELECT ROUND(100.0*AVG(is_observed),2) FROM features "
                "WHERE entity_type='well'").fetchone()[0]
            if obs is not None:
                print(f"\n[check] rural rows backed by a REAL reading: {obs}%")
                print("        (this is the number you quote, not 100%)")

            print(f"\n{'ACCEPTANCE: PASS' if ok else 'ACCEPTANCE: FAIL — fix before freeze'}")
            run.rows_out = n
            if not ok:
                sys.exit(1)


if __name__ == "__main__":
    main()
