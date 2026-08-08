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
    xgboost                                     77.3%  @ cutoff 53

Note the middle row: at the poster's cutoff of 71 the better forecaster warns
FEWER people, because its predictions sit closer to the seasonal mean and
cross a fixed line less often. That is why ACT_NOW_CUTOFF below is 53 and not
71 — the threshold was fitted on val to a stated recall target, never on test.
Moving to the model without moving the cutoff would have made the product
worse at the one thing it exists to do.
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

# Fitted on VAL for >= 80% recall (ml/04_operating_point.py), applied unchanged
# to test where it caught 77.3% of 510 real crises for 1,249 false alarms.
# The poster's band boundary is 71; this is a deliberate, stated override.
ACT_NOW_CUTOFF = 53
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
