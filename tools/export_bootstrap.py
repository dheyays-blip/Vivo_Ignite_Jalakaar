#!/usr/bin/env python3
"""
JALAAKAR — export the minimum needed to rebuild a working database.

    python tools/export_bootstrap.py

Writes data/bootstrap/*.parquet. Those files ARE committed; `data/jalaakar.db`
is not, because it is 1.9 GB. A fresh clone runs `tools/bootstrap.py` and gets
a working database out of these in seconds, with no network.

What is exported, and why only this
-----------------------------------
The API reads six tables. Four of them are tiny or regenerable:

    wells             940 rows      exported (35 KB)
    gw_observations   68,994 rows   exported (143 KB)
    weather_daily     3.86M rows    exported — the only large one
    reservoirs        15 rows       regenerated from 04_reservoirs.py
    reservoir_daily   121 rows      regenerated from reservoir_seeds.csv
    urban_stress      121 rows      regenerated from 07_stress.py

Deliberately NOT exported:

    gw_daily      3.25M rows of interpolation. Nothing in the serving path
                  reads it, and ml/01_baseline.py showed it leaks the target.
    features      3.19M rows built FROM gw_daily, so it inherits that leak.
                  It is superseded by features_causal. Shipping 196 MB of a
                  table the README tells people not to use is not a service.
    features_causal  Rebuildable with ingest/06b_features_causal.py from what
                  is here. Only the training and verification scripts need it.

Net effect on the repository: features.parquet (196 MB) comes out, weather
goes in. The clone gets smaller AND starts working.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import connect, read  # noqa: E402

OUT = ROOT / "data" / "bootstrap"

TABLES = {
    "wells": "the 940-well registry — coordinates, taluka, specific yield",
    "gw_observations": "68,994 real CGWB readings — the system of record",
    "weather_daily": "NASA POWER daily weather; the only large export",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-weather", action="store_true",
                    help="skip weather_daily (smaller repo, degraded scores)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    with connect() as con:
        for t, note in TABLES.items():
            if t == "weather_daily" and args.no_weather:
                print(f"  {t:<18} skipped (--no-weather)")
                continue
            df = read(con, f"SELECT * FROM {t}")
            p = OUT / f"{t}.parquet"
            df.to_parquet(p, index=False, compression="snappy")
            mb = p.stat().st_size / 1e6
            total += mb
            print(f"  {t:<18} {len(df):>10,} rows  {mb:>7.1f} MB   {note}")

    print(f"\n  {total:.1f} MB total in data/bootstrap/")
    print("  Commit these; data/jalaakar.db stays ignored.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
