"""
A4/A5 — daily interpolation. THE KEYSTONE.
Owner: Dev A.

Turns 69k sparse quarterly observations into the daily series the 30-day model
needs. CGWB measures 4x/year (Jan, May, Aug, Nov), so ~99% of every well's daily
curve is reconstructed. That is honest and defensible ONLY because `is_observed`
marks the real readings and `confidence` decays away from them.

METHOD — and why this one
-------------------------
Four methods were validated on 1,088 held-out observations (every 4th reading
removed, reconstructed without it, error measured at that point):

    climatology + anomaly            MAE 1.32 m   <- SHIPPED
    seasonal climatology alone       MAE 1.52 m
    rainfall-driven recession        MAE 1.90 m
    linear between observations      MAE 1.99 m

The rainfall-physics approach the plan originally called for — exponential
recession with recharge pulses scaled by specific yield — came SECOND WORST.
Adding a rainfall-anomaly correction on top of the shipped method moved MAE by
0.005 m (1.321 -> 1.316), i.e. nothing. So rainfall is not used here.

This does NOT mean rainfall is useless to the project. It still feeds the
forecasting model as a feature in `features`. It simply does not help
reconstruct daily levels between quarterly readings — the seasonal cycle
already explains that variation.

How it works:
  1. CLIMATOLOGY — each well's own annual cycle, built from its quarterly means
     placed at mid-month and interpolated circularly across the year. With
     ~70 readings per well that is ~17 per season.
  2. ANOMALY — level minus climatology at each real reading, interpolated
     linearly in time between readings.
  3. RECONSTRUCT — daily level = climatology(day-of-year) + anomaly(day).
     At a real reading this is clim + (obs - clim) = obs EXACTLY, so the curve
     passes through every observation by construction, with no reconciliation
     step and no residual to distribute.
  4. CONFIDENCE — exp(-days_from_nearest_real_reading / tau).

WHAT TO SAY
    "We reconstruct daily levels from each well's own seasonal cycle plus a
     linearly interpolated anomaly. We validated four methods against held-out
     readings and chose the lowest-error one, at 1.32 m MAE. Rainfall-driven
     recession curves scored worse, so we didn't use them."

NEVER SAY: "we trained on 5 years of daily GSDA data."

Usage:
    python ingest/05_interpolate.py --taluka Dindori --validate --plot --no-load
    python ingest/05_interpolate.py                       # all wells -> gw_daily
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.db import cfg, connect, log_run, read, upsert  # noqa: E402

TAU_DAYS = 45.0       # confidence e-folding distance from nearest real reading
MIN_OBS = 4           # need at least one full seasonal cycle
MIN_LEVEL = 0.05      # never surface the water table above ground
pd.set_option("display.width", 200)


# ---------------------------------------------------------------- inputs
def load_inputs(con, taluka: str | None, limit: int | None):
    where, params = "", []
    if taluka:
        where, params = "WHERE w.taluka = ?", [taluka]
    wells = read(con, f"""
        SELECT w.well_id, w.taluka, w.district, w.village, w.well_depth
        FROM wells w {where} ORDER BY w.well_id""", params)
    if limit:
        wells = wells.head(limit)
    if wells.empty:
        sys.exit(f"[FAIL] no wells matched (taluka={taluka!r})")

    ids = tuple(wells.well_id)
    q = ",".join("?" * len(ids))
    obs = read(con, f"""SELECT well_id, obs_date AS date, level_mbgl
                        FROM gw_observations WHERE well_id IN ({q})
                        ORDER BY well_id, obs_date""", list(ids))
    obs["date"] = pd.to_datetime(obs["date"])
    return wells, obs


# ---------------------------------------------------------------- core
def climatology(o: pd.DataFrame):
    """This well's own annual cycle as a callable over day-of-year.

    Monthly means placed at mid-month, wrapped circularly so December flows
    into January without a discontinuity.
    """
    lv = o["level_mbgl"].to_numpy(dtype=float)
    months = o["date"].dt.month.to_numpy()
    means = pd.Series(lv).groupby(months).mean()
    if len(means) < 2:
        g = float(lv.mean())
        return lambda d: np.full(len(np.atleast_1d(d)), g)

    doy = np.array([pd.Timestamp(2001, int(m), 15).dayofyear for m in means.index])
    val = means.to_numpy(dtype=float)
    order = np.argsort(doy)
    doy, val = doy[order], val[order]
    doy_w = np.concatenate(([doy[-1] - 366], doy, [doy[0] + 366]))
    val_w = np.concatenate(([val[-1]], val, [val[0]]))
    return lambda d: np.interp(np.atleast_1d(d), doy_w, val_w)


def interpolate_well(wid: str, o: pd.DataFrame, depth: float | None,
                     daily_start: pd.Timestamp | None = None) -> pd.DataFrame:
    o = o.sort_values("date").drop_duplicates("date")
    if len(o) < MIN_OBS:
        return pd.DataFrame()

    clim = climatology(o)
    idx = pd.date_range(o.date.iloc[0], o.date.iloc[-1], freq="D")

    base = clim(idx.dayofyear.to_numpy())
    obs_base = clim(o.date.dt.dayofyear.to_numpy())
    anom = pd.Series(o.level_mbgl.to_numpy(dtype=float) - obs_base, index=o.date)
    anom_daily = (anom.reindex(idx.union(anom.index))
                      .interpolate("time").ffill().bfill()
                      .reindex(idx).to_numpy())

    level = base + anom_daily
    cap = depth if depth and np.isfinite(depth) and depth > MIN_LEVEL else np.inf
    level = np.clip(level, MIN_LEVEL, cap)

    obs_idx = np.flatnonzero(idx.isin(o.date))
    dist = np.abs(np.arange(len(idx))[:, None] - obs_idx[None, :]).min(axis=1)
    is_obs = np.zeros(len(idx), dtype=int)
    is_obs[obs_idx] = 1

    # Round the reconstructed values, THEN write the real readings back in
    # unrounded. Doing it the other way round left 21 of 28,717 observed rows
    # differing from gw_observations by ~2e-6 m — harmless float32 noise, but
    # `is_observed` is the column the whole honesty argument rests on, so it
    # should be bit-exact rather than nearly exact.
    level = np.round(level, 4)
    level[obs_idx] = o.set_index("date").loc[idx[obs_idx], "level_mbgl"].to_numpy()

    out = pd.DataFrame({
        "well_id": wid,
        "date": idx,
        "level_mbgl": level,
        "is_observed": is_obs,
        "confidence": np.round(np.exp(-dist / TAU_DAYS), 4),
    })
    # trim AFTER reconstruction so early rows stay anchored on earlier readings
    return out[out["date"] >= daily_start] if daily_start is not None else out


def run(wells, obs, daily_start=None) -> pd.DataFrame:
    obs_by = dict(list(obs.groupby("well_id")))
    out, skipped = [], 0
    for r in wells.itertuples(index=False):
        o = obs_by.get(r.well_id)
        if o is None or len(o) < MIN_OBS:
            skipped += 1
            continue
        d = interpolate_well(r.well_id, o, r.well_depth, daily_start)
        if not d.empty:
            out.append(d)
    if skipped:
        print(f"  [skip] {skipped} wells with < {MIN_OBS} observations")
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ---------------------------------------------------------------- A5
def validate(wells, obs) -> float:
    """Hold out every 4th reading, reconstruct without it, measure the error."""
    errs = []
    for r in wells.itertuples(index=False):
        o = obs.loc[obs.well_id == r.well_id].sort_values("date")
        if len(o) < 8:
            continue
        held = o.iloc[3::4]
        kept = o.drop(held.index)
        if len(kept) < MIN_OBS:
            continue
        d = interpolate_well(r.well_id, kept, r.well_depth)
        if d.empty:
            continue
        p = d.set_index("date")["level_mbgl"].reindex(held.date).to_numpy()
        e = p - held.level_mbgl.to_numpy(dtype=float)
        errs.extend(e[~np.isnan(e)])
    e = np.array(errs)
    if not len(e):
        return float("nan")
    print(f"\n  held-out readings : {len(e):,}")
    print(f"  MAE               : {np.abs(e).mean():.3f} m")
    print(f"  RMSE              : {np.sqrt((e ** 2).mean()):.3f} m")
    print(f"  bias              : {e.mean():+.3f} m")
    print(f"  90th pct |err|    : {np.percentile(np.abs(e), 90):.3f} m")
    return float(np.abs(e).mean())


def plot(daily, obs, wells, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ids = wells.well_id.tolist()[:4]
    fig, axes = plt.subplots(len(ids), 1, figsize=(13, 3 * len(ids)), sharex=True)
    for ax, wid in zip(np.atleast_1d(axes), ids):
        d = daily[daily.well_id == wid]
        o = obs[obs.well_id == wid]
        name = wells.loc[wells.well_id == wid, "village"].iloc[0]
        ax.plot(d.date, d.level_mbgl, lw=.9, color="#0f6fd6", label="reconstructed daily")
        ax.scatter(o.date, o.level_mbgl, s=20, color="#b3261e", zorder=3,
                   label="real reading")
        ax.invert_yaxis()
        ax.set_ylabel("mbgl")
        ax.set_title(f"{name} ({wid})", fontsize=9, loc="left")
        ax.grid(alpha=.25)
    np.atleast_1d(axes)[0].legend(fontsize=8)
    fig.suptitle("Jalaakar — daily reconstruction vs real readings", y=.995)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"  [plot] {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--taluka", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--no-load", action="store_true")
    ap.add_argument("--from", dest="from_date", default=None)
    a = ap.parse_args()

    with connect() as con:
        wells, obs = load_inputs(con, a.taluka, a.limit)
    print(f"[in] {len(wells)} wells · {len(obs):,} observations")

    ds = pd.Timestamp(a.from_date or cfg.daily_start)
    print(f"[win] materialising gw_daily from {ds.date()}")
    daily = run(wells, obs, ds)
    if daily.empty:
        sys.exit("[FAIL] nothing reconstructed")

    n_obs = int(daily.is_observed.sum())
    print(f"[out] {len(daily):,} daily rows · {n_obs:,} observed "
          f"({n_obs / len(daily) * 100:.2f}%)")
    print(f"      level range {daily.level_mbgl.min():.2f} – "
          f"{daily.level_mbgl.max():.2f} mbgl")

    mae = validate(wells, obs) if a.validate else None
    if a.plot:
        plot(daily, obs, wells, ROOT / "data" / "interim" / "interpolation_check.png")

    if not a.no_load:
        with log_run("05_interpolate.py", rows_in=len(obs)) as r:
            with connect() as con:
                r.rows_out = upsert(con, "gw_daily", daily)
                print(f"\n[db] gw_daily {r.rows_out:,}")
                c = con.execute("SELECT * FROM v_observed_ratio").fetchone()
                print(f"     observed ratio: {c['pct_observed']}% "
                      f"({c['n_observed']:,} of {c['n_daily_rows']:,})")
    if mae is not None:
        print(f"\n*** INTERPOLATION MAE = {mae:.3f} m — put this in DATA_CARD.md ***")


if __name__ == "__main__":
    main()
