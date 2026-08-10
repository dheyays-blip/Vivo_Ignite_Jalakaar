"""
JALAAKAR — score cards for the dashboard.

Two tracks, two honesty stories, and the API tells you which one you are
looking at on every response via `method` and `data_through`.

URBAN  reads the precomputed `urban_stress` table. Real BMC / Irrigation
       Department readings, current to within a day, no leakage. This is the
       track that can be demoed live on 2026 data.

RURAL  computed here, per request. The CGWB record ends 2023-08-15, so a
       "live" rural score for August 2026 does not exist and this module will
       not invent one. Ask for a date inside the data and you get a real
       answer; ask for today and you get `status: "no_data"` with the reason.

       The rural formula mirrors the urban one so the two are comparable:
           score = S_depth (0-60) + S_trend (0-25) + S_headroom (0-15)
       and `method` records whether the forecast came from climatology (the
       1.845 m baseline) or from a trained model.

Level convention: level_mbgl is metres BELOW ground. Bigger = deeper = worse.
"""

from __future__ import annotations

from datetime import date, timedelta

import json
from functools import lru_cache
from pathlib import Path

from . import model as model_mod
from .appdb import pipeline_db

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# 4.5 — the score card carries its own language. The poster's sample card
# prints MARATHI on it, so the band has to be renderable in the user's
# language, not just in English with a language label bolted on.
# --------------------------------------------------------------------------
BAND_LABELS = {
    "SAFE":    {"en": "Safe",      "mr": "सुरक्षित", "hi": "सुरक्षित"},
    "MONITOR": {"en": "Monitor",   "mr": "लक्ष ठेवा", "hi": "निगरानी रखें"},
    "ACT NOW": {"en": "Act now",   "mr": "त्वरित कृती", "hi": "तुरंत कार्रवाई"},
}
LANG_NAMES = {"en": "ENGLISH", "mr": "MARATHI", "hi": "HINDI"}


def _label(band: str, lang: str) -> str:
    """Band in the requested language, English if that language is unknown."""
    row = BAND_LABELS.get(band)
    if not row:
        return band
    return row.get(lang) or row["en"]


# --------------------------------------------------------------------------
# 3.9 — prediction interval.
#
# Empirical, not parametric. ml/06_intervals.py measures the absolute-error
# quantiles per horizon on held-out CGWB readings and writes them here; a
# +/- band derived from actual observed error is defensible in a way that a
# Gaussian assumption over quarterly groundwater data is not.
#
# If the file is absent, no interval is returned at all. An interval invented
# from a default constant is worse than none, because it looks measured.
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _intervals() -> dict:
    p = ROOT / "reports" / "intervals.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except ValueError:
        return {}


def interval_for(horizon_d: int, method: str) -> dict | None:
    iv = _intervals()
    key = "xgboost" if "xgboost" in method else "climatology"
    band = (iv.get(key) or {}).get(str(horizon_d))
    if not band:
        return None
    return {"plus_minus_m": band["p80"], "coverage": 0.80,
            "p50_m": band.get("p50"), "p95_m": band.get("p95"),
            "n": band.get("n"), "source": "empirical, held-out CGWB readings"}

CLIM_METHOD = "rural-stress-1.0/climatology"
CRISIS_PERCENTILE = 0.90        # "crisis" = deeper than 90% of this well's history

# Urban keeps the poster's boundaries: its score is rule-based on directly
# observed storage, so there is no forecast error to tune a threshold against.
URBAN_BANDS = [(40, "SAFE", "GREEN"), (70, "MONITOR", "AMBER"),
               (100, "ACT NOW", "RED")]


def band_of(score: float) -> tuple[str, str]:
    for ceiling, name, colour in URBAN_BANDS:
        if score <= ceiling:
            return name, colour
    return "ACT NOW", "RED"


def rural_band(score: float) -> tuple[str, str]:
    """Same boundaries as urban: 0-40 SAFE, 41-70 MONITOR, 71-100 ACT NOW.

    Rural previously used 53, fitted on val by ml/04_operating_point.py for
    >= 80% recall. It now matches urban so that one number means one thing
    across both tracks on the admin dashboard, which lists them in a single
    table and broadcasts to both from one button. `api/model.py` states what
    that costs in recall and why it is still the right default for broadcast.
    """
    if score > model_mod.ACT_NOW_CUTOFF:
        return "ACT NOW", "RED"
    if score > model_mod.MONITOR_CUTOFF:
        return "MONITOR", "AMBER"
    return "SAFE", "GREEN"


# --------------------------------------------------------------------------
def urban_score(entity_id: str, on: str | None = None,
                lang: str = "en") -> dict:
    with pipeline_db() as con:
        if on:
            row = con.execute(
                "SELECT * FROM urban_stress WHERE entity_id=? AND date=?",
                (entity_id, on)).fetchone()
        else:
            row = con.execute(
                "SELECT * FROM urban_stress WHERE entity_id=? "
                "ORDER BY date DESC LIMIT 1", (entity_id,)).fetchone()
        if not row:
            return {"status": "no_data", "entity_id": entity_id,
                    "reason": f"no urban_stress row for {entity_id}"
                              f"{' on ' + on if on else ''}"}
        name = con.execute("SELECT name, city FROM reservoirs WHERE reservoir_id=?",
                           (entity_id,)).fetchone()

    r = dict(row)
    days = r["days_of_supply"]
    return {
        "status": "ok",
        "track": "urban",
        "entity_id": entity_id,
        "entity_label": name["name"] if name else entity_id,
        "date": r["date"],
        "score": r["score"],
        "band": r["band"],
        "colour": band_of(r["score"])[1],
        "days_to_crisis": int(days) if days is not None else None,
        "headline": {"label": "live storage",
                     "value": r["live_storage_pct"], "unit": "%"},
        "components": {"depletion": r["s_level"], "trend": r["s_trend"],
                       "runway": r["s_runway"]},
        "detail": {"trend_pp_per_day": r["trend_pp_per_day"],
                   "trend_window_d": r["trend_window_d"],
                   "days_of_supply": days},
        "method": r["method_version"],
        "provenance": r["inputs_source"],
        "data_through": r["date"],
        "lang": lang,
        "lang_name": LANG_NAMES.get(lang, "ENGLISH"),
        # BUG: an unknown lang fell through to the raw band ("ACT NOW"), so a
        # bad ?lang= produced different casing from ?lang=en ("Act now").
        # Fall back to the ENGLISH label, not to the enum value.
        "band_label": _label(r["band"], lang),
    }


# --------------------------------------------------------------------------
def _wells_for(entity_type: str, entity_id: str) -> list[str]:
    with pipeline_db() as con:
        if entity_type == "well":
            return [entity_id]
        rows = con.execute("SELECT well_id FROM wells WHERE taluka = ?",
                           (entity_id,)).fetchall()
        return [r["well_id"] for r in rows]


def rural_score(entity_type: str, entity_id: str,
                on: str | None = None, horizon_d: int = 30,
                lang: str = "en") -> dict:
    """Score a well or taluka at a date, forecasting `horizon_d` ahead.

    `on` is the ORIGIN date — when the forecast is made. The score describes
    the predicted state at on + horizon_d.
    """
    wells = _wells_for(entity_type, entity_id)
    if not wells:
        return {"status": "no_data", "entity_id": entity_id,
                "reason": f"no wells found for {entity_type} {entity_id}"}

    ph = ",".join("?" * len(wells))
    with pipeline_db() as con:
        last_real = con.execute(
            f"SELECT MAX(obs_date) d FROM gw_observations WHERE well_id IN ({ph})",
            wells).fetchone()["d"]
        if not last_real:
            return {"status": "no_data", "entity_id": entity_id,
                    "reason": "no observations for this entity"}

        origin = on or last_real
        if origin > last_real:
            return {
                "status": "no_data",
                "entity_id": entity_id,
                "reason": (
                    f"CGWB observations for this entity end {last_real}. "
                    f"No reading exists at {origin}, so no honest score can be "
                    f"produced for it. Pass ?on={last_real} or earlier."),
                "data_through": last_real,
            }

        target = (date.fromisoformat(origin) + timedelta(days=horizon_d)).isoformat()

        rows = con.execute(
            f"""SELECT o.well_id, o.obs_date, o.level_mbgl, o.season,
                       w.well_depth, w.village, w.taluka, w.district
                FROM gw_observations o JOIN wells w USING (well_id)
                WHERE o.well_id IN ({ph}) AND o.obs_date <= ?
                ORDER BY o.well_id, o.obs_date""", wells + [origin]).fetchall()

    if not rows:
        return {"status": "no_data", "entity_id": entity_id,
                "reason": f"no observations at or before {origin}"}

    by_well: dict[str, list] = {}
    for r in rows:
        by_well.setdefault(r["well_id"], []).append(dict(r))

    per_well, label = [], None
    target_season = _season_of(int(target[5:7]))
    used_model = False

    for wid, hist in by_well.items():
        if len(hist) < 4:
            continue
        label = label or (f"{hist[-1]['taluka']} Taluka, {hist[-1]['district']}"
                          if entity_type == "taluka"
                          else f"{hist[-1]['village']}, {hist[-1]['taluka']} Taluka")

        levels = sorted(h["level_mbgl"] for h in hist)
        crisis = levels[min(len(levels) - 1,
                            int(CRISIS_PERCENTILE * len(levels)))]
        shallow = levels[0]

        # Forecast: the trained model if it loaded, else that well's mean level
        # for the target season — the 1.845 m climatology baseline. Which one
        # was used is reported in `method` on every response; the API never
        # claims a model result it did not compute.
        forecast = None
        fc = model_mod.forecast(wid, origin, horizon_d)
        if fc is not None:
            forecast = fc["level"]
            used_model = True
        if forecast is None:
            seasonal = [h["level_mbgl"] for h in hist
                        if h["season"] == target_season]
            forecast = (sum(seasonal) / len(seasonal)) if seasonal else \
                       (sum(levels) / len(levels))

        last, prev = hist[-1], hist[-2]
        gap = (date.fromisoformat(last["obs_date"])
               - date.fromisoformat(prev["obs_date"])).days or 1
        trend = (last["level_mbgl"] - prev["level_mbgl"]) / gap   # +ve = deepening

        span = max(crisis - shallow, 0.5)
        s_depth = max(0.0, min(60.0, (forecast - shallow) / span * 60))
        s_trend = max(0.0, min(25.0, trend / 0.05 * 25)) if trend > 0 else 0.0
        depth = last.get("well_depth")
        if depth and depth > 0:
            s_head = max(0.0, min(15.0, (forecast / depth - 0.6) / 0.4 * 15))
        else:
            s_head = 0.0

        headroom = crisis - last["level_mbgl"]
        d2c = int(headroom / trend) if trend > 0 and headroom > 0 else None

        per_well.append({
            "well_id": wid,
            "score": round(s_depth + s_trend + s_head),
            "s_depth": round(s_depth, 2), "s_trend": round(s_trend, 2),
            "s_headroom": round(s_head, 2),
            "last_obs_level": last["level_mbgl"], "last_obs_date": last["obs_date"],
            "forecast_level": round(forecast, 2),
            "trend_m_per_day": round(trend, 5),
            "days_to_crisis": d2c,
        })

    if not per_well:
        return {"status": "no_data", "entity_id": entity_id,
                "reason": "fewer than 4 observations per well; cannot score"}

    # taluka = worst well. A taluka is safe only if all of it is safe.
    worst = max(per_well, key=lambda w: w["score"])
    score = worst["score"]
    name, colour = rural_band(score)
    d2c = [w["days_to_crisis"] for w in per_well if w["days_to_crisis"] is not None]

    return {
        "status": "ok",
        "track": "rural",
        "entity_id": entity_id,
        "entity_label": label or entity_id,
        "date": origin,
        "target_date": target,
        "horizon_d": horizon_d,
        "score": score,
        "band": name,
        "colour": colour,
        "days_to_crisis": min(d2c) if d2c else None,
        "headline": {"label": "forecast level",
                     "value": worst["forecast_level"], "unit": "m below ground"},
        "components": {"depth": worst["s_depth"], "trend": worst["s_trend"],
                       "headroom": worst["s_headroom"]},
        "detail": {"driving_well": worst["well_id"],
                   "last_obs_level": worst["last_obs_level"],
                   "last_obs_date": worst["last_obs_date"],
                   "days_since_last_reading":
                       (date.fromisoformat(origin)
                        - date.fromisoformat(worst["last_obs_date"])).days,
                   "wells_scored": len(per_well)},
        "wells": sorted(per_well, key=lambda w: -w["score"]),
        "method": model_mod.METHOD if used_model else CLIM_METHOD,
        "bands": {"monitor_above": model_mod.MONITOR_CUTOFF,
                  "act_now_above": model_mod.ACT_NOW_CUTOFF,
                  "note": "0-40 SAFE, 41-70 MONITOR, 71-100 ACT NOW — the "
                          "same boundaries as the urban track"},
        "provenance": "cgwb_observations",
        "lang": lang,
        "lang_name": LANG_NAMES.get(lang, "ENGLISH"),
        "band_label": _label(name, lang),
        "interval": interval_for(horizon_d,
                                 model_mod.METHOD if used_model else CLIM_METHOD),
        "data_through": max(w["last_obs_date"] for w in per_well),
    }


def _season_of(month: int) -> str:
    if month in (3, 4, 5):
        return "pre_monsoon"
    if month in (6, 7, 8, 9):
        return "monsoon"
    if month in (10, 11):
        return "post_monsoon"
    return "rabi"


# --------------------------------------------------------------------------
def score_for(entity_type: str, entity_id: str, on: str | None = None,
              horizon_d: int = 30, lang: str = "en") -> dict:
    if entity_type == "reservoir":
        return urban_score(entity_id, on, lang)
    if entity_type in ("well", "taluka"):
        return rural_score(entity_type, entity_id, on, horizon_d, lang)
    return {"status": "no_data", "entity_id": entity_id,
            "reason": f"unknown entity_type {entity_type!r}"}
