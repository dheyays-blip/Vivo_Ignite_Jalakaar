"""
JALAAKAR — the trained forecaster, loaded once and used for live scores.

What it predicts
----------------
`ml/02_xgboost.py` trains on the RESIDUAL against each well's seasonal
climatology, so the raw booster output is a correction, not a level. The
climatology has to be added back:

    forecast_level = booster.predict(features) + clim_season

Get that wrong and the numbers are nonsense in a way that still looks
plausible — a metre or two off, no error raised.

Degrading gracefully
--------------------
If `models/xgb_causal.json` is missing, or xgboost is not installed, this
returns None and `api/scoring.py` falls back to climatology, reporting
`rural-stress-1.0/climatology` as its method. The demo keeps working and the
API never claims a model result it did not compute.

The measured difference (2,584 held-out CGWB readings, ml/03 and ml/04):

                    MAE @7d   exact band   crises caught
    climatology      1.845 m       70.5%        52.0%
    xgboost          1.391 m       77.7%        43.9%  @ cutoff 71
    xgboost                                     77.5%  @ cutoff 54

The cutoff is a product decision, not a modelling one, and the answers trade
against each other on held-out test (7,752 rows, 510 real crises). All three
rows below are MEASURED by ml/04_operating_point.py, not interpolated:

    cutoff 54 (fitted)    395 caught, 1,157 false alarms   recall 77.5%, prec 25.5%
    cutoff 70 (shipped)   228 caught,   212 false alarms   recall 44.7%, prec 51.8%
    cutoff 71 (poster)    217 caught,   194 false alarms   recall 42.5%, prec 52.8%

ACT_NOW_CUTOFF is 70. That is a **deliberate move away from the value
ml/04_operating_point.py fitted**, and it costs 33 points of recall, so the
reason has to be stated rather than assumed: the product now broadcasts
state-wide from one button (`api/admin.py`). At 54 a single click sends 1,552
alerts of which 1,157 are false, and an alerting channel wrong three times in
four is one people mute — after which recall on paper is 77% and recall in
practice is zero. At 70 the same click sends 440 and is right more often than
not.

Both numbers are real and neither is free. If Jalaakar ever moves to
per-subscriber opt-in severity, 54 is the better default again, and
`reports/operating_point.json` holds the full curve to re-derive it from.
That script reads this constant rather than hard-coding it, so the "shipped"
row above cannot go stale when the constant changes.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .features_live import FEATURE_ORDER, as_row, build

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = Path(os.getenv("JALAAKAR_MODEL",
                            ROOT / "models" / "xgb_causal.json"))

METHOD = "rural-stress-1.1/xgboost"

# One set of bands for BOTH tracks: 0-40 SAFE, 41-70 MONITOR, 71-100 ACT NOW.
# Rural used to sit at 53 (fitted on val by ml/04_operating_point.py); it now
# matches the urban boundaries so a 68 in Nashik and a 68 in Mumbai mean the
# same thing on the same admin dashboard. See the module docstring for the
# recall/precision this costs and why it is the right call for broadcast.
ACT_NOW_CUTOFF = 70
MONITOR_CUTOFF = 40


@lru_cache(maxsize=1)
def _booster():
    if not MODEL_PATH.exists():
        print(f"[model] {MODEL_PATH} not found — falling back to climatology")
        return None
    try:
        import xgboost as xgb
    except ImportError:
        print("[model] xgboost not installed — falling back to climatology")
        return None
    b = xgb.Booster()
    b.load_model(str(MODEL_PATH))
    names = list(b.feature_names or [])
    if names != FEATURE_ORDER:
        # A silent reorder would feed rainfall into the latitude split.
        print("[model] FEATURE ORDER MISMATCH — refusing to use the model.\n"
              f"        model:  {names}\n"
              f"        serving:{FEATURE_ORDER}")
        return None
    print(f"[model] loaded {MODEL_PATH.name}, {len(names)} features, "
          f"best_iteration={b.best_iteration}")
    return b


def available() -> bool:
    return _booster() is not None


def forecast(well_id: str, origin: str, horizon_d: int = 30) -> dict | None:
    """Model forecast for one well. None if unavailable — caller falls back."""
    b = _booster()
    if b is None:
        return None
    feats = build(well_id, origin, horizon_d)
    if feats is None or feats.get("clim_season") is None:
        return None

    import numpy as np
    import xgboost as xgb

    row = np.array([[(np.nan if v is None else float(v))
                     for v in as_row(feats)]], dtype=np.float32)
    d = xgb.DMatrix(row, feature_names=FEATURE_ORDER, missing=np.nan)
    residual = float(b.predict(d, iteration_range=(0, b.best_iteration + 1))[0])

    return {
        "level": feats["clim_season"] + residual,
        "residual": residual,
        "clim_season": feats["clim_season"],
        "target_date": feats["_target_date"],
        "last_obs_date": feats["_last_obs_date"],
        "method": METHOD,
    }
