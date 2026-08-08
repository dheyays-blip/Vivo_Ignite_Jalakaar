#!/usr/bin/env python3
"""
JALAAKAR — ML Stage 2: XGBoost on causal features.

Reads `features_causal` only. It does NOT touch `features` / features.parquet,
because those columns are built from gw_daily and leak the target — see
ml/01_baseline.py, which measures the leak, and the header of
ingest/06b_features_causal.py, which explains it.

The bar to beat (test, real observations only, from 01_baseline.py):

    +7d   1.845 m   climatology
    +15d  1.845 m   climatology
    +30d  1.845 m   climatology

Climatology is flat across horizons because it only knows the calendar. A real
model should beat it comfortably at +7d and by less at +30d; if the curve is
flat, the model has learned the seasonal cycle and nothing else, which is worth
knowing and worth saying.

What it predicts
----------------
By default the model predicts the **residual against that well's seasonal
climatology**, not the level itself, and the climatology is added back at the
end. Gradient-boosted trees cannot extrapolate a level, but they are good at
"how far from normal is this well going to be, given how dry it has been."
`--target level` and `--target delta_obs` are there so you can check that claim
rather than take it on faith.

Usage
-----
    python ml/02_xgboost.py
    python ml/02_xgboost.py --per-horizon --target level
    python ml/02_xgboost.py --dry-run          # data prep only, no training
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
from ingest.db import connect, read  # noqa: E402

DROP = ["well_id", "origin_date", "target_date", "split", "target_level"]
SEASON_CODES = {"pre_monsoon": 0, "monsoon": 1, "post_monsoon": 2, "rabi": 3}

# Native xgboost API, not the sklearn wrapper — XGBRegressor imports sklearn
# even when you never use it, and there is nothing here that needs it.
PARAMS = {
    "objective": "reg:absoluteerror",  # optimise MAE, because MAE is what we report
    "eta": 0.03,
    "max_depth": 6,
    "min_child_weight": 8,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "lambda": 2.0,
    "tree_method": "hist",
    "seed": 42,
}
NUM_ROUNDS = 2000
EARLY_STOP = 100


# --------------------------------------------------------------------------
def metrics(y_true, y_pred) -> dict:
    e = np.asarray(y_pred, float) - np.asarray(y_true, float)
    m = ~np.isnan(e)
    if not m.any():
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    e = e[m]
    return {"n": int(m.sum()),
            "mae": round(float(np.abs(e).mean()), 3),
            "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
            "bias": round(float(e.mean()), 3)}


def load(con, sample: int | None) -> pd.DataFrame:
    df = read(con, "SELECT * FROM features_causal")
    if df.empty:
        sys.exit("ERROR: features_causal is empty. "
                 "Run: python ingest/06b_features_causal.py")
    if sample:
        df = df.sample(min(sample, len(df)), random_state=42)
    df["season"] = df["season"].map(SEASON_CODES).astype("float32")

    # SQLite returns an all-NULL column as dtype object, which DMatrix rejects
    # with a confusing error about categoricals. Coerce everything that is not
    # an identifier to numeric so the failure mode is a visible NaN, not a
    # dtype exception three functions later.
    for c in df.columns:
        if c not in ("well_id", "origin_date", "target_date", "split"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    print(f"[load] {len(df):,} rows, {df.well_id.nunique():,} wells")
    print(df.groupby(["split", "horizon_d"]).size().to_string())
    return df


def make_target(df: pd.DataFrame, kind: str) -> tuple[pd.Series, pd.Series]:
    """Returns (y_to_fit, offset_to_add_back)."""
    if kind == "level":
        return df["target_level"], pd.Series(0.0, index=df.index)
    if kind == "delta_obs":
        return df["target_level"] - df["last_obs_level"], df["last_obs_level"]
    if kind == "delta_clim":
        base = df["clim_season"].fillna(df["clim_well"])
        return df["target_level"] - base, base
    sys.exit(f"unknown --target {kind}")


# --------------------------------------------------------------------------
def train_one(tr, va, te, feats, target_kind, tag):
    import xgboost as xgb

    ytr, _ = make_target(tr, target_kind)
    yva, ova = make_target(va, target_kind)
    _, ote = make_target(te, target_kind)

    dtr = xgb.DMatrix(tr[feats], label=ytr, feature_names=feats, missing=np.nan)
    dva = xgb.DMatrix(va[feats], label=yva, feature_names=feats, missing=np.nan)

    bst = xgb.train(PARAMS, dtr, num_boost_round=NUM_ROUNDS,
                    evals=[(dtr, "train"), (dva, "val")],
                    early_stopping_rounds=EARLY_STOP, verbose_eval=False)
    print(f"[fit ] {tag}: best iteration {bst.best_iteration} of {NUM_ROUNDS}")

    def predict(part: pd.DataFrame) -> np.ndarray:
        d = xgb.DMatrix(part[feats], feature_names=feats, missing=np.nan)
        raw = bst.predict(d, iteration_range=(0, bst.best_iteration + 1))
        return raw + make_target(part, target_kind)[1].values

    out = {}
    for name, part in (("val", va), ("test", te)):
        out[name] = metrics(part["target_level"].values, predict(part))
        out[name]["by_horizon"] = {
            int(h): metrics(g["target_level"].values, predict(g))
            for h, g in part.groupby("horizon_d")
        }
    return bst, out


# --------------------------------------------------------------------------
def compare(results: dict, baseline_path: Path) -> None:
    base = {}
    if baseline_path.exists():
        b = json.loads(baseline_path.read_text())
        for hk, byspl in b.get("observed_targets_only", {}).items():
            t = byspl.get("test", {})
            cand = {k: v["mae"] for k, v in t.items()
                    if v.get("mae") is not None and k != "persistence_daily"}
            if cand:
                base[int(hk[1:])] = min(cand.items(), key=lambda kv: kv[1])

    print(f"\n{'=' * 78}")
    print("  XGBOOST vs BASELINE — test split, real observations only")
    print(f"{'=' * 78}")
    print(f"  {'horizon':<9} {'n':>6} {'XGB MAE':>9} {'baseline':>9} "
          f"{'method':<16} {'skill':>7}")
    print(f"  {'-' * 62}")
    for h, m in sorted(results["test"]["by_horizon"].items()):
        if h in base:
            bname, bmae = base[h]
            skill = 1 - m["mae"] / bmae
            verdict = f"{skill:+6.1%}"
        else:
            bname, bmae, verdict = "—", float("nan"), "     —"
        print(f"  +{h:<8}d {m['n']:>6,} {m['mae']:>9.3f} {bmae:>9.3f} "
              f"{bname:<16} {verdict:>7}")
    print(f"\n  skill = 1 - MAE_model / MAE_baseline. Positive means better.")
    print(f"{'=' * 78}\n")

    flat = [m["mae"] for _, m in sorted(results["test"]["by_horizon"].items())]
    if len(flat) > 1 and (max(flat) - min(flat)) < 0.05:
        print("  NOTE: error is flat across horizons. The model is leaning on the\n"
              "  seasonal cycle and little else. Say so rather than let it pass.\n")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="delta_clim",
                    choices=["delta_clim", "delta_obs", "level"])
    ap.add_argument("--per-horizon", action="store_true",
                    help="one model per horizon instead of horizon-as-feature")
    ap.add_argument("--weather-only", action="store_true",
                    help="keep only rows that have weather at origin. Train is "
                         "62.5%% weatherless (obs start 2000, weather 2012) while "
                         "val/test are 100%% covered — a train/serve mismatch. "
                         "This trades training rows for a matched distribution.")
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate data prep and exit without training")
    ap.add_argument("--out", default="reports/xgboost_metrics.json")
    ap.add_argument("--model-dir", default="models")
    args = ap.parse_args()

    with connect() as con:
        df = load(con, args.sample)

    if args.weather_only:
        before = len(df)
        df = df[df["rain_30d"].notna()]
        print(f"[filt] --weather-only: {len(df):,} rows kept, "
              f"{before - len(df):,} dropped")
        print(df.groupby("split").size().to_string())

    feats = [c for c in df.columns if c not in DROP]

    # Soil moisture is NULL for every well — the hourly Open-Meteo request was
    # ~95% of the per-call cost and had to be dropped to finish the pull (see
    # DATA_CARD.md). Two of the four inputs the poster names for XGBoost are
    # therefore unavailable on the rural track. Say it, don't feed empty
    # columns to the model and hope.
    allnull = [c for c in feats if df[c].isna().all()]
    if allnull:
        print(f"[feat] dropping {len(allnull)} all-NULL columns: "
              f"{', '.join(allnull)}")
        feats = [c for c in feats if c not in allnull]

    sparse = {c: float(df[c].isna().mean()) for c in feats
              if df[c].isna().mean() > 0.2}
    if sparse:
        print("[feat] sparse but kept (XGBoost splits on missingness):")
        for c, frac in sorted(sparse.items(), key=lambda kv: -kv[1]):
            print(f"        {c:<24} {frac:.0%} null")

    print(f"\n[feat] {len(feats)} features: {', '.join(feats)}")

    leaky = [c for c in feats if c in
             ("level", "level_lag_7", "level_lag_15", "level_lag_30",
              "level_lag_60", "level_lag_90", "level_change_7d",
              "level_change_30d", "target_level_t30")]
    if leaky:
        sys.exit(f"ERROR: leaked columns present in features_causal: {leaky}")
    print("[feat] no gw_daily-derived level columns present — OK")

    tr = df[df.split == "train"]
    va = df[df.split == "val"]
    te = df[df.split == "test"]
    for name, part in (("train", tr), ("val", va), ("test", te)):
        if part.empty:
            sys.exit(f"ERROR: {name} split is empty.")
        print(f"[split] {name:<5} {len(part):>7,}  "
              f"{part.target_date.min()} → {part.target_date.max()}")

    assert tr.target_date.max() < va.target_date.min(), "train/val overlap"
    assert va.target_date.max() < te.target_date.min(), "val/test overlap"
    print("[split] chronological, no overlap — OK")

    if args.dry_run:
        print("\n[dry-run] data prep valid. Stopping before training.")
        return

    mdir = ROOT / args.model_dir
    mdir.mkdir(parents=True, exist_ok=True)

    # Name the model after the RUN, not the script. Two runs with different
    # --out files used to overwrite the same models/xgb_causal.json, so the
    # saved model and the saved metrics could describe different experiments
    # while looking paired. api/verify_model.py then compared the wrong two
    # things and reported a divergence that was purely bookkeeping.
    tag = "_weatheronly" if args.weather_only else ""
    if args.target != "delta_clim":
        tag += "_" + args.target
    stem = f"xgb_causal{tag}"

    payload = {"target": args.target, "params": PARAMS, "features": feats,
               "weather_only": bool(args.weather_only),
               "model_path": str((mdir / f"{stem}.json").relative_to(ROOT))}

    if args.per_horizon:
        merged = {"val": {"by_horizon": {}}, "test": {"by_horizon": {}}}
        f2 = [c for c in feats if c != "horizon_d"]
        for h in sorted(df.horizon_d.unique()):
            m, r = train_one(tr[tr.horizon_d == h], va[va.horizon_d == h],
                             te[te.horizon_d == h], f2, args.target, f"h={h}")
            m.save_model(str(mdir / f"{stem}_h{h}.json"))
            for sp in ("val", "test"):
                merged[sp]["by_horizon"][int(h)] = r[sp]
        results = merged
        payload["per_horizon"] = True
    else:
        model, results = train_one(tr, va, te, feats, args.target, "pooled")
        model.save_model(str(mdir / f"{stem}.json"))
        payload["best_iteration"] = int(model.best_iteration)
        gain = model.get_score(importance_type="gain")
        total = sum(gain.values()) or 1.0
        imp = sorted(((k, v / total) for k, v in gain.items()),
                     key=lambda kv: -kv[1])[:15]
        print("\n[imp ] top features by gain (share of total)")
        for k, v in imp:
            print(f"   {k:<24} {v:6.2%}")
        payload["importance"] = {k: float(v) for k, v in imp}
        unused = [f for f in feats if f not in gain]
        if unused:
            print(f"[imp ] never split on: {', '.join(unused)}")
            payload["unused_features"] = unused

    compare(results, ROOT / "reports" / "baseline_metrics.json")

    payload["results"] = results
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[out ] {out}")
    print(f"[out ] model: {payload['model_path']}")
    print(f"[out ] serve this run with: "
          f"export JALAAKAR_MODEL={ROOT / payload['model_path']}")


if __name__ == "__main__":
    main()
