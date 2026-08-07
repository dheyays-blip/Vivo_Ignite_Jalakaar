#!/usr/bin/env python3
"""
JALAAKAR — Stage 7: freeze and hand off.
Owner: Dev B. Run at Sat 20:00. After this, no new data sources.

    python tools/freeze.py --mae 0.42

Does four things, in order, and refuses to continue if any fails:
  1. runs the full validation suite (tools/validate.py)
  2. copies the DB to data/FROZEN_<timestamp>.db and marks it read-only
  3. regenerates DATA_CARD.md against the frozen copy
  4. prints the exact message to post to the team

--force skips only step 1's exit code, and says so loudly in the data card.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import cfg  # noqa: E402


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mae", default=None, help="Dev A's held-out interpolation MAE")
    ap.add_argument("--force", action="store_true",
                    help="freeze even if validation fails (ship-what-exists mode)")
    args = ap.parse_args()

    if not cfg.db_path.exists():
        sys.exit(f"no database at {cfg.db_path}")

    print("=" * 70)
    print("STEP 1 — validation")
    print("=" * 70)
    rc = run([sys.executable, "tools/validate.py"])
    if rc != 0:
        if not args.force:
            print("\nVALIDATION FAILED. Fix the checks above, or re-run with "
                  "--force to ship what exists.")
            return 1
        print("\n--force: freezing despite failed checks.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    frozen = cfg.db_path.parent / f"FROZEN_{stamp}.db"

    print("\n" + "=" * 70)
    print("STEP 2 — freeze")
    print("=" * 70)
    # checkpoint the WAL so the copy is self-contained
    import sqlite3
    con = sqlite3.connect(cfg.db_path)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    shutil.copy2(cfg.db_path, frozen)
    os.chmod(frozen, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    size = frozen.stat().st_size / 1e6
    print(f"  {frozen}  ({size:.1f} MB, read-only)")

    print("\n" + "=" * 70)
    print("STEP 3 — data card")
    print("=" * 70)
    cmd = [sys.executable, "tools/data_card.py"]
    if args.mae:
        cmd += ["--mae", args.mae]
    else:
        print("  WARNING: no --mae. The card will say the interpolation MAE is "
              "missing, and it will be the first thing a judge asks about.")
    env = dict(os.environ, JALAAKAR_DB=str(frozen))
    subprocess.call(cmd, cwd=ROOT, env=env)

    print("\n" + "=" * 70)
    print("STEP 4 — post this to the team")
    print("=" * 70)
    print(f"""
    Ingestion frozen: {frozen.name}
    ML and alerting read from `features`. The schema will not change.
    Data card: DATA_CARD.md (generated, not hand-written).
    Interpolation MAE: {args.mae or 'NOT RECORDED — Dev A owes this'}
    No new data sources from here. Sunday and Monday are model, WhatsApp,
    demo, rehearsal.
    """)
    print("Tag it:  git tag v1-data-frozen && git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
