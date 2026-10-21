"""
JALAAKAR — In-situ multi-depth sensor rig telemetry.

Handles live data stream and pilot baseline for the physical Jalaakar Sensor Rig:
- 4 soil moisture sensors along a 100 cm vertical shaft (20, 40, 60, 80 cm)
- 1 subsoil pH sensor at 100 cm
- ESP32 main controller streaming over Wi-Fi / Adafruit IO

Provides dual-mode operation:
- LIVE: when a physical ESP32 / Adafruit IO webhook is posting data
- STANDBY_PILOT: calibrated baseline for Dindori pilot unit when hardware is offline
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .appdb import app_db, new_id, utcnow

PILOT_BASELINE: Dict[str, Any] = {
    "device_id": "JALAAKAR-RIG-01",
    "taluka": "Dindori",
    "moist_20cm": 42.0,
    "moist_40cm": 31.5,
    "moist_60cm": 22.0,
    "moist_80cm": 14.5,
    "soil_ph": 7.2,
    "battery_v": 3.95,
}

LIVE_MAX_AGE_HOURS = 6


def moist_band(pct: float) -> str:
    """Color band for soil volumetric moisture percentage."""
    if pct >= 35.0:
        return "optimal"       # Green / high moisture
    if pct >= 20.0:
        return "adequate"      # Blue / stable buffer
    if pct >= 12.0:
        return "monitor"       # Amber / drying
    return "stress"            # Red / near permanent wilting point


def compute_advisory(m20: float, m40: float, m60: float, m80: float, ph: float) -> Dict[str, Any]:
    """Derives soil hydraulic metrics, infiltration status, and farmer guidance."""
    root_zone_avg = round((m20 + m40) / 2.0, 1)
    deep_buffer_avg = round((m60 + m80) / 2.0, 1)
    gradient = round((m20 - m80) / 60.0, 3)

    # Infiltration & Percolation Dynamics
    if m20 >= 35.0 and m80 >= 12.0:
        infilt_key = "ACTIVE_INFILTRATION"
        infilt_label = "Active Infiltration"
        infilt_desc = "Rain/irrigation is actively percolating through root zone into subsoil."
    elif m20 < 22.0 and m40 >= 25.0:
        infilt_key = "SURFACE_DRY_SUBSOIL_MOIST"
        infilt_label = "Subsoil Buffer Active"
        infilt_desc = "Topsoil is baked/dry, but the 40–60 cm root zone remains well-hydrated."
    elif m40 < 18.0 and m60 < 15.0:
        infilt_key = "ROOT_ZONE_STRESS"
        infilt_label = "Root-Zone Deficit"
        infilt_desc = "Moisture across 40–60 cm has fallen below crop safety levels."
    else:
        infilt_key = "STABLE_MOISTURE"
        infilt_label = "Stable Moisture Profile"
        infilt_desc = "Soil moisture levels are within normal seasonal range."

    # Actionable Irrigation Advice (Saves Borewell Water)
    if m40 >= 28.0:
        irrigation_advice = "Root zone at 40 cm has ~3–4 days of moisture. Delay borewell pumping by 48 hrs to conserve groundwater."
        pump_action = "DELAY_PUMP"
    elif m40 >= 18.0:
        irrigation_advice = "Adequate moisture for crop transpiration. Follow scheduled low-volume drip cycle."
        pump_action = "NORMAL_CYCLE"
    else:
        irrigation_advice = "Feeder roots approaching stress threshold. Irrigate immediately using low-volume drip."
        pump_action = "IRRIGATE_NOW"

    # Soil pH / Chemistry Evaluation
    if ph < 6.0:
        ph_status = "ACIDIC"
        ph_label = f"pH {ph:.1f} — Acidic (Check runoff / drainage)"
        ph_ok = False
    elif ph <= 7.8:
        ph_status = "OPTIMAL"
        ph_label = f"pH {ph:.1f} — Optimal / Balanced"
        ph_ok = True
    else:
        ph_status = "ALKALINE"
        ph_label = f"pH {ph:.1f} — Alkaline (Salinity risk from deep borewell water)"
        ph_ok = False

    return {
        "root_zone_avg_pct": root_zone_avg,
        "deep_buffer_avg_pct": deep_buffer_avg,
        "gradient_pct_per_cm": gradient,
        "infiltration_status": {
            "key": infilt_key,
            "label": infilt_label,
            "description": infilt_desc,
        },
        "irrigation_advice": irrigation_advice,
        "pump_action": pump_action,
        "soil_ph": {
            "value": round(ph, 2),
            "status": ph_status,
            "label": ph_label,
            "is_optimal": ph_ok,
        },
        "profile": [
            {"depth_cm": 20, "label": "Topsoil / Evaporative", "pct": round(m20, 1), "band": moist_band(m20)},
            {"depth_cm": 40, "label": "Active Feeder Roots",   "pct": round(m40, 1), "band": moist_band(m40)},
            {"depth_cm": 60, "label": "Deep Root Buffer",       "pct": round(m60, 1), "band": moist_band(m60)},
            {"depth_cm": 80, "label": "Subsoil Recharge Gate",  "pct": round(m80, 1), "band": moist_band(m80)},
        ],
    }


def record_telemetry(
    device_id: str,
    m20: float,
    m40: float,
    m60: float,
    m80: float,
    ph: float,
    battery_v: Optional[float] = None,
    taluka: Optional[str] = "Dindori",
    source: str = "esp32",
    raw_payload: str = "",
) -> Dict[str, Any]:
    """Records an incoming in-situ sensor rig reading into app.db."""
    # Clamp bounds for physical plausibility
    m20 = max(0.0, min(100.0, float(m20)))
    m40 = max(0.0, min(100.0, float(m40)))
    m60 = max(0.0, min(100.0, float(m60)))
    m80 = max(0.0, min(100.0, float(m80)))
    ph = max(0.0, min(14.0, float(ph)))

    rid = new_id("rig")
    now = utcnow()

    with app_db() as con:
        con.execute(
            """
            INSERT INTO rig_telemetry
            (reading_id, device_id, recorded_at, source,
             moist_20cm, moist_40cm, moist_60cm, moist_80cm,
             soil_ph, battery_v, taluka, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rid, device_id, now, source, m20, m40, m60, m80, ph, battery_v, taluka, raw_payload),
        )

    advisory = compute_advisory(m20, m40, m60, m80, ph)
    return {
        "reading_id": rid,
        "device_id": device_id,
        "recorded_at": now,
        "source": source,
        "taluka": taluka,
        "mode": "LIVE",
        **advisory,
    }


def get_latest_telemetry(taluka: Optional[str] = "Dindori") -> Dict[str, Any]:
    """Returns the most recent rig reading or calibrated standby pilot baseline."""
    with app_db() as con:
        q = "SELECT * FROM rig_telemetry"
        params: List[Any] = []
        if taluka:
            q += " WHERE LOWER(taluka) = LOWER(?)"
            params.append(taluka)
        q += " ORDER BY recorded_at DESC LIMIT 1"
        row = con.execute(q, params).fetchone()

    now = datetime.now(timezone.utc)

    if row:
        try:
            rec_time = datetime.fromisoformat(row["recorded_at"])
            if rec_time.tzinfo is None:
                rec_time = rec_time.replace(tzinfo=timezone.utc)
            is_live = (now - rec_time) <= timedelta(hours=LIVE_MAX_AGE_HOURS)
        except Exception:
            is_live = False

        m20 = float(row["moist_20cm"])
        m40 = float(row["moist_40cm"])
        m60 = float(row["moist_60cm"])
        m80 = float(row["moist_80cm"])
        ph = float(row["soil_ph"])
        advisory = compute_advisory(m20, m40, m60, m80, ph)

        return {
            "device_id": row["device_id"],
            "taluka": row["taluka"] or taluka or "Dindori",
            "recorded_at": row["recorded_at"],
            "source": row["source"],
            "mode": "LIVE" if is_live else "HISTORICAL",
            "battery_v": row["battery_v"],
            **advisory,
        }

    # Fallback to calibrated pilot baseline
    m20 = PILOT_BASELINE["moist_20cm"]
    m40 = PILOT_BASELINE["moist_40cm"]
    m60 = PILOT_BASELINE["moist_60cm"]
    m80 = PILOT_BASELINE["moist_80cm"]
    ph = PILOT_BASELINE["soil_ph"]
    advisory = compute_advisory(m20, m40, m60, m80, ph)

    return {
        "device_id": PILOT_BASELINE["device_id"],
        "taluka": taluka or PILOT_BASELINE["taluka"],
        "recorded_at": utcnow(),
        "source": "calibrated_pilot",
        "mode": "STANDBY_PILOT",
        "battery_v": PILOT_BASELINE["battery_v"],
        **advisory,
    }
