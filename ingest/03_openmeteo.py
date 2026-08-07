#!/usr/bin/env python3
"""
JALAAKAR — Stage 3: Open-Meteo historical weather.
Owner: Dev B.

Pulls daily precipitation, ET0, temperature, humidity and (hourly→daily mean)
soil moisture for every well / reservoir coordinate, then materialises the
`weather_daily` table.

Key behaviours
--------------
* Coordinates are deduped to a 0.1° grid before calling. Many wells share an
  ERA5 cell, so this typically halves the request count.
* Every response is cached to disk via requests-cache. Re-runs are free and
  never re-hit the API. Interrupt and restart at will.
* Each grid cell is also written to data/raw/openmeteo/*.parquet, so the load
  step can run offline.
* Runs against 3 hardcoded Nashik coordinates until Dev A's mh_wells.csv
  lands (--source stub). Swapping to real wells is one flag.

Usage
-----
    # before A's handoff — proves the client works
    python ingest/03_openmeteo.py --source stub

    # after H2 lands
    python ingest/03_openmeteo.py --source csv --csv data/interim/mh_wells.csv

    # see the plan without spending a single call
    python ingest/03_openmeteo.py --source csv --csv <path> --dry-run

    # re-materialise weather_daily from the parquet cache, no network
    python ingest/03_openmeteo.py --source csv --csv <path> --offline
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import (  # noqa: E402
    ROOT, cfg, connect, dedupe_coords, log_run, summary, table_count, upsert,
)

RAW_DIR = ROOT / "data" / "raw" / "openmeteo"

DAILY_VARS = [
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "temperature_2m_max",
    "relative_humidity_2m_mean",
]
HOURLY_VARS = [
    "soil_moisture_0_to_7cm",
    "soil_moisture_7_to_28cm",
]

RENAME = {
    "precipitation_sum": "precip_mm",
    "et0_fao_evapotranspiration": "et0_mm",
    "temperature_2m_max": "temp_max",
    "relative_humidity_2m_mean": "rh_mean",
    "soil_moisture_0_to_7cm": "soil_moist_0_7",
    "soil_moisture_7_to_28cm": "soil_moist_7_28",
}
OUT_COLS = ["date", "precip_mm", "et0_mm", "soil_moist_0_7",
            "soil_moist_7_28", "temp_max", "rh_mean"]

# 3 Nashik coordinates — Dindori, Nashik city, Niphad. Stand-ins until H2.
STUB_WELLS = pd.DataFrame(
    {
        "well_id": ["STUB_DINDORI", "STUB_NASHIK", "STUB_NIPHAD"],
        "lat": [20.2010, 19.9975, 20.0800],
        "lon": [73.8330, 73.7898, 74.1100],
        "district": ["Nashik"] * 3,
        "taluka": ["Dindori", "Nashik", "Niphad"],
        "first_obs": ["2015-01-01"] * 3,
    }
)

LAG_BUFFER_DAYS = 120  # enough history to fill the 90-day lags/rollings
END_BUFFER_DAYS = 30   # slack past last_obs + horizon


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------
def make_session(cache_path: Path):
    """Cached session if requests-cache is available, plain session otherwise."""
    try:
        import requests_cache

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        s = requests_cache.CachedSession(
            str(cache_path),
            backend="sqlite",
            expire_after=None,          # archive data is immutable
            allowable_codes=(200,),
            stale_if_error=True,
        )
        print(f"[cache] {cache_path}.sqlite")
        return s, True
    except ImportError:
        print("[cache] requests-cache NOT installed — re-runs will re-hit the API.",
              file=sys.stderr)
        print("        pip install requests-cache", file=sys.stderr)
        return requests.Session(), False


def fetch_cell(session, lat: float, lon: float, start: str,
               end: str) -> pd.DataFrame:
    """One Open-Meteo archive call → tidy daily frame for this grid cell."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": ",".join(DAILY_VARS),
        "hourly": ",".join(HOURLY_VARS),
        "timezone": cfg.openmeteo_timezone,
    }

    last_err = None
    for attempt in range(cfg.openmeteo_max_retries):
        try:
            r = session.get(cfg.openmeteo_url, params=params,
                            timeout=cfg.openmeteo_timeout_s)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 2 ** attempt * 5
                print(f"    HTTP {r.status_code} — backing off {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return _parse(r.json())
        except requests.RequestException as e:
            last_err = e
            wait = 2 ** attempt * 3
            print(f"    {type(e).__name__} — retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Open-Meteo failed for ({lat},{lon}): {last_err}")


def _parse(js: dict) -> pd.DataFrame:
    if "daily" not in js:
        raise ValueError(f"no 'daily' block in response: {str(js)[:300]}")

    daily = pd.DataFrame(js["daily"]).rename(columns={"time": "date"})
    daily["date"] = pd.to_datetime(daily["date"])

    if "hourly" in js:
        h = pd.DataFrame(js["hourly"]).rename(columns={"time": "date"})
        h["date"] = pd.to_datetime(h["date"])
        sm = (
            h.set_index("date")[HOURLY_VARS]
            .resample("D").mean()
            .reset_index()
        )
        daily = daily.merge(sm, on="date", how="left")
    else:
        for v in HOURLY_VARS:
            daily[v] = pd.NA

    daily = daily.rename(columns=RENAME)
    for c in OUT_COLS:
        if c not in daily.columns:
            daily[c] = pd.NA
    return daily[OUT_COLS]


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------
def load_points(args) -> pd.DataFrame:
    """Return well_id, lat, lon, start (per-point earliest date needed)."""
    if args.source == "stub":
        pts = STUB_WELLS.copy()
        print("[input] STUB — 3 hardcoded Nashik coordinates (no dependency on Dev A)")
    else:
        path = Path(args.csv)
        if not path.exists():
            sys.exit(f"ERROR: {path} not found. Waiting on handoff H2 from Dev A.")
        pts = pd.read_csv(path)
        print(f"[input] {path} — {len(pts)} rows")

    pts.columns = [c.strip().lower() for c in pts.columns]
    # reservoirs.csv keys on reservoir_id; weather_daily.well_id holds both
    if "well_id" not in pts.columns and "reservoir_id" in pts.columns:
        pts = pts.rename(columns={"reservoir_id": "well_id"})
        print("  (reservoir_id → well_id: weather_daily holds both entity kinds)")
    for req in ("well_id", "lat", "lon"):
        if req not in pts.columns:
            sys.exit(f"ERROR: {args.csv} missing required column '{req}'. "
                     f"Got: {list(pts.columns)}")

    pts = pts.dropna(subset=["lat", "lon"]).copy()
    pts["lat"] = pts["lat"].astype(float)
    pts["lon"] = pts["lon"].astype(float)

    bb = cfg.bbox
    outside = ~(
        pts["lat"].between(bb["lat_min"], bb["lat_max"])
        & pts["lon"].between(bb["lon_min"], bb["lon_max"])
    )
    if outside.any():
        print(f"  warning: {int(outside.sum())} points outside the Maharashtra bbox "
              f"— dropping. Check A's lat/lon are not swapped.", file=sys.stderr)
        pts = pts[~outside]

    if args.limit:
        pts = pts.head(args.limit)
        print(f"  --limit {args.limit} → {len(pts)} points")

    # earliest date we need per point
    floor = pd.Timestamp(cfg.history_floor)
    if "first_obs" in pts.columns:
        start = pd.to_datetime(pts["first_obs"], errors="coerce")
        start = start - pd.Timedelta(days=LAG_BUFFER_DAYS)
    else:
        start = pd.Series(pd.NaT, index=pts.index)
    start = start.fillna(pd.Timestamp(cfg.last5_start) - pd.Timedelta(days=LAG_BUFFER_DAYS))
    pts["start"] = start.clip(lower=floor)

    # latest date we need per point. Wells stop being useful shortly after
    # their last reading + the forecast horizon; only reservoirs need "today".
    # Pulling to today for every well would fetch years of weather that no
    # row can ever use.
    hard_end = pd.Timestamp(args.end or cfg.end_date)
    if "last_obs" in pts.columns and not args.end:
        tail = pd.Timedelta(days=cfg.horizon + END_BUFFER_DAYS)
        pts["end"] = (pd.to_datetime(pts["last_obs"], errors="coerce") + tail
                      ).fillna(hard_end).clip(upper=hard_end)
        saved = (hard_end - pts["end"]).dt.days.clip(lower=0).sum()
        if saved > 0:
            print(f"  end dates trimmed to last_obs + "
                  f"{cfg.horizon + END_BUFFER_DAYS}d "
                  f"— {saved:,} point-days of unusable weather skipped")
            print(f"  (pass --end {hard_end.date()} to override)")
    else:
        pts["end"] = hard_end

    return pts.reset_index(drop=True)


def cell_path(lat: float, lon: float) -> Path:
    return RAW_DIR / f"g_{lat:+.2f}_{lon:+.2f}.parquet".replace("+", "p").replace("-", "m")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["stub", "csv"], default="stub")
    ap.add_argument("--csv", default="data/interim/mh_wells.csv")
    ap.add_argument("--end", default=None, help="default: config.today")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="plan only, zero calls")
    ap.add_argument("--offline", action="store_true",
                    help="skip the network, rebuild weather_daily from parquet cache")
    ap.add_argument("--no-load", action="store_true", help="fetch only, skip the DB write")
    args = ap.parse_args()

    end = args.end or str(cfg.end_date)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    marker = RAW_DIR / "_SYNTHETIC_DO_NOT_SHIP"
    if marker.exists():
        listed = [x for x in marker.read_text().split() if x]
        print("\n" + "!" * 70, file=sys.stderr)
        print(f"SYNTHETIC WEATHER CACHE: {len(listed)} fabricated parquet cells "
              f"are sitting in {RAW_DIR}.", file=sys.stderr)
        print("These came from tools/make_fixtures.py and are NOT real data. "
              "Delete them and this marker before any run you intend to ship.",
              file=sys.stderr)
        print("!" * 70 + "\n", file=sys.stderr)

    pts = load_points(args)
    grid = dedupe_coords(pts, precision=cfg.coord_precision)

    # earliest start required within each cell
    p = pts.copy()
    prec = cfg.coord_precision
    p["grid_lat"] = ((p["lat"] / prec).round() * prec).round(4)
    p["grid_lon"] = ((p["lon"] / prec).round() * prec).round(4)
    cell_span = (p.groupby(["grid_lat", "grid_lon"])
                   .agg(start=("start", "min"), end=("end", "max"))
                   .reset_index())
    grid = grid.merge(cell_span, on=["grid_lat", "grid_lon"])

    print(f"\n[plan] {len(pts)} points → {len(grid)} grid cells "
          f"({100 * (1 - len(grid) / max(len(pts), 1)):.0f}% fewer calls)")
    print(f"       date range {grid['start'].min().date()} → "
          f"{grid['end'].max().date()}")
    est_rows = int((grid["end"] - grid["start"]).dt.days.sum())
    print(f"       ~{est_rows:,} weather rows before fan-out to wells")
    if args.dry_run:
        print("\n--dry-run: stopping before any network call.")
        print(grid.assign(members=grid["members"].str[:3]).to_string(index=False))
        return

    session, cached = make_session(cfg.path("cache"))

    with log_run("03_openmeteo.py", rows_in=len(pts)) as run:
        # ---------------- fetch ----------------
        frames: dict[tuple, pd.DataFrame] = {}
        n_fetched = n_reused = 0
        for i, row in grid.iterrows():
            key = (row.grid_lat, row.grid_lon)
            path = cell_path(*key)
            start = row.start.strftime("%Y-%m-%d")
            cell_end = row.end.strftime("%Y-%m-%d")

            if path.exists():
                df = pd.read_parquet(path)
                have_start = pd.to_datetime(df["date"]).min()
                have_end = pd.to_datetime(df["date"]).max()
                if have_start <= row.start and have_end >= row.end:
                    frames[key] = df
                    n_reused += 1
                    continue

            if args.offline:
                print(f"  [{i+1}/{len(grid)}] MISSING parquet for {key} — "
                      f"--offline cannot fetch it", file=sys.stderr)
                continue

            print(f"  [{i+1}/{len(grid)}] {key} {start}→{cell_end} "
                  f"({row.n_members} well{'s' if row.n_members > 1 else ''})")
            df = fetch_cell(session, key[0], key[1], start, cell_end)
            df.to_parquet(path, index=False)
            frames[key] = df
            n_fetched += 1

            from_cache = getattr(session, "cache", None) is not None and \
                getattr(session, "_last_from_cache", False)
            if not from_cache:
                time.sleep(cfg.openmeteo_sleep_s)

        print(f"\n[fetch] {n_fetched} cells pulled, {n_reused} reused from parquet, "
              f"{len(frames)}/{len(grid)} available")
        if len(frames) < len(grid):
            print("  WARNING: some cells missing — weather_daily will have gaps.",
                  file=sys.stderr)

        if args.no_load:
            run.rows_out = 0
            return

        # ---------------- fan out to wells + load ----------------
        total = 0
        with connect() as con:
            for _, row in grid.iterrows():
                key = (row.grid_lat, row.grid_lon)
                if key not in frames:
                    continue
                base = frames[key]
                for wid in row.members:
                    w = base.copy()
                    w.insert(0, "well_id", wid)
                    total += upsert(con, "weather_daily", w)
            print(f"\n[load] {total:,} rows → weather_daily")
            print(summary(con).to_string(index=False))

            # ---------------- acceptance checks ----------------
            print("\n[check] monsoon signal by month (mean daily precip, mm):")
            m = con.execute(
                "SELECT CAST(strftime('%m', date) AS INTEGER) AS month, "
                "ROUND(AVG(precip_mm),2) AS mean_precip "
                "FROM weather_daily GROUP BY month ORDER BY month"
            ).fetchall()
            for r in m:
                bar = "#" * int((r["mean_precip"] or 0) * 2)
                print(f"   {r['month']:>2}  {r['mean_precip']:>6}  {bar}")
            wet = {r["month"]: (r["mean_precip"] or 0) for r in m}
            if wet:
                peak = max(wet, key=wet.get)
                verdict = "OK" if peak in (6, 7, 8, 9) else "!! WRONG — check dates/units"
                print(f"   peak month = {peak}  [{verdict}]")

            gaps = con.execute(
                "SELECT COUNT(*) FROM weather_daily WHERE precip_mm IS NULL"
            ).fetchone()[0]
            print(f"[check] null precip rows: {gaps}")
            print(f"[check] distinct entities: "
                  f"{con.execute('SELECT COUNT(DISTINCT well_id) FROM weather_daily').fetchone()[0]}")

            run.rows_out = total


if __name__ == "__main__":
    main()
