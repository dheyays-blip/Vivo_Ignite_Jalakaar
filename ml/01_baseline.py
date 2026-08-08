#!/usr/bin/env python3
"""
JALAAKAR — ML Stage 1: baselines. Run this BEFORE any model.

Why this exists
---------------
A neural network that cannot beat "tomorrow looks like today" is not a model,
it is decoration. These numbers are the bar. Every later result in this repo
is quoted against them, and if XGBoost or the LSTM does not clear them, that
is a finding to report, not a failure to hide.

The one thing that makes these numbers honest
---------------------------------------------
`gw_daily` is 99.12% interpolated — 28,717 real readings inside 3,250,606 daily
rows. Scoring against interpolated targets measures how well a model reproduces
`05_interpolate.py`, not how well it predicts groundwater. It would look
excellent and mean nothing.

So **every metric here is computed only where the target date is a genuine CGWB
observation.** That leaves 3,837 evaluation points in val and 2,584 in test —
small, real, and defensible. `--include-interpolated` will score against the
full reconstruction, purely so you can see the gap for yourself. Do not quote
those numbers anywhere.

Level convention: `level_mbgl` is metres BELOW ground. Bigger = deeper = worse.
Errors are in metres, so they are directly comparable to the 1.32 m
interpolation MAE reported in DATA_CARD.md.

Baselines
---------
    persistence_daily  level(t+h) = reconstructed level at t. What you would
                       actually have at prediction time.
    persistence_obs    level(t+h) = last REAL observation at or before t.
                       Harsher and more honest: no interpolation in the input.
    climatology        per-well mean level for that day-of-year (±15 d),
                       fitted on the TRAIN period only. Captures the seasonal
                       cycle, which for quarterly monsoon data is most of the
                       signal.
    well_mean          per-well train mean. The no-skill floor.

Usage
-----
    python ml/01_baseline.py
    python ml/01_baseline.py --horizons 7,15,30 --out reports/baseline.json
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

CLIMATOLOGY_WINDOW_D = 15


# --------------------------------------------------------------------------
def load(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("[load] gw_daily ...", flush=True)
    daily = read(con, "SELECT well_id, date, level_mbgl, is_observed, confidence "
                      "FROM gw_daily")
    daily["date"] = pd.to_datetime(daily["date"])
    print(f"       {len(daily):,} rows, {int(daily.is_observed.sum()):,} observed "
          f"({100 * daily.is_observed.mean():.2f}%)")

    print("[load] gw_observations ...", flush=True)
    obs = read(con, "SELECT well_id, obs_date AS date, level_mbgl, season "
                    "FROM gw_observations")
    obs["date"] = pd.to_datetime(obs["date"])
    print(f"       {len(obs):,} real readings")
    return daily, obs


def split_of(dates: pd.Series) -> pd.Series:
    s = cfg.splits
    out = pd.Series(pd.NA, index=dates.index, dtype=object)
    out[dates <= pd.Timestamp(s["train_end"])] = "train"
    out[(dates > pd.Timestamp(s["train_end"])) &
        (dates <= pd.Timestamp(s["val_end"]))] = "val"
    out[(dates > pd.Timestamp(s["val_end"])) &
        (dates <= pd.Timestamp(s["test_end"]))] = "test"
    return out


# --------------------------------------------------------------------------
def fit_climatology(daily: pd.DataFrame) -> pd.DataFrame:
    """Per-well, per-day-of-year mean, fitted on TRAIN rows only.

    Uses the reconstructed daily series rather than the ~30 real readings per
    well, because a day-of-year climatology needs coverage. The reconstruction
    is fitted on real observations, so this is a summary of the training
    signal, not an independent source — and it never sees val or test.
    """
    train = daily[daily["split"] == "train"]
    if train.empty:
        sys.exit("ERROR: no train rows. Check config.yaml splits.")

    print(f"[fit ] climatology on {len(train):,} train rows "
          f"(≤ {cfg.splits['train_end']})", flush=True)

    t = train[["well_id", "level_mbgl"]].copy()
    t["doy"] = train["date"].dt.dayofyear

    # ±15-day smoothing via a wrapped rolling mean over the 366-day cycle
    grid = (t.groupby(["well_id", "doy"])["level_mbgl"].mean()
              .rename("clim").reset_index())
    full = (grid.set_index(["well_id", "doy"])
                .reindex(pd.MultiIndex.from_product(
                    [grid.well_id.unique(), range(1, 367)],
                    names=["well_id", "doy"]))["clim"])
    w = 2 * CLIMATOLOGY_WINDOW_D + 1
    full = (full.groupby(level="well_id")
                .transform(lambda s: pd.concat([s, s, s])
                           .rolling(w, center=True, min_periods=1).mean()
                           .iloc[len(s):2 * len(s)].values))
    clim = full.reset_index().rename(columns={0: "clim"})
    clim.columns = ["well_id", "doy", "clim"]

    well_mean = (train.groupby("well_id")["level_mbgl"].mean()
                      .rename("well_mean").reset_index())
    clim = clim.merge(well_mean, on="well_id", how="left")
    clim["clim"] = clim["clim"].fillna(clim["well_mean"])
    print(f"       {clim.well_id.nunique():,} wells covered")
    return clim


# --------------------------------------------------------------------------
def build_pairs(daily: pd.DataFrame, obs: pd.DataFrame,
                horizon: int, observed_targets_only: bool) -> pd.DataFrame:
    """One row per (well, origin t, target t+h) evaluation point."""
    targets = obs.copy() if observed_targets_only else daily[["well_id", "date",
                                                              "level_mbgl"]].copy()
    targets = targets.rename(columns={"date": "target_date",
                                      "level_mbgl": "y_true"})
    targets["date"] = targets["target_date"] - pd.Timedelta(days=horizon)

    # the state the model would actually have at origin time t
    state = daily[["well_id", "date", "level_mbgl", "is_observed",
                   "confidence"]].rename(columns={"level_mbgl": "level_t"})

    p = targets.merge(state, on=["well_id", "date"], how="inner")
    p["split"] = split_of(p["target_date"])
    return p[p["split"].notna()]


def last_observation_at_or_before(obs: pd.DataFrame,
                                  pairs: pd.DataFrame) -> pd.Series:
    """Nearest REAL reading at or before origin t — no interpolation used."""
    o = obs[["well_id", "date", "level_mbgl"]].sort_values("date")
    p = pairs[["well_id", "date"]].reset_index().sort_values("date")
    merged = pd.merge_asof(p, o, on="date", by="well_id", direction="backward")
    return merged.set_index("index")["level_mbgl"].reindex(pairs.index)


# --------------------------------------------------------------------------
def metrics(y_true: pd.Series, y_pred: pd.Series) -> dict:
    m = y_true.notna() & y_pred.notna()
    if not m.any():
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    e = (y_pred[m] - y_true[m]).astype(float)
    return {
        "n": int(m.sum()),
        "mae": round(float(e.abs().mean()), 3),
        "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
        "bias": round(float(e.mean()), 3),
    }


def evaluate(daily, obs, clim, horizons, observed_only) -> dict:
    results: dict = {}
    for h in horizons:
        pairs = build_pairs(daily, obs, h, observed_only)
        pairs = pairs.merge(clim.assign(doy=clim.doy.astype(int)),
                            left_on=["well_id",
                                     pairs["target_date"].dt.dayofyear],
                            right_on=["well_id", "doy"], how="left")
        pairs["persist_obs"] = last_observation_at_or_before(obs, pairs)

        preds = {
            "persistence_daily": pairs["level_t"],
            "persistence_obs":   pairs["persist_obs"],
            "climatology":       pairs["clim"],
            "well_mean":         pairs["well_mean"],
        }
        for sp in ("val", "test"):
            s = pairs[pairs["split"] == sp]
            if s.empty:
                continue
            for name, col in preds.items():
                results.setdefault(f"h{h}", {}).setdefault(sp, {})[name] = \
                    metrics(s["y_true"], col.loc[s.index])
    return results


# --------------------------------------------------------------------------
def report(results: dict, observed_only: bool) -> None:
    tag = ("REAL observations only" if observed_only
           else "ALL rows incl. interpolated — DO NOT QUOTE")
    print(f"\n{'=' * 74}")
    print(f"  BASELINE — targets: {tag}")
    print(f"  error in metres below ground level; lower is better")
    print(f"{'=' * 74}")
    for hk in sorted(results, key=lambda k: int(k[1:])):
        for sp in ("val", "test"):
            if sp not in results[hk]:
                continue
            r = results[hk][sp]
            n = next(iter(r.values()))["n"]
            print(f"\n  horizon +{hk[1:]:>2} days   split={sp}   n={n:,}")
            print(f"  {'method':<20} {'MAE':>8} {'RMSE':>8} {'bias':>8}")
            print(f"  {'-' * 46}")
            for name, m in sorted(r.items(), key=lambda kv: (kv[1]["mae"] is None,
                                                             kv[1]["mae"])):
                if m["mae"] is None:
                    continue
                print(f"  {name:<20} {m['mae']:>8.3f} {m['rmse']:>8.3f} "
                      f"{m['bias']:>+8.3f}")

    # ---- leakage check ------------------------------------------------
    # persistence_daily reads gw_daily at t. gw_daily is interpolated BETWEEN
    # real observations, so the value at t was built partly from the very
    # observation at t+h that we are trying to predict. If it beats
    # persistence_obs — which uses only real past readings — that gap is
    # leakage, not skill.
    leaks = []
    for hk, byspl in results.items():
        d = byspl.get("test", {})
        a, b = d.get("persistence_daily"), d.get("persistence_obs")
        if a and b and a["mae"] is not None and b["mae"] is not None:
            if a["mae"] < b["mae"] * 0.8:
                leaks.append((hk, a["mae"], b["mae"]))

    if leaks:
        print(f"\n{'!' * 74}")
        print("  LEAKAGE DETECTED — persistence_daily is contaminated")
        print(f"{'!' * 74}")
        for hk, a, b in sorted(leaks, key=lambda x: int(x[0][1:])):
            print(f"    +{hk[1:]:>2}d   gw_daily state {a:.3f} m   vs   "
                  f"last real reading {b:.3f} m")
        print("""
  gw_daily interpolates BETWEEN real observations. The reconstructed level at
  origin t therefore already encodes the observation at t+h — the thing we are
  predicting. Any feature derived from gw_daily near t carries the same taint,
  which means `features.level`, every `level_lag_*` and every `level_change_*`
  column is contaminated for this task.

  A model trained on those columns will post an excellent MAE and mean nothing.

  The honest baseline is persistence_obs: last REAL reading, no interpolation.
  Beat that.
""")

    best = {}
    for hk, byspl in results.items():
        if "test" not in byspl:
            continue
        cand = {k: v["mae"] for k, v in byspl["test"].items()
                if v["mae"] is not None and not (leaks and k == "persistence_daily")}
        if cand:
            best[hk] = min(cand.items(), key=lambda kv: kv[1])
    if best:
        print(f"{'=' * 74}")
        print("  THE BAR — best UNCONTAMINATED baseline MAE on test.")
        print("  Beat these or say why.")
        for hk in sorted(best, key=lambda k: int(k[1:])):
            name, mae = best[hk]
            print(f"    +{hk[1:]:>2}d   {mae:.3f} m   ({name})")
        print(f"{'=' * 74}\n")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="7,15,30")
    ap.add_argument("--include-interpolated", action="store_true",
                    help="also score against interpolated targets (diagnostic only)")
    ap.add_argument("--out", default="reports/baseline_metrics.json")
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",")]

    with connect() as con:
        daily, obs = load(con)

    daily["split"] = split_of(daily["date"])
    clim = fit_climatology(daily)

    print(f"\n[eval] horizons {horizons}, observed targets only", flush=True)
    honest = evaluate(daily, obs, clim, horizons, observed_only=True)
    report(honest, observed_only=True)

    payload = {"observed_targets_only": honest,
               "config": {"horizons": horizons,
                          "splits": cfg.splits,
                          "climatology_window_d": CLIMATOLOGY_WINDOW_D}}

    if args.include_interpolated:
        print("\n[eval] diagnostic pass over interpolated targets", flush=True)
        loose = evaluate(daily, obs, clim, horizons, observed_only=False)
        report(loose, observed_only=False)
        payload["all_targets_diagnostic"] = loose
        print("  The gap between the two tables is the size of the mistake you\n"
              "  would have made by scoring against your own interpolation.\n")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    # cfg.splits holds datetime.date objects straight out of config.yaml
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[out ] {out}")


if __name__ == "__main__":
    main()
