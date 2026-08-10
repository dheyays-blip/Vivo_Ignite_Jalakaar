#!/usr/bin/env python3
"""
JALAAKAR — ML Stage 4: choose the alert threshold deliberately.

The problem 03 exposed
----------------------
At the poster's default cutoff of 71, XGBoost catches 43.9% of real crises and
climatology catches 52.0%. The better model warns fewer people. That is not a
modelling failure, it is an untuned decision threshold: XGBoost's predictions
sit closer to the seasonal mean, so fewer of them cross a fixed line.

The band boundaries 0-40 / 41-70 / 71-100 are a design choice from the poster.
They were never fitted to anything. This script fits the ACT NOW boundary to a
stated policy instead — "catch N% of real crises" — and reports honestly what
that costs in false alarms.

Why recall is weighted above precision here
-------------------------------------------
A MISS means a farmer plants a crop against a well that fails. A FALSE ALARM
means somebody conserved water they did not need to conserve, and trusts the
next alert slightly less. These are not symmetric, and averaging them into one
"accuracy" number hides the only trade-off that matters.

The threshold is chosen on VAL and then applied unchanged to TEST. Choosing it
on test would be fitting to the number you then report.

What the product actually ships, and why that is not what this fits
-------------------------------------------------------------------
This script fits 53. `api/model.py` ships **70**. The gap is deliberate and is
argued in that module and in the README: the control room can now warn the
whole state in one click, and at 53 three of every four alerts are false,
which is how an alerting channel gets muted. Recall you cannot deliver is not
recall.

So the test block below reports THREE cutoffs — the poster's, the fitted one,
and whatever `api/model.py` currently ships — and the last one is read from
that module rather than written down here. A threshold that lives in two files
is a threshold that will disagree with itself, and this script exists to stop
exactly that.

Note the comparison is `pred_score > cutoff`, matching `api/scoring.py`. So
cutoff 70 fires at 71 and above. Off by one here silently moves every number
in the README.

Usage
-----
    python ml/04_operating_point.py                    # target 80% recall
    python ml/04_operating_point.py --target-recall 0.9
    python ml/04_operating_point.py --sweep            # full curve, pick yourself
    python ml/04_operating_point.py --cutoff 70        # measure one specific value
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

SEASON_CODES = {"pre_monsoon": 0, "monsoon": 1, "post_monsoon": 2, "rabi": 3}
CRISIS_PERCENTILE = 0.90
DEFAULT_CUTOFF = 71


def prep(con, splits: tuple[str, ...]) -> pd.DataFrame:
    ph = ",".join("?" * len(splits))
    df = read(con, f"SELECT * FROM features_causal WHERE split IN ({ph})",
              tuple(splits))
    if df.empty:
        sys.exit("ERROR: features_causal has no rows for " + ",".join(splits))
    df["season"] = df["season"].map(SEASON_CODES).astype("float32")
    for c in df.columns:
        if c not in ("well_id", "origin_date", "target_date", "split"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    obs = read(con, "SELECT well_id, level_mbgl FROM gw_observations "
                    "WHERE obs_date <= ?", (str(cfg.splits["train_end"]),))
    g = obs.groupby("well_id")["level_mbgl"]
    ref = pd.DataFrame({"shallow": g.min(),
                        "crisis": g.quantile(CRISIS_PERCENTILE),
                        "n_train_obs": g.size()}).reset_index()
    return df.merge(ref[ref.n_train_obs >= 4], on="well_id", how="inner")


def score_from_level(level, row):
    span = np.maximum(row["crisis"] - row["shallow"], 0.5)
    s_depth = np.clip((level - row["shallow"]) / span * 60, 0, 60)
    trend = row["obs_trend_m_per_day"].fillna(0.0)
    s_trend = np.clip(np.where(trend > 0, trend / 0.05 * 25, 0.0), 0, 25)
    depth = row["well_depth"]
    s_head = np.where(depth.notna() & (depth > 0),
                      np.clip((level / depth.replace(0, np.nan) - 0.6) / 0.4 * 15,
                              0, 15), 0.0)
    return s_depth + s_trend + np.nan_to_num(s_head)


def rates(true_score, pred_score, cutoff) -> dict:
    act_true = true_score > DEFAULT_CUTOFF        # reality: poster's definition
    act_pred = pred_score > cutoff                # what we choose to alert on
    tp = int((act_true & act_pred).sum())
    fp = int((~act_true & act_pred).sum())
    fn = int((act_true & ~act_pred).sum())
    return {"cutoff": float(cutoff), "alerts": tp + fp, "caught": tp,
            "misses": fn, "false_alarms": fp,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "crises": tp + fn}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/xgb_causal.json")
    ap.add_argument("--target-recall", type=float, default=0.80)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--cutoff", type=float, default=None,
                    help="also report test metrics at this exact cutoff; "
                         "defaults to whatever api/model.py ships")
    ap.add_argument("--out", default="reports/operating_point.json")
    args = ap.parse_args()

    # Imported, never copied. If someone changes the shipped cutoff, the next
    # run of this script measures the new one without anybody remembering to
    # come here and edit a number.
    from api.model import ACT_NOW_CUTOFF as SHIPPED
    shipped = float(args.cutoff if args.cutoff is not None else SHIPPED)

    import xgboost as xgb

    with connect() as con:
        df = prep(con, ("val", "test"))

    bst = xgb.Booster()
    bst.load_model(str(ROOT / args.model))
    feats = list(bst.feature_names)

    d = xgb.DMatrix(df[feats], feature_names=feats, missing=np.nan)
    base = df["clim_season"].fillna(df["clim_well"])
    df["pred_level"] = bst.predict(d, iteration_range=(0, bst.best_iteration + 1)) \
        + base.values
    df["true_score"] = score_from_level(df["target_level"], df)
    df["pred_score"] = score_from_level(df["pred_level"], df)

    va, te = df[df.split == "val"], df[df.split == "test"]
    print(f"[data] val {len(va):,}  test {len(te):,}")

    grid = np.arange(30, 91, 1)
    curve = [rates(va["true_score"].values, va["pred_score"].values, c)
             for c in grid]

    if args.sweep:
        print(f"\n  VAL sweep — pick your own operating point")
        print(f"  {'cutoff':>7} {'alerts':>7} {'caught':>7} {'recall':>8} "
              f"{'precision':>10} {'misses':>7}")
        print(f"  {'-' * 52}")
        for r in curve:
            if r["recall"] is None:
                continue
            print(f"  {r['cutoff']:>7.0f} {r['alerts']:>7,} {r['caught']:>7,} "
                  f"{r['recall']:>8.1%} "
                  f"{(r['precision'] or 0):>10.1%} {r['misses']:>7,}")

    ok = [r for r in curve if r["recall"] and r["recall"] >= args.target_recall]
    if not ok:
        best = max((r for r in curve if r["recall"]), key=lambda r: r["recall"])
        print(f"\n  Target recall {args.target_recall:.0%} unreachable at any "
              f"cutoff. Best on val is {best['recall']:.1%} at {best['cutoff']:.0f}.")
        chosen = best["cutoff"]
    else:
        chosen = max(r["cutoff"] for r in ok)   # highest cutoff that still hits it

    print(f"\n{'=' * 74}")
    print(f"  CHOSEN ACT NOW CUTOFF: {chosen:.0f}   "
          f"(fitted on VAL for >= {args.target_recall:.0%} recall)")
    print(f"{'=' * 74}")

    out = {"target_recall": args.target_recall, "chosen_cutoff": float(chosen),
           "default_cutoff": DEFAULT_CUTOFF, "shipped_cutoff": shipped,
           "val_curve": curve, "test": {}}

    for label, cut in (("poster default", DEFAULT_CUTOFF), ("tuned", chosen),
                       ("shipped", shipped)):
        r = rates(te["true_score"].values, te["pred_score"].values, cut)
        out["test"][label] = r
        print(f"\n  TEST @ cutoff {cut:.0f}  ({label})")
        print(f"    real crises           {r['crises']:>6,}")
        print(f"    alerts fired          {r['alerts']:>6,}")
        print(f"    caught                {r['caught']:>6,}   "
              f"recall {r['recall']:.1%}")
        print(f"    MISSES                {r['misses']:>6,}")
        print(f"    FALSE ALARMS          {r['false_alarms']:>6,}   "
              f"precision {(r['precision'] or 0):.1%}")

    a, b = out["test"]["poster default"], out["test"]["tuned"]
    # Signed as CHANGE IN THE METRIC, so negative always means "less of it".
    # Printing a reduction of 171 misses as "+171 misses" reads as the exact
    # opposite of what happened.
    print(f"\n  Moving the cutoff {DEFAULT_CUTOFF} -> {chosen:.0f} on test:")
    print(f"    {b['misses'] - a['misses']:+,} misses       "
          f"({a['misses']:,} -> {b['misses']:,})")
    print(f"    {b['false_alarms'] - a['false_alarms']:+,} false alarms "
          f"({a['false_alarms']:,} -> {b['false_alarms']:,})")
    if b["alerts"]:
        print(f"    alert rate {b['alerts'] / len(te):.1%} of scored "
              f"well-days ({b['alerts']:,} of {len(te):,})")
    print("\n  That is the trade. State it on the poster as a choice you made,\n"
          "  not a number you found — 'we accept N false alarms to catch M%\n"
          "  of real crises' is a defensible engineering position. A single\n"
          "  accuracy percentage is not.\n")

    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"[out ] {p}")


if __name__ == "__main__":
    main()
