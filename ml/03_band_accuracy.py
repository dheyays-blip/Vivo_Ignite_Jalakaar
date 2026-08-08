#!/usr/bin/env python3
"""
JALAAKAR — ML Stage 3: does the system make the right CALL?

Why MAE is not the number to put on the poster
----------------------------------------------
1.39 m is honest but it is not a decision. Nobody acts on metres; they act on
a band — Safe, Monitor, Act Now. So the question that matters is: when the
system says ACT NOW, is it right, and when it stays quiet, was it safe to?

This script converts the forecast into the band the product would actually
have shown, and scores that against the band the real reading implies. It
replaces the poster's borrowed "~90% @ 7d / ~85% @ 15d / ~80% @ 30d" ladder
with something measured on 2,584 held-out CGWB readings.

Two error types, and they are not equal
---------------------------------------
    MISS         truly ACT NOW, system said something calmer.
                 A farmer gets no warning. This is the expensive one.

    FALSE ALARM  system said ACT NOW, reality was calmer.
                 Cries wolf. Kills adoption faster than silence does, which
                 is the specific criticism a judge will reach for.

Both are reported. Neither is buried in an accuracy average.

How the band is derived
-----------------------
Same formula as api/scoring.py, so this measures the shipped product and not a
convenient stand-in:

    score = s_depth(level) + s_trend + s_headroom

`s_trend` and `s_headroom` come from real observations and are identical for
the true and predicted rows, so the ONLY thing that differs is the forecast
level. That isolates the model's contribution exactly.

Per-well shallow/crisis reference levels are fitted on TRAIN observations only.
Using the full record would leak the test period into the thresholds.

Usage
-----
    python ml/03_band_accuracy.py
    python ml/03_band_accuracy.py --model models/xgb_causal.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import cfg, connect, read  # noqa: E402

BANDS = ["SAFE", "MONITOR", "ACT NOW"]
CRISIS_PERCENTILE = 0.90
SEASON_CODES = {"pre_monsoon": 0, "monsoon": 1, "post_monsoon": 2, "rabi": 3}
DROP = ["well_id", "origin_date", "target_date", "split", "target_level"]


def band_of(score: float) -> str:
    if score <= 40:
        return "SAFE"
    if score <= 70:
        return "MONITOR"
    return "ACT NOW"


# --------------------------------------------------------------------------
def well_reference(con) -> pd.DataFrame:
    """Shallow and crisis levels per well, from TRAIN observations only."""
    obs = read(con, "SELECT well_id, obs_date, level_mbgl FROM gw_observations "
                    "WHERE obs_date <= ?", (str(cfg.splits["train_end"]),))
    if obs.empty:
        sys.exit("ERROR: no train observations.")
    g = obs.groupby("well_id")["level_mbgl"]
    ref = pd.DataFrame({
        "shallow": g.min(),
        "crisis": g.quantile(CRISIS_PERCENTILE),
        "n_train_obs": g.size(),
    }).reset_index()
    ref = ref[ref["n_train_obs"] >= 4]
    print(f"[ref ] shallow/crisis fitted on {len(obs):,} train readings, "
          f"{len(ref):,} wells (≤ {cfg.splits['train_end']})")
    return ref


def score_from_level(level, row) -> float:
    span = np.maximum(row["crisis"] - row["shallow"], 0.5)
    s_depth = np.clip((level - row["shallow"]) / span * 60, 0, 60)

    trend = row["obs_trend_m_per_day"].fillna(0.0)
    s_trend = np.clip(np.where(trend > 0, trend / 0.05 * 25, 0.0), 0, 25)

    depth = row["well_depth"]
    s_head = np.where(
        depth.notna() & (depth > 0),
        np.clip((level / depth.replace(0, np.nan) - 0.6) / 0.4 * 15, 0, 15),
        0.0)
    return s_depth + s_trend + np.nan_to_num(s_head)


# --------------------------------------------------------------------------
def confusion(true_b, pred_b) -> pd.DataFrame:
    m = pd.crosstab(pd.Series(true_b, name="actual"),
                    pd.Series(pred_b, name="predicted"))
    return m.reindex(index=BANDS, columns=BANDS, fill_value=0)


def report_block(name, true_b, pred_b) -> dict:
    cm = confusion(true_b, pred_b)
    n = int(cm.values.sum())
    exact = int(np.trace(cm.values))
    idx = {b: i for i, b in enumerate(BANDS)}
    dist = np.array([abs(idx[a] - idx[p]) for a, p in zip(true_b, pred_b)])

    act_true = np.array(true_b) == "ACT NOW"
    act_pred = np.array(pred_b) == "ACT NOW"
    tp = int((act_true & act_pred).sum())
    fp = int((~act_true & act_pred).sum())
    fn = int((act_true & ~act_pred).sum())

    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None

    print(f"\n  {name}")
    print(f"  {'-' * 58}")
    print(cm.to_string())
    print(f"\n    exact band            {exact / n:6.1%}  ({exact:,}/{n:,})")
    print(f"    within one band       {(dist <= 1).mean():6.1%}")
    if recall is not None:
        print(f"    ACT NOW caught        {recall:6.1%}  "
              f"({tp} of {tp + fn} real crises flagged)")
    if precision is not None:
        print(f"    ACT NOW precision     {precision:6.1%}  "
              f"({fp} false alarms in {tp + fp} alerts)")
    print(f"    MISSES (dangerous)    {fn:>6,}")
    print(f"    FALSE ALARMS          {fp:>6,}")

    return {"n": n, "exact_band": round(exact / n, 4),
            "within_one_band": round(float((dist <= 1).mean()), 4),
            "act_now_recall": round(recall, 4) if recall is not None else None,
            "act_now_precision": round(precision, 4) if precision is not None else None,
            "misses": fn, "false_alarms": fp,
            "confusion": cm.to_dict()}


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/xgb_causal.json")
    ap.add_argument("--target", default="delta_clim",
                    choices=["delta_clim", "delta_obs", "level"])
    ap.add_argument("--out", default="reports/band_accuracy.json")
    args = ap.parse_args()

    import xgboost as xgb

    with connect() as con:
        df = read(con, "SELECT * FROM features_causal WHERE split='test'")
        ref = well_reference(con)

    if df.empty:
        sys.exit("ERROR: no test rows in features_causal.")

    df["season"] = df["season"].map(SEASON_CODES).astype("float32")
    for c in df.columns:
        if c not in ("well_id", "origin_date", "target_date", "split"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    before = len(df)
    df = df.merge(ref, on="well_id", how="inner")
    print(f"[data] {len(df):,} test rows ({before - len(df):,} dropped: well has "
          f"no usable train history)")

    bst = xgb.Booster()
    bst.load_model(str(ROOT / args.model))
    feats = list(bst.feature_names)
    missing = [f for f in feats if f not in df.columns]
    if missing:
        sys.exit(f"ERROR: model expects features not in the table: {missing}")

    d = xgb.DMatrix(df[feats], feature_names=feats, missing=np.nan)
    raw = bst.predict(d, iteration_range=(0, bst.best_iteration + 1))
    base = df["clim_season"].fillna(df["clim_well"])
    offset = {"delta_clim": base,
              "delta_obs": df["last_obs_level"],
              "level": pd.Series(0.0, index=df.index)}[args.target]
    df["pred_level"] = raw + offset.values

    true_b = [band_of(s) for s in score_from_level(df["target_level"], df)]
    pred_b = [band_of(s) for s in score_from_level(df["pred_level"], df)]
    clim_b = [band_of(s) for s in score_from_level(base, df)]
    last_b = [band_of(s) for s in score_from_level(df["last_obs_level"], df)]

    print(f"\n{'=' * 78}")
    print("  BAND ACCURACY — test split, real CGWB readings only")
    print("  'Does the system make the right call?', not 'how many metres out?'")
    print(f"{'=' * 78}")

    out = {"overall": {}, "by_horizon": {}, "actual_distribution":
           {b: int((np.array(true_b) == b).sum()) for b in BANDS}}

    out["overall"]["xgboost"] = report_block("XGBOOST", true_b, pred_b)
    out["overall"]["climatology"] = report_block("CLIMATOLOGY (baseline)",
                                                 true_b, clim_b)
    out["overall"]["last_reading"] = report_block("LAST REAL READING (no model)",
                                                  true_b, last_b)

    print(f"\n{'=' * 78}")
    print("  BY HORIZON — xgboost")
    print(f"  {'horizon':<9} {'n':>6} {'exact':>8} {'±1 band':>9} "
          f"{'caught':>8} {'misses':>7} {'false':>7}")
    print(f"  {'-' * 58}")
    tb, pb = np.array(true_b), np.array(pred_b)
    for h in sorted(df.horizon_d.unique()):
        m = (df.horizon_d == h).values
        r = report_quiet(tb[m], pb[m])
        out["by_horizon"][int(h)] = r
        caught = f"{r['act_now_recall']:.0%}" if r["act_now_recall"] is not None else "—"
        print(f"  +{int(h):<8}d {r['n']:>6,} {r['exact_band']:>8.1%} "
              f"{r['within_one_band']:>9.1%} {caught:>8} "
              f"{r['misses']:>7,} {r['false_alarms']:>7,}")
    print(f"{'=' * 78}\n")

    print("  Actual band distribution in the test set:")
    for b in BANDS:
        c = out["actual_distribution"][b]
        print(f"    {b:<9} {c:>6,}  {c / len(df):6.1%}")
    print("\n  Read the exact-band figure against this. If one band dominates,\n"
          "  a constant prediction would score well too — quote ACT NOW recall\n"
          "  and precision alongside it, never the headline alone.\n")

    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"[out ] {p}")


def report_quiet(true_b, pred_b) -> dict:
    cm = confusion(true_b, pred_b)
    n = int(cm.values.sum())
    idx = {b: i for i, b in enumerate(BANDS)}
    dist = np.array([abs(idx[a] - idx[p]) for a, p in zip(true_b, pred_b)])
    act_true, act_pred = np.array(true_b) == "ACT NOW", np.array(pred_b) == "ACT NOW"
    tp = int((act_true & act_pred).sum())
    fp = int((~act_true & act_pred).sum())
    fn = int((act_true & ~act_pred).sum())
    return {"n": n, "exact_band": float(np.trace(cm.values) / n),
            "within_one_band": float((dist <= 1).mean()),
            "act_now_recall": tp / (tp + fn) if tp + fn else None,
            "act_now_precision": tp / (tp + fp) if tp + fp else None,
            "misses": fn, "false_alarms": fp}


if __name__ == "__main__":
    main()
