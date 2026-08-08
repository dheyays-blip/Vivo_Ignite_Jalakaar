#!/usr/bin/env python3
"""
JALAAKAR — ML Stage 6: prediction intervals from measured error.

    python ml/06_intervals.py        ->  reports/intervals.json

Why empirical and not parametric
--------------------------------
The obvious move is to assume Gaussian errors and quote +/- 1.28 sigma for an
80% band. Groundwater errors are not Gaussian: they are right-skewed, because a
well can fall much further than it can rise, and the tail is exactly where a
missed crisis lives. Fitting a normal distribution would understate the very
cases the product exists to catch.

So this measures the actual absolute-error distribution on held-out CGWB
readings and quotes its quantiles. "80% of forecasts landed within X metres"
is a claim you can point at a table for.

Both forecasters are measured, because the API falls back to climatology when
the model is unavailable and the interval must follow whichever produced the
number.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import connect, read  # noqa: E402

SEASON_CODES = {"pre_monsoon": 0, "monsoon": 1, "post_monsoon": 2, "rabi": 3}
DROP = ["well_id", "origin_date", "target_date", "split", "target_level"]


def quantiles(err: np.ndarray) -> dict:
    return {"p50": round(float(np.quantile(err, 0.50)), 3),
            "p80": round(float(np.quantile(err, 0.80)), 3),
            "p95": round(float(np.quantile(err, 0.95)), 3),
            "mae": round(float(err.mean()), 3),
            "n": int(err.size)}


def main() -> int:
    with connect() as con:
        df = read(con, "SELECT * FROM features_causal WHERE split='test'")
    if df.empty:
        sys.exit("No test rows — run ingest/06b_features_causal.py")

    df["season"] = df["season"].map(SEASON_CODES).astype("float32")
    for c in df.columns:
        if c not in ("well_id", "origin_date", "target_date", "split"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    base = df["clim_season"].fillna(df["clim_well"])
    out: dict = {"climatology": {}, "xgboost": {}}

    for h, g in df.groupby("horizon_d"):
        e = (base.loc[g.index] - g["target_level"]).abs().to_numpy()
        out["climatology"][str(int(h))] = quantiles(e)

    try:
        import xgboost as xgb
        model_path = ROOT / "models" / "xgb_causal.json"
        if not model_path.exists():
            raise FileNotFoundError(model_path)
        bst = xgb.Booster()
        bst.load_model(str(model_path))
        feats = list(bst.feature_names)
        d = xgb.DMatrix(df[feats], feature_names=feats, missing=np.nan)
        pred = bst.predict(d, iteration_range=(0, bst.best_iteration + 1)) \
            + base.to_numpy()
        df["_pred"] = pred
        for h, g in df.groupby("horizon_d"):
            e = (g["_pred"] - g["target_level"]).abs().to_numpy()
            out["xgboost"][str(int(h))] = quantiles(e)
    except Exception as e:                          # noqa: BLE001
        print(f"[intervals] model unavailable ({type(e).__name__}) — "
              f"climatology intervals only")
        out.pop("xgboost")

    print(f"\n{'=' * 66}")
    print("  PREDICTION INTERVALS — held-out CGWB readings")
    print(f"{'=' * 66}")
    for name, byh in out.items():
        print(f"\n  {name}")
        print(f"  {'horizon':<9} {'n':>6} {'MAE':>7} {'p50':>7} "
              f"{'p80':>7} {'p95':>7}")
        print(f"  {'-' * 48}")
        for h in sorted(byh, key=int):
            q = byh[h]
            print(f"  +{h:<8}d {q['n']:>6,} {q['mae']:>7.3f} {q['p50']:>7.3f} "
                  f"{q['p80']:>7.3f} {q['p95']:>7.3f}")

    best = out.get("xgboost") or out["climatology"]
    h30 = best.get("30")
    if h30:
        print(f"\n  Quotable: at 30 days, 80% of forecasts landed within "
              f"{h30['p80']:.2f} m")
        print(f"  of the real reading. The p95 of {h30['p95']:.2f} m is the "
              f"tail worth naming\n  out loud — it is where a missed crisis "
              f"would sit.\n")

    p = ROOT / "reports" / "intervals.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    print(f"[out ] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
