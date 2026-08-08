"""
JALAAKAR — build the model's 26 causal features for ONE (well, date, horizon).

Why this file exists at all
---------------------------
`ingest/06b_features_causal.py` builds features in bulk, anchored on the 68,994
real observations, because that is what training needs. Serving needs the
opposite shape: any well, any origin date, right now.

The two MUST agree. If this file computes `rain_30d` over a slightly different
window than 06b did, the model sees inputs it was never trained on, the live
score quietly drifts from the 1.39 m MAE printed on the landing page, and
nothing anywhere errors. `api/verify_features.py` exists precisely to catch
that: it rebuilds rows that already exist in `features_causal` and asserts
they match.

Anything changed here must be changed in 06b, and vice versa.

Rules carried over from 06b, stated so they are hard to break by accident:
  * every rolling window ENDS at the origin date, inclusive
  * calendar features (month, doy, season) come from the TARGET date, not the
    origin — the model predicts what the level will be then
  * climatology is fitted on TRAIN observations only (<= splits.train_end)
  * a rain day is >= 2.5 mm; cumulative monsoon rainfall resets on 1 June
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from .appdb import pipeline_db

RAIN_DAY_MM = 2.5
MONSOON_START_MONTH = 6
SEASON_CODES = {"pre_monsoon": 0, "monsoon": 1, "post_monsoon": 2, "rabi": 3}

FEATURE_ORDER = [
    "horizon_d", "last_obs_level", "days_since_obs", "prev_obs_level",
    "prev_obs_gap_d", "obs_trend_m_per_day", "last_obs_anomaly",
    "rain_since_obs", "et0_since_obs", "rain_7d", "rain_30d", "rain_90d",
    "et0_30d", "days_since_last_rain", "cum_monsoon_rainfall", "temp_max",
    "rh_mean", "month", "doy", "season", "specific_yield", "well_depth",
    "lat", "lon", "clim_season", "clim_well",
]


def season_of(month: int) -> str:
    if month in (3, 4, 5):
        return "pre_monsoon"
    if month in (6, 7, 8, 9):
        return "monsoon"
    if month in (10, 11):
        return "post_monsoon"
    return "rabi"


@lru_cache(maxsize=1)
def _train_end() -> str:
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent /
                          "config.yaml").read_text())
    return str(cfg["splits"]["train_end"])


def _win(con, well_id: str, origin: str, days: int, col: str):
    """Sum of `col` over the `days`-long window ending at origin, inclusive."""
    start = (date.fromisoformat(origin) - timedelta(days=days - 1)).isoformat()
    r = con.execute(
        f"SELECT SUM({col}) s, COUNT({col}) n FROM weather_daily "
        f"WHERE well_id=? AND date BETWEEN ? AND ?",
        (well_id, start, origin)).fetchone()
    return r["s"] if r and r["n"] else None


def build(well_id: str, origin: str, horizon_d: int = 30) -> dict | None:
    """Returns the feature dict, or None if the well has no usable history."""
    target = (date.fromisoformat(origin) + timedelta(days=horizon_d)).isoformat()
    t_month = int(target[5:7])
    t_season = season_of(t_month)

    with pipeline_db() as con:
        w = con.execute("SELECT lat, lon, specific_yield, well_depth "
                        "FROM wells WHERE well_id=?", (well_id,)).fetchone()
        if not w:
            return None

        # ---- the two most recent REAL readings at or before origin ---------
        obs = con.execute(
            "SELECT obs_date, level_mbgl FROM gw_observations "
            "WHERE well_id=? AND obs_date<=? ORDER BY obs_date DESC LIMIT 2",
            (well_id, origin)).fetchall()
        if not obs:
            return None
        last = dict(obs[0])
        prev = dict(obs[1]) if len(obs) > 1 else None

        # ---- climatology, TRAIN observations only --------------------------
        te = _train_end()
        cw = con.execute(
            "SELECT AVG(level_mbgl) m FROM gw_observations "
            "WHERE well_id=? AND obs_date<=?", (well_id, te)).fetchone()["m"]
        cs = con.execute(
            "SELECT AVG(level_mbgl) m FROM gw_observations "
            "WHERE well_id=? AND obs_date<=? AND season=?",
            (well_id, te, t_season)).fetchone()["m"]
        clim_well = cw
        clim_season = cs if cs is not None else cw

        # ---- weather to origin ---------------------------------------------
        # 06b MERGES the weather frame on (well_id, origin_date). If there is
        # no weather row at exactly the origin, every weather feature comes out
        # null — the whole merge misses. Weather begins 2012-09-03 while
        # observations begin in 2000, so this is the normal case for 62.5% of
        # training rows, and the model learned a default branch for it.
        # Computing a partial sum here instead would hand the model a value it
        # never saw during training.
        at = con.execute(
            "SELECT temp_max, rh_mean FROM weather_daily WHERE well_id=? AND date=?",
            (well_id, origin)).fetchone()
        has_w = at is not None

        if has_w:
            rain_7d = _win(con, well_id, origin, 7, "precip_mm")
            rain_30d = _win(con, well_id, origin, 30, "precip_mm")
            rain_90d = _win(con, well_id, origin, 90, "precip_mm")
            et0_30d = _win(con, well_id, origin, 30, "et0_mm")

            lr = con.execute(
                "SELECT MAX(date) d FROM weather_daily "
                "WHERE well_id=? AND date<=? AND precip_mm>=?",
                (well_id, origin, RAIN_DAY_MM)).fetchone()["d"]
            dslr = ((date.fromisoformat(origin) - date.fromisoformat(lr)).days
                    if lr else 999)

            # cumulative monsoon rainfall — resets 1 June
            o = date.fromisoformat(origin)
            wy = o.year - (1 if o.month < MONSOON_START_MONTH else 0)
            cum_v = con.execute(
                "SELECT SUM(precip_mm) s FROM weather_daily "
                "WHERE well_id=? AND date BETWEEN ? AND ?",
                (well_id, f"{wy}-06-01", origin)).fetchone()["s"]

            # Accumulated since the last real reading. 06b computes this as a
            # difference of cumulative sums looked up at BOTH dates, so if the
            # anchor date predates the weather series the result is null — not
            # a partial total. Reproduce that by requiring a row at the anchor.
            anchor = con.execute(
                "SELECT 1 FROM weather_daily WHERE well_id=? AND date=?",
                (well_id, last["obs_date"])).fetchone()
            if anchor:
                since_start = (date.fromisoformat(last["obs_date"]) +
                               timedelta(days=1)).isoformat()
                acc = con.execute(
                    "SELECT SUM(precip_mm) r, SUM(et0_mm) e "
                    "FROM weather_daily WHERE well_id=? AND date BETWEEN ? AND ?",
                    (well_id, since_start, origin)).fetchone()
                rain_since, et0_since = acc["r"], acc["e"]
            else:
                rain_since = et0_since = None
        else:
            rain_7d = rain_30d = rain_90d = et0_30d = None
            dslr = cum_v = rain_since = et0_since = None

    gap = ((date.fromisoformat(last["obs_date"]) -
            date.fromisoformat(prev["obs_date"])).days) if prev else None
    trend = ((last["level_mbgl"] - prev["level_mbgl"]) / gap) if (prev and gap) else None

    return {
        "horizon_d": float(horizon_d),
        "last_obs_level": last["level_mbgl"],
        "days_since_obs": float((date.fromisoformat(origin) -
                                 date.fromisoformat(last["obs_date"])).days),
        "prev_obs_level": prev["level_mbgl"] if prev else None,
        "prev_obs_gap_d": float(gap) if gap is not None else None,
        "obs_trend_m_per_day": trend,
        "last_obs_anomaly": (last["level_mbgl"] - clim_well)
                            if clim_well is not None else None,
        "rain_since_obs": rain_since,
        "et0_since_obs": et0_since,
        "rain_7d": rain_7d, "rain_30d": rain_30d, "rain_90d": rain_90d,
        "et0_30d": et0_30d,
        "days_since_last_rain": float(dslr) if dslr is not None else None,
        "cum_monsoon_rainfall": cum_v,
        "temp_max": at["temp_max"] if at else None,
        "rh_mean": at["rh_mean"] if at else None,
        "month": float(t_month),
        "doy": float(date.fromisoformat(target).timetuple().tm_yday),
        "season": float(SEASON_CODES[t_season]),
        "specific_yield": w["specific_yield"],
        "well_depth": w["well_depth"],
        "lat": w["lat"], "lon": w["lon"],
        "clim_season": clim_season, "clim_well": clim_well,
        # not features — carried for the scorer and the UI
        "_last_obs_date": last["obs_date"],
        "_target_date": target,
    }


def as_row(feats: dict) -> list:
    """Feature dict -> list in the exact order the booster expects."""
    return [feats.get(k) for k in FEATURE_ORDER]
