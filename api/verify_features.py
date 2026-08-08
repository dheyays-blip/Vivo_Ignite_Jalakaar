#!/usr/bin/env python3
"""
JALAAKAR — prove the serving features match the training features.

    python api/verify_features.py [--n 400]

`api/features_live.py` rebuilds a row from scratch for an arbitrary
(well, origin, horizon). `features_causal` holds the rows the model was
actually trained and evaluated on. If those two ever disagree, the live score
silently stops matching the 1.39 m MAE the landing page advertises, and
nothing raises an error — the model just receives inputs it has never seen.

So: sample real rows from `features_causal`, rebuild each one through the
serving path, and compare every feature. Any mismatch is a bug in one of the
two files and must be fixed before trusting a live number.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.appdb import pipeline_db          # noqa: E402
from api.features_live import (FEATURE_ORDER, SEASON_CODES,  # noqa: E402
                               build)

TOL = 1e-6


def norm(field: str, v):
    """features_causal stores `season` as text; the model wants the code.
    ml/02_xgboost.py does this mapping at load time, so the verifier has to
    do it too or every row 'fails' on a difference that is not real."""
    if field == "season" and isinstance(v, str):
        return SEASON_CODES.get(v)
    return v


def close(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        if math.isnan(float(a)) and math.isnan(float(b)):
            return True
    except (TypeError, ValueError):
        return a == b
    return abs(float(a) - float(b)) <= TOL * max(1.0, abs(float(a)), abs(float(b)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--split", default=None, choices=["train", "val", "test"])
    args = ap.parse_args()

    where = f"WHERE split='{args.split}'" if args.split else ""
    with pipeline_db() as con:
        rows = con.execute(
            f"SELECT * FROM features_causal {where} "
            f"ORDER BY well_id, origin_date LIMIT ?", (args.n,)).fetchall()
    if not rows:
        sys.exit("features_causal is empty — run ingest/06b_features_causal.py")

    print(f"[verify] {len(rows)} rows"
          f"{' from ' + args.split if args.split else ''}")

    bad = defaultdict(list)
    skipped = 0
    for r in rows:
        r = dict(r)
        live = build(r["well_id"], r["origin_date"], int(r["horizon_d"]))
        if live is None:
            skipped += 1
            continue
        for f in FEATURE_ORDER:
            want, got = norm(f, r.get(f)), norm(f, live.get(f))
            if not close(got, want):
                bad[f].append((r["well_id"], r["origin_date"], want, got))

    checked = len(rows) - skipped
    if not bad:
        print(f"[verify] {checked} rows x {len(FEATURE_ORDER)} features — "
              f"ALL MATCH")
        print("         serving path reproduces the training features exactly.")
        return 0

    print(f"[verify] MISMATCHES in {len(bad)} of {len(FEATURE_ORDER)} features\n")
    for f, items in sorted(bad.items(), key=lambda kv: -len(kv[1])):
        print(f"  {f}: {len(items)}/{checked} rows differ")
        for wid, od, train_v, live_v in items[:3]:
            print(f"      {wid} {od}   trained={train_v!r}  served={live_v!r}")
    print("\n  Fix api/features_live.py or ingest/06b_features_causal.py so the\n"
          "  two agree. Do not ship a live score until this passes.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
