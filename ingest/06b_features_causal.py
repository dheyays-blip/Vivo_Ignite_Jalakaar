#!/usr/bin/env python3
"""
JALAAKAR — Stage 6b: causal features for forecasting.

The problem this solves
-----------------------
`06_features.py` builds every level column out of `gw_daily`, which is
interpolated BETWEEN real observations. The reconstructed level at origin t is
therefore partly made of the observation at t+30 that we are trying to predict.
`ml/01_baseline.py` measures it: persistence off gw_daily scores ~0.22 m MAE at
+7 days, against ~2.54 m for persistence off the last real reading. A model
trained on those columns posts a beautiful number and has learned nothing.

This script never touches gw_daily. Every feature is computable at origin time
from things that had already happened, and every label is a genuine CGWB
reading.

Shape
-----
One row per (well, origin_date, horizon). Targets are the 68,994 real
observations; origins are `target_date - horizon`. At three horizons that is
~207k candidate rows before filtering — roughly 6% the size of `features` and
worth far more.

Why this is smaller and better: 3.19M rows of interpolated targets is 3.19M
restatements of ~69k facts. Training on the restatements teaches a model to
reproduce `05_interpolate.py`.

Usage
-----
    python ingest/06b_features_causal.py
    python ingest/06b_features_causal.py --horizons 7,15,30 --min-obs 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import cfg, connect, log_run, read, upsert  # noqa: E402

RAIN_DAY_MM = 2.5
REQUIRE_WEATHER = False          # set by --require-weather


# --------------------------------------------------------------------------
def split_of(dates: pd.Series) -> pd.Series:
    s = cfg.splits
    out = pd.Series(pd.NA, index=dates.index, dtype=object)
    out[dates <= pd.Timestamp(s["train_end"])] = "train"
    out[(dates > pd.Timestamp(s["train_end"])) &
        (dates <= pd.Timestamp(s["val_end"]))] = "val"
    out[(dates > pd.Timestamp(s["val_end"])) &
        (dates <= pd.Timestamp(s["test_end"]))] = "test"
    return out


def season_of(months: pd.Series) -> pd.Series:
    lut = {}
    for name, mm in cfg.raw["seasons"].items():
        for m in mm:
            lut[m] = name
    return months.map(lut)


# --------------------------------------------------------------------------
def build_weather(con) -> pd.DataFrame:
    """Rolling weather aggregates per well-day. All strictly backward-looking."""
    print("[weather] loading ...", flush=True)
    w = read(con, "SELECT well_id, date, precip_mm, et0_mm, soil_moist_0_7, "
                  "soil_moist_7_28, temp_max, rh_mean FROM weather_daily")
    w["date"] = pd.to_datetime(w["date"])
    w = w.sort_values(["well_id", "date"])
    print(f"          {len(w):,} rows, {w.well_id.nunique():,} entities", flush=True)

    g = w.groupby("well_id", sort=False)
    for win in (7, 30, 90):
        w[f"rain_{win}d"] = g["precip_mm"].transform(
            lambda s: s.rolling(win, min_periods=1).sum())
    w["et0_30d"] = g["et0_mm"].transform(
        lambda s: s.rolling(30, min_periods=1).sum())

    # cumulative rainfall, used to difference between two dates cheaply
    w["rain_cum"] = g["precip_mm"].cumsum()
    w["et0_cum"] = g["et0_mm"].cumsum()

    # days since last rain day
    wet = w["precip_mm"] >= RAIN_DAY_MM
    grp = w.groupby("well_id", sort=False)
    idx = pd.Series(np.arange(len(w)), index=w.index)
    last_wet = idx.where(wet.values).groupby(w["well_id"].values).ffill()
    w["days_since_last_rain"] = (idx - last_wet).fillna(999).astype(int)

    # cumulative monsoon rainfall, resets 1 June
    start_m = cfg.raw["features"]["monsoon_start_month"]
    wy = w["date"].dt.year - (w["date"].dt.month < start_m).astype(int)
    w["cum_monsoon_rainfall"] = (w.groupby([w["well_id"], wy])["precip_mm"]
                                  .cumsum())
    return w.drop(columns=["precip_mm", "et0_mm"])


# --------------------------------------------------------------------------
def fit_climatology(obs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-well seasonal means from REAL TRAIN observations only.

    Not from gw_daily: a train-period gw_daily row near the split boundary can
    have been interpolated against a val-period observation. Real readings in
    the train window cannot leak by construction.
    """
    tr = obs[obs["split_obs"] == "train"]
    if tr.empty:
        sys.exit("ERROR: no train observations. Check config.yaml splits.")
    clim_season = (tr.groupby(["well_id", "season"])["level_mbgl"].mean()
                     .rename("clim_season").reset_index())
    clim_well = (tr.groupby("well_id")["level_mbgl"].mean()
                   .rename("clim_well").reset_index())
    print(f"[clim ] fitted on {len(tr):,} real train readings across "
          f"{tr.well_id.nunique():,} wells", flush=True)
    return clim_season, clim_well


# --------------------------------------------------------------------------
def build(con, horizons: list[int], min_obs: int) -> pd.DataFrame:
    obs = read(con, "SELECT well_id, obs_date AS date, level_mbgl, season "
                    "FROM gw_observations ORDER BY well_id, obs_date")
    obs["date"] = pd.to_datetime(obs["date"])
    obs["split_obs"] = split_of(obs["date"])
    obs = obs[obs["split_obs"].notna()]
    print(f"[obs  ] {len(obs):,} real readings inside the split windows")

    keep = obs.groupby("well_id")["date"].size()
    keep = keep[keep >= min_obs].index
    obs = obs[obs.well_id.isin(keep)]
    print(f"[obs  ] {len(obs):,} readings across {obs.well_id.nunique():,} wells "
          f"with >= {min_obs} readings")

    clim_season, clim_well = fit_climatology(obs)
    weather = build_weather(con)
    wells = read(con, "SELECT well_id, lat, lon, specific_yield, well_depth "
                      "FROM wells")

    # ---- observation history, as a lookup keyed on the observation date ----
    hist = obs[["well_id", "date", "level_mbgl"]].sort_values(["well_id", "date"])
    hist["prev_obs_level"] = hist.groupby("well_id")["level_mbgl"].shift(1)
    hist["prev_obs_date"] = hist.groupby("well_id")["date"].shift(1)
    hist = hist.rename(columns={"date": "last_obs_date",
                                "level_mbgl": "last_obs_level"})

    frames = []
    for h in horizons:
        t = obs[["well_id", "date", "level_mbgl", "season"]].copy()
        t = t.rename(columns={"date": "target_date", "level_mbgl": "target_level"})
        t["origin_date"] = t["target_date"] - pd.Timedelta(days=h)
        t["horizon_d"] = h

        # last REAL reading at or before origin
        left = t.sort_values("origin_date")
        right = (hist[["well_id", "last_obs_date", "last_obs_level"]]
                 .sort_values("last_obs_date"))
        t = pd.merge_asof(left, right, left_on="origin_date",
                          right_on="last_obs_date", by="well_id",
                          direction="backward")
        t = t.merge(hist[["well_id", "last_obs_date", "prev_obs_level",
                          "prev_obs_date"]],
                    on=["well_id", "last_obs_date"], how="left")
        frames.append(t)

    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    df = df[df["last_obs_date"].notna() & (df["last_obs_date"] < df["target_date"])]
    print(f"[pairs] {len(df):,} rows ({before - len(df):,} dropped: no prior "
          f"reading, or the prior reading IS the target)")

    df["days_since_obs"] = (df["origin_date"] - df["last_obs_date"]).dt.days
    df["prev_obs_gap_d"] = (df["last_obs_date"] - df["prev_obs_date"]).dt.days
    df["obs_trend_m_per_day"] = ((df["last_obs_level"] - df["prev_obs_level"])
                                 / df["prev_obs_gap_d"].replace(0, np.nan))

    # ---- weather at origin, and accumulated since the last real reading ----
    wcols = ["well_id", "date", "rain_7d", "rain_30d", "rain_90d", "et0_30d",
             "rain_cum", "et0_cum", "days_since_last_rain",
             "cum_monsoon_rainfall", "soil_moist_0_7", "soil_moist_7_28",
             "temp_max", "rh_mean"]
    df = df.merge(weather[wcols], left_on=["well_id", "origin_date"],
                  right_on=["well_id", "date"], how="left").drop(columns=["date"])
    at_obs = (weather[["well_id", "date", "rain_cum", "et0_cum"]]
              .rename(columns={"rain_cum": "rain_cum_obs",
                               "et0_cum": "et0_cum_obs"}))
    df = df.merge(at_obs, left_on=["well_id", "last_obs_date"],
                  right_on=["well_id", "date"], how="left").drop(columns=["date"])
    df["rain_since_obs"] = df["rain_cum"] - df["rain_cum_obs"]
    df["et0_since_obs"] = df["et0_cum"] - df["et0_cum_obs"]

    # Weather begins 2012-09-03 (history_floor, chosen to cut the fetch), but
    # observations go back to 2000. Dropping weatherless rows throws away
    # roughly two thirds of the training readings. XGBoost handles NaN natively,
    # so keeping them is usually the better trade — the seasonal and
    # last-reading features still carry signal. LSTM will need imputation.
    n_noweather = int(df["rain_30d"].isna().sum())
    if REQUIRE_WEATHER:
        df = df[df["rain_30d"].notna()]
        print(f"[trim ] dropped {n_noweather:,} rows with no weather at origin "
              f"(weather starts {cfg.raw['dates']['history_floor']})")
    else:
        print(f"[keep ] {n_noweather:,} rows kept with NULL weather "
              f"(pre-{cfg.raw['dates']['history_floor']}); pass --require-weather "
              f"to drop them")

    # ---- calendar of the target, static attributes, climatology ------------
    df["month"] = df["target_date"].dt.month
    df["doy"] = df["target_date"].dt.dayofyear
    df["season"] = season_of(df["month"])
    df = df.merge(wells, on="well_id", how="left")
    df = df.merge(clim_season, on=["well_id", "season"], how="left")
    df = df.merge(clim_well, on="well_id", how="left")
    df["clim_season"] = df["clim_season"].fillna(df["clim_well"])
    df["last_obs_anomaly"] = df["last_obs_level"] - df["clim_well"]

    df["split"] = split_of(df["target_date"])
    before = len(df)
    df = df[df["split"].notna() & df["target_level"].notna()]
    print(f"[trim ] dropped {before - len(df):,} rows outside a split window")

    df["origin_date"] = df["origin_date"].dt.strftime("%Y-%m-%d")
    df["target_date"] = df["target_date"].dt.strftime("%Y-%m-%d")

    cols = ["well_id", "origin_date", "target_date", "horizon_d",
            "last_obs_level", "days_since_obs", "prev_obs_level",
            "prev_obs_gap_d", "obs_trend_m_per_day", "last_obs_anomaly",
            "rain_since_obs", "et0_since_obs", "rain_7d", "rain_30d",
            "rain_90d", "et0_30d", "days_since_last_rain",
            "cum_monsoon_rainfall", "soil_moist_0_7", "soil_moist_7_28",
            "temp_max", "rh_mean", "month", "doy", "season",
            "specific_yield", "well_depth", "lat", "lon",
            "clim_season", "clim_well", "target_level", "split"]
    return df[cols].drop_duplicates(["well_id", "origin_date", "horizon_d"])


# --------------------------------------------------------------------------
def audit(con, df: pd.DataFrame) -> None:
    """The checks that would have caught the leak in `features`."""
    print("\n[audit] leakage checks")

    bad = (pd.to_datetime(df.origin_date) >= pd.to_datetime(df.target_date)).sum()
    print(f"   origin on/after target ............ {bad}  (must be 0)")

    obs = read(con, "SELECT well_id, obs_date FROM gw_observations")
    real = set(zip(obs.well_id, obs.obs_date))
    lbl = sum(1 for w, d in zip(df.well_id, df.target_date) if (w, d) not in real)
    print(f"   labels that are not real readings . {lbl}  (must be 0)")

    fut = (pd.to_datetime(df.target_date)
           - pd.to_timedelta(df.horizon_d, unit="D")
           - pd.to_datetime(df.origin_date)).dt.days.abs().sum()
    print(f"   horizon/date mismatches ........... {fut}  (must be 0)")

    per = df.groupby("split")["target_date"].agg(["count", "min", "max"])
    print("\n[audit] split boundaries")
    print(per.to_string())

    ov = df.groupby("split")["target_date"].agg(["min", "max"])
    order = [s for s in ("train", "val", "test") if s in ov.index]
    for a, b in zip(order, order[1:]):
        assert ov.loc[a, "max"] < ov.loc[b, "min"], f"{a}/{b} overlap"
    print("   chronological, no overlap ......... OK")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="7,15,30")
    ap.add_argument("--min-obs", type=int, default=20,
                    help="skip wells with fewer real readings than this")
    ap.add_argument("--require-weather", action="store_true",
                    help="drop pre-2012 rows instead of keeping NULL weather")
    args = ap.parse_args()
    horizons = [int(x) for x in args.horizons.split(",")]

    global REQUIRE_WEATHER
    REQUIRE_WEATHER = args.require_weather

    with log_run("06b_features_causal.py") as run:
        with connect() as con:
            df = build(con, horizons, args.min_obs)
            audit(con, df)
            n = upsert(con, "features_causal", df)
            print(f"\n[out  ] {n:,} rows written to features_causal")
            print(df.groupby(["split", "horizon_d"]).size().to_string())
            run.rows_out = n


if __name__ == "__main__":
    main()
