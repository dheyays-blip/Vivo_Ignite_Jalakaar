#!/usr/bin/env python3
"""
Export the frozen database to Parquet for model training.

WHY
---
`pd.read_sql("SELECT * FROM features")` gets OOM-killed — 3.19M rows x 31
columns does not survive the round trip through SQLite's row objects. Parquet
is columnar, so it loads in 0.4s, is 205 MB instead of 1.9 GB, and lets you
read only the columns you need.

    SQLite full load : OOM
    parquet full     : 0.4s -> 0.87 GB RAM
    parquet 5 cols   : 0.1s -> 0.30 GB RAM

Only tables the model actually needs are exported. `gw_daily` and
`weather_daily` are deliberately skipped: `features` already carries the level,
is_observed, confidence and every weather column, joined and aligned. Exporting
7M more rows you'd never open is not a service.

The SQLite file remains the system of record. These are derived artefacts —
delete and regenerate them freely.

Usage:
    python tools/export_parquet.py                         # uses config db
    python tools/export_parquet.py --db data/FROZEN_x.db   # the frozen copy
"""

from __future__ import annotations

import argparse
import gc
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import cfg  # noqa: E402

# all-NULL for every well — dropping them saves space and stops anyone
# wasting an afternoon wondering why the column does nothing
ALL_NULL = ["soil_moist_0_7", "soil_moist_7_28"]
CATEGORICAL = ["entity_type", "season", "split"]

# table -> (chunked?, note)
TABLES = {
    "features":        (True,  "the training table — everything the model reads"),
    "wells":           (False, "registry: taluka, lat/lon, specific_yield, sy_source"),
    "gw_observations": (False, "REAL readings — use these to report honest accuracy"),
    "reservoirs":      (False, "urban registry, 14 rows"),
    "reservoir_daily": (False, "urban storage, rule-based score only — not modelled"),
}


def export(con, table: str, out: Path, chunked: bool) -> tuple[int, float]:
    t0 = time.time()
    if not chunked:
        df = pd.read_sql(f"SELECT * FROM {table}", con)
        for c in CATEGORICAL:
            if c in df.columns:
                df[c] = df[c].astype("category")
        df.to_parquet(out, compression="zstd", index=False)
        return len(df), time.time() - t0

    writer, n = None, 0
    for chunk in pd.read_sql(f"SELECT * FROM {table}", con,
                             parse_dates=["date"], chunksize=250_000):
        chunk = chunk.drop(columns=[c for c in ALL_NULL if c in chunk.columns])
        for c in CATEGORICAL:
            if c in chunk.columns:
                chunk[c] = chunk[c].astype("category")
        tb = pa.Table.from_pandas(chunk, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out, tb.schema, compression="zstd")
        writer.write_table(tb)
        n += len(chunk)
        del chunk, tb
        gc.collect()
    if writer:
        writer.close()
    return n, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="default: config paths.db")
    ap.add_argument("--out", default=str(ROOT / "data" / "parquet"))
    a = ap.parse_args()

    db = Path(a.db) if a.db else cfg.db_path
    if not db.exists():
        sys.exit(f"[FAIL] {db} not found")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    print(f"[src] {db}  ({db.stat().st_size / 1e6:,.0f} MB)")
    print(f"[dst] {out}/\n")

    total = 0
    for table, (chunked, note) in TABLES.items():
        try:
            path = out / f"{table}.parquet"
            n, secs = export(con, table, path, chunked)
            mb = path.stat().st_size / 1e6
            total += mb
            print(f"  {table:<18}{n:>10,} rows  {mb:>7,.1f} MB  {secs:5.1f}s   {note}")
        except Exception as e:                                  # noqa: BLE001
            print(f"  {table:<18}FAILED: {e}", file=sys.stderr)

    print(f"\n  total {total:,.1f} MB  (vs {db.stat().st_size / 1e6:,.0f} MB SQLite)")
    print(f"""
Load it:

    import pandas as pd
    df = pd.read_parquet("{out.relative_to(ROOT)}/features.parquet")
    train = df[df.split == "train"]
    val   = df[df.split == "val"]
    test  = df[df.split == "test"]

    # only the columns you need — much faster, much less RAM
    y = pd.read_parquet("{out.relative_to(ROOT)}/features.parquet",
                        columns=["entity_id", "date", "level",
                                 "target_level_t30", "confidence", "split"])

Reminders that will save you on Tuesday:
  * NEVER re-split randomly. `split` is chronological; random leaks the future.
  * Only 0.88% of rows are real measurements. Weight by `confidence`, or report
    accuracy on is_observed=1 rows only — otherwise you are measuring how well
    the model predicts your own interpolation.
  * soil_moist_* are dropped here because they are 100% NULL.
""")


if __name__ == "__main__":
    main()
