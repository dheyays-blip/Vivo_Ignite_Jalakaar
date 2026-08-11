#!/usr/bin/env python3
"""
JALAAKAR — build a working data/jalaakar.db from what the repository ships.

    python tools/bootstrap.py

Run once after cloning. Takes about 30 seconds, needs no network, and does not
touch anything you already have unless you pass --force.

Why this exists
---------------
`data/jalaakar.db` is 1.9 GB, so it is not in git. But without it the API can
score nothing, and "clone the repo and run it" has to actually work. So the
repository ships the irreducible parts as Parquet — the well registry, the
68,994 real CGWB readings, and the weather series — and everything else is
regenerated here from code and from `ingest/reservoir_seeds.csv`.

That split is deliberate. Measurements are data and must be shipped.
Interpolations, features and scores are OUTPUT and are rebuilt, so nobody
inherits a stale copy of a number they cannot trace.

What it produces
----------------
    wells, gw_observations, weather_daily   loaded from data/bootstrap/
    reservoirs, reservoir_daily             from ingest/reservoir_seeds.csv
    urban_stress                            computed by ingest/07_stress.py

The rural forecast reads wells + gw_observations + weather_daily directly, so
that is enough for every endpoint. `features_causal` is only needed to RETRAIN
or to run the verification scripts; build it with
`python ingest/06b_features_causal.py` if you want those.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BOOT = ROOT / "data" / "bootstrap"
DB = ROOT / "data" / "jalaakar.db"


def _fail(con=None) -> int:
    """Leave nothing half-built.

    A partially loaded database is worse than none: the next run sees a file
    with a `wells` table, decides it is "already built", and the API then
    serves an empty registry. Remove it so the next attempt starts clean.
    """
    if con is not None:
        try:
            con.close()
        except Exception:                               # noqa: BLE001
            pass
    for p in (DB, DB.with_suffix(".db-wal"), DB.with_suffix(".db-shm")):
        if p.exists():
            p.unlink()
    print("\n  Removed the partial database — nothing half-built left behind.\n")
    return 1


def step(n: int, msg: str) -> None:
    print(f"\n  [{n}/5] {msg}")


def run(cmd: list[str], why: str) -> bool:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"        FAILED: {why}")
        print("        " + (r.stderr.strip().splitlines() or ["(no output)"])[-1])
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if data/jalaakar.db already exists")
    args = ap.parse_args()

    print("\n  JALAAKAR — building data/jalaakar.db")

    rebuild = args.force
    if DB.exists() and not args.force:
        import sqlite3
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            n = con.execute("SELECT COUNT(*) FROM wells").fetchone()[0]
            print(f"\n  Already built: {DB.name} with {n:,} wells.")
            print("  Pass --force to rebuild from scratch.\n")
            return 0
        except Exception:
            print("\n  Existing database looks incomplete — rebuilding.")
            rebuild = True
        finally:
            con.close()

    # CHECK THE INPUTS BEFORE DESTROYING THE OUTPUT.
    #
    # The first version deleted the database and *then* looked for the Parquet
    # files. On a machine where data/bootstrap/ had not been exported yet, that
    # sequence destroys a 1.9 GB database that cannot be rebuilt — the only
    # copy, gone, because the tool checked its prerequisites in the wrong order.
    missing = [f"{t}.parquet" for t in ("wells", "gw_observations")
               if not (BOOT / f"{t}.parquet").exists()]
    if not BOOT.exists() or missing:
        print(f"\n  Cannot build — {BOOT.relative_to(ROOT)}/ is "
              f"{'missing' if not BOOT.exists() else 'incomplete: ' + ', '.join(missing)}")
        if DB.exists():
            print(f"\n  Your existing {DB.name} has NOT been touched.")
            print("  Create the Parquet files first:  python tools/export_bootstrap.py")
        else:
            print("\n  If you just cloned this, the LFS files did not download:")
            print("      git lfs install && git lfs pull")
        print()
        return 1

    # Only now is it safe to remove the old database. "Rebuild" has to mean
    # "start from nothing" — the previous version ran CREATE TABLE IF NOT
    # EXISTS over the existing file and then appended the same 940 wells,
    # which died on the UNIQUE constraint. WAL sidecars go too, or they
    # resurrect the old contents.
    if rebuild:
        for p in (DB, DB.with_suffix(".db-wal"), DB.with_suffix(".db-shm")):
            if p.exists():
                p.unlink()
                print(f"  removed {p.name}")

    # ---- 1. schema -------------------------------------------------------
    step(1, "creating the schema")
    import sqlite3
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript((ROOT / "ingest" / "00_schema.sql").read_text())
    con.commit()

    # ---- 2. shipped measurements ----------------------------------------
    step(2, "loading measurements from data/bootstrap/")
    try:
        import pandas as pd
    except ImportError:
        print("        pandas is not installed — run: pip install -r requirements.txt")
        return 1

    try:
        for name in ("wells", "gw_observations", "weather_daily"):
            p = BOOT / f"{name}.parquet"
            if not p.exists():
                if name == "weather_daily":
                    print(f"        {name:<18} not shipped — scores still work, but")
                    print("                           weather features will be null and")
                    print("                           will not match the published MAE.")
                    continue
                print(f"        MISSING {p.name} — cannot continue.")
                return _fail(con)
            # Stream the file in row-group batches instead of materialising it
            # whole. weather_daily is 3.86 M rows, and read_parquet + to_sql on
            # it peaked at 2.3 GB RSS — more memory than any small host gives
            # you, so a deploy died in the build step and never reached the
            # server at all. Batched, the same load peaks under 300 MB.
            # Same rows, same order, same count; only the memory profile moves.
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(p)
            rows = 0
            for batch in pf.iter_batches(batch_size=50_000):
                chunk = batch.to_pandas()
                chunk.to_sql(name, con, if_exists="append", index=False)
                rows += len(chunk)
                del chunk
            print(f"        {name:<18} {rows:>10,} rows")
        con.commit()
    except Exception as e:                              # noqa: BLE001
        print(f"        LOAD FAILED: {type(e).__name__}: "
              f"{str(e).splitlines()[0][:90]}")
        return _fail(con)
    finally:
        con.close()

    # ---- 3-5. everything derived ----------------------------------------
    py = sys.executable
    step(3, "rebuilding reservoirs from ingest/reservoir_seeds.csv")
    if not run([py, "ingest/04_reservoirs.py", "--seed", "--interpolate"],
               "reservoir load"):
        return _fail()

    step(4, "scoring the urban track")
    if not run([py, "ingest/07_stress.py"], "urban stress scores"):
        return _fail()

    step(5, "checking the result")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ok = True
    for t, want in (("wells", 940), ("gw_observations", 68994),
                    ("reservoirs", 15), ("reservoir_daily", 121),
                    ("urban_stress", 121)):
        got = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        flag = "ok" if got == want else f"expected {want}"
        ok &= got == want
        print(f"        {t:<18} {got:>10,}  {flag}")
    w = con.execute("SELECT COUNT(*) FROM weather_daily").fetchone()[0]
    print(f"        {'weather_daily':<18} {w:>10,}  "
          f"{'ok' if w else 'absent — degraded'}")
    con.close()

    size = DB.stat().st_size / 1e6
    print(f"\n  {DB.relative_to(ROOT)} built — {size:.0f} MB\n")
    print("  Next:  uvicorn api.main:app --port 8000")
    print("         http://localhost:8000\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
