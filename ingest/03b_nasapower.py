#!/usr/bin/env python3
"""
Stage 3 FALLBACK — NASA POWER daily weather.
Owner: Dev A (written when Open-Meteo's quota was exhausted mid-pull).

Drop-in replacement for 03_openmeteo.py. Writes the SAME `weather_daily`
columns, so everything downstream is unchanged. Use it when Open-Meteo returns
HTTP 429 and you cannot wait for the UTC-midnight reset.

    https://power.larc.nasa.gov/api/temporal/daily/point

Verified response shape:
    {"properties": {"parameter": {"PRECTOTCORR": {"20230601": 0.0, ...}}},
     "header": {"fill_value": -999.0, "sources": ["MERRA2"]}}

DIFFERENCES FROM OPEN-METEO — say these out loud if asked:
  * Source is MERRA-2, not ERA5. Native grid ~0.5 x 0.625 deg (~55 km) vs
    ERA5's 0.25 deg, so the default dedupe here is 0.5 deg. Coarser rainfall.
  * No key, no meaningful rate limit for this volume.
  * ET0 is NOT served directly. We compute Hargreaves reference ET from
    T2M_MAX / T2M_MIN / T2M plus extraterrestrial radiation — the standard
    FAO-56 fallback when radiation data is unavailable. Documented, not fudged.
  * Soil moisture is not fetched; those columns stay NULL, same as
    03_openmeteo.py --no-soil.

Usage:
    python ingest/03b_nasapower.py --csv data/interim/mh_wells.csv
    python ingest/03b_nasapower.py --csv data/interim/mh_wells.csv --dry-run
    python ingest/03b_nasapower.py --csv data/interim/mh_wells.csv --only-missing
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import (  # noqa: E402
    ROOT, cfg, connect, dedupe_coords, log_run, summary, upsert,
)

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["PRECTOTCORR", "T2M_MAX", "T2M_MIN", "T2M", "RH2M"]
FILL = -999.0
RAW_DIR = ROOT / "data" / "raw" / "nasapower"
GRID_DEG = 0.5          # MERRA-2 native-ish; override with --precision
SLEEP_S = 0.3
RETRIES = 4


# ------------------------------------------------------------------ ET0
def hargreaves_et0(lat: float, doy: np.ndarray, tmax: np.ndarray,
                   tmin: np.ndarray, tmean: np.ndarray) -> np.ndarray:
    """FAO-56 Hargreaves reference evapotranspiration, mm/day.

    Used because POWER does not serve ET0 directly. Needs only temperature
    and latitude, which is exactly the case FAO-56 recommends it for.
    """
    phi = np.radians(lat)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    ra = (24 * 60 / np.pi) * 0.0820 * dr * (
        ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws)
    )                                                  # MJ m-2 day-1
    dt = np.clip(tmax - tmin, 0, None)
    return np.clip(0.0023 * (tmean + 17.8) * np.sqrt(dt) * ra * 0.408, 0, None)


# ------------------------------------------------------------------ fetch
def fetch_cell(lat: float, lon: float, start: str, end: str) -> pd.DataFrame | None:
    q = {
        "parameters": ",".join(PARAMS), "community": "AG",
        "latitude": lat, "longitude": lon,
        "start": start.replace("-", ""), "end": end.replace("-", ""),
        "format": "JSON",
    }
    for attempt in range(RETRIES):
        try:
            r = requests.get(URL, params=q, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 2 ** attempt * 4
                print(f"    HTTP {r.status_code} — backing off {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return _parse(r.json(), lat)
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"    {type(e).__name__}: {e} — retry {attempt+1}/{RETRIES}",
                  file=sys.stderr)
            time.sleep(2 ** attempt * 3)
    print(f"    GIVING UP on ({lat},{lon})", file=sys.stderr)
    return None


def _parse(js: dict, lat: float) -> pd.DataFrame:
    p = js["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(FILL, np.nan).sort_index()

    doy = df.index.dayofyear.to_numpy()
    out = pd.DataFrame({
        "date": df.index,
        "precip_mm": df["PRECTOTCORR"].to_numpy(),
        "et0_mm": hargreaves_et0(lat, doy, df["T2M_MAX"].to_numpy(),
                                 df["T2M_MIN"].to_numpy(), df["T2M"].to_numpy()),
        "soil_moist_0_7": np.nan,
        "soil_moist_7_28": np.nan,
        "temp_max": df["T2M_MAX"].to_numpy(),
        "rh_mean": df["RH2M"].to_numpy(),
    })
    return out.reset_index(drop=True)


def cell_path(lat, lon) -> Path:
    return RAW_DIR / f"power_{lat:+07.3f}_{lon:+08.3f}.parquet"


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/interim/mh_wells.csv")
    ap.add_argument("--precision", type=float, default=GRID_DEG)
    ap.add_argument("--start", default=None, help="default: config history_floor")
    ap.add_argument("--end", default=None, help="default: config gw_end + 60d")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-missing", action="store_true",
                    help="skip wells that already have weather_daily rows")
    ap.add_argument("--no-load", action="store_true")
    a = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pts = pd.read_csv(a.csv)
    pts.columns = [c.strip().lower() for c in pts.columns]
    if "well_id" not in pts and "reservoir_id" in pts:
        pts = pts.rename(columns={"reservoir_id": "well_id"})

    if a.only_missing:
        with connect() as con:
            have = {r[0] for r in con.execute(
                "SELECT DISTINCT well_id FROM weather_daily")}
        before = len(pts)
        pts = pts[~pts.well_id.isin(have)]
        print(f"[skip] {before - len(pts)} wells already have weather")

    if pts.empty:
        sys.exit("nothing to do — every well already has weather")

    start = a.start or str(cfg.history_floor)
    end = a.end or str(pd.Timestamp(cfg.gw_end) + pd.Timedelta(days=60))[:10]
    grid = dedupe_coords(pts[["well_id", "lat", "lon"]], precision=a.precision)

    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    print(f"[input] {a.csv} — {len(pts)} wells")
    print(f"[plan]  {len(pts)} points → {len(grid)} cells at {a.precision}° "
          f"({(1-len(grid)/len(pts))*100:.0f}% fewer calls)")
    print(f"        {start} → {end}  ({days:,} days/cell)")
    print(f"        ~{len(pts)*days:,} rows after fan-out")
    if a.dry_run:
        print("--dry-run: stopping before any network call.")
        return

    with log_run("03b_nasapower.py", rows_in=len(pts)) as run:
        frames, failed, reused = {}, [], 0
        for i, row in grid.iterrows():
            key = (row.grid_lat, row.grid_lon)
            path = cell_path(*key)
            if path.exists():
                frames[key] = pd.read_parquet(path)
                reused += 1
                continue
            print(f"  [{i+1}/{len(grid)}] {key} ({row.n_members} wells)")
            df = fetch_cell(key[0], key[1], start, end)
            if df is None:
                failed.append(key)
                continue
            df.to_parquet(path, index=False)
            frames[key] = df
            time.sleep(SLEEP_S)

        print(f"\n[fetch] {len(frames)-reused} pulled, {reused} cached, "
              f"{len(frames)}/{len(grid)} available")
        if failed:
            print(f"  {len(failed)} failed — re-run to resume from cache",
                  file=sys.stderr)
        if a.no_load:
            run.rows_out = 0
            return

        total = 0
        with connect() as con:
            for _, row in grid.iterrows():
                df = frames.get((row.grid_lat, row.grid_lon))
                if df is None:
                    continue
                for wid in row.members:
                    total += upsert(con, "weather_daily", df.assign(well_id=wid))
            run.rows_out = total
            print(f"[load] {total:,} rows → weather_daily")
            print()
            print(summary(con).to_string(index=False))

            print("\n[check] monsoon signal (mean daily precip, mm):")
            for m, v in con.execute(
                "SELECT CAST(strftime('%m',date) AS INT) m, ROUND(AVG(precip_mm),2) v "
                "FROM weather_daily GROUP BY m ORDER BY m"
            ):
                print(f"   {m:>2}  {v:>6}  {'#' * int(min(v, 30))}")
            peak = con.execute(
                "SELECT CAST(strftime('%m',date) AS INT) m FROM weather_daily "
                "GROUP BY m ORDER BY AVG(precip_mm) DESC LIMIT 1").fetchone()[0]
            print(f"   peak month = {peak}  "
                  f"{'[OK]' if peak in (6,7,8,9) else '[WRONG — check dates/units]'}")


if __name__ == "__main__":
    main()
