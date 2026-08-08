#!/usr/bin/env python3
"""
JALAAKAR — prove the LIVE score path reproduces the published accuracy.

    python api/verify_model.py [--n 800]

`verify_features.py` proves the serving features match the training features.
This goes one step further and checks the whole serving path end to end:

    api.features_live.build  ->  booster.predict  ->  + clim_season  ->  level

It replays test-split rows through exactly the code the API runs, computes MAE
per horizon, and compares against reports/xgboost_metrics.json — the numbers
quoted on the landing page. If they diverge, the site is advertising an
accuracy the live system does not deliver.

The most likely way to break this is forgetting that the model predicts a
RESIDUAL against climatology, not a level. That mistake leaves errors around
4-5 m while everything still runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import model as model_mod          # noqa: E402
from api.appdb import pipeline_db           # noqa: E402

TOL_M = 0.02          # metres of slack against the published figure


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0,
                    help="rows to check; 0 = all 7,752 test rows (default)")
    ap.add_argument("--metrics", default="reports/xgboost_metrics.json")
    args = ap.parse_args()

    # Pair the model with the metrics that describe it. Two training runs used
    # to overwrite the same model file while writing metrics to different
    # files, so the "wrong" model could sit next to the "right" numbers and
    # this script would report a divergence that was pure bookkeeping.
    p = ROOT / args.metrics
    published, meta = {}, {}
    if p.exists():
        try:
            meta = json.loads(p.read_text())
            for h, m in meta["results"]["test"]["by_horizon"].items():
                published[int(h)] = m["mae"]
        except (KeyError, ValueError):
            pass
    if meta.get("model_path"):
        import os
        os.environ["JALAAKAR_MODEL"] = str(ROOT / meta["model_path"])
        model_mod.MODEL_PATH = ROOT / meta["model_path"]
        model_mod._booster.cache_clear()
        print(f"[verify] pairing {args.metrics} with {meta['model_path']}")
    else:
        print(f"[verify] {args.metrics} predates model-path tracking — "
              f"assuming {model_mod.MODEL_PATH.name} is the matching model.\n"
              f"         Re-run ml/02_xgboost.py to make the pairing explicit.")

    if not model_mod.available():
        sys.exit("Model unavailable — install xgboost and ensure "
                 f"{model_mod.MODEL_PATH} exists.")

    with pipeline_db() as con:
        rows = con.execute(
            "SELECT well_id, origin_date, horizon_d, target_level "
            "FROM features_causal WHERE split='test' "
            "ORDER BY well_id, origin_date").fetchall()
    if not rows:
        sys.exit("No test rows in features_causal.")

    # Subsampling must SPREAD ACROSS WELLS. Taking the first N rows of a
    # well-ordered table gave 85 of 821 wells — alphabetically first — and the
    # resulting MAE was 0.07 m off the published figure for no reason other
    # than that. Stride sampling keeps the well mix representative.
    total = len(rows)
    if args.n and args.n < total:
        stride = total / args.n
        rows = [rows[int(i * stride)] for i in range(args.n)]
        print(f"[verify] stride sample: {len(rows):,} of {total:,} test rows, "
              f"{len({r['well_id'] for r in rows}):,} wells")
    else:
        print(f"[verify] all {total:,} test rows, "
              f"{len({r['well_id'] for r in rows}):,} wells")

    err: dict[int, list[float]] = {}
    skipped = 0
    for r in rows:
        fc = model_mod.forecast(r["well_id"], r["origin_date"],
                                int(r["horizon_d"]))
        if fc is None:
            skipped += 1
            continue
        err.setdefault(int(r["horizon_d"]), []).append(
            abs(fc["level"] - r["target_level"]))

    print(f"\n[verify] {sum(len(v) for v in err.values()):,} predictions "
          f"through the live serving path ({skipped} skipped)\n")
    print(f"  {'horizon':<9} {'n':>6} {'served MAE':>11} {'published':>10} "
          f"{'delta':>8}")
    print(f"  {'-' * 48}")

    ok = True
    for h in sorted(err):
        e = err[h]
        mae = sum(e) / len(e)
        pub = published.get(h)
        if pub is None:
            print(f"  +{h:<8}d {len(e):>6,} {mae:>11.3f} {'—':>10} {'—':>8}")
            continue
        delta = mae - pub
        flag = "" if abs(delta) <= TOL_M else "   <-- DIVERGED"
        ok = ok and abs(delta) <= TOL_M
        print(f"  +{h:<8}d {len(e):>6,} {mae:>11.3f} {pub:>10.3f} "
              f"{delta:>+8.3f}{flag}")

    if published and ok:
        print("\n  Serving path matches the published accuracy. The number on\n"
              "  the landing page is the number the demo actually delivers.\n")
        return 0
    if published:
        print("\n  The live path does NOT reproduce the published MAE.\n"
              "  Most likely cause: the model predicts a residual against\n"
              "  clim_season and something is adding the wrong base back.\n")
        return 1
    print("\n  No published metrics found — run ml/02_xgboost.py first.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
