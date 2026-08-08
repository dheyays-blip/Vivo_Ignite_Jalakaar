#!/usr/bin/env python3
"""
JALAAKAR — FastAPI backend.

Serves the existing static frontend in `web/` and the API it was written
against. `web/script.js` already logs the payload it "would POST to
/api/signup"; this is that endpoint, with the same field names and the same
phone validation, so nothing on the page has to change shape.

Run
---
    pip install -r requirements-api.txt
    uvicorn api.main:app --reload --port 8000
    # http://localhost:8000  -> the site
    # http://localhost:8000/docs -> interactive API docs

WhatsApp
--------
Optional. Without credentials, alerts are rendered and logged, never faked as
delivered. With them, they go out through the Twilio sandbox:

    export TWILIO_ACCOUNT_SID=...
    export TWILIO_AUTH_TOKEN=...
    export TWILIO_WHATSAPP_FROM='whatsapp:+14155238886'
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import alerts as alerts_mod
from . import figures as figures_mod
from . import places as places_mod
from . import scoring
from .appdb import app_db, new_id, normalise_phone, pipeline_db, utcnow

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

app = FastAPI(title="Jalaakar API", version="1.0",
              description="Water stress forecasting for Maharashtra.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000",
                   "http://localhost:5500", "https://jalaakar.in"],
    allow_methods=["*"], allow_headers=["*"],
)


# --------------------------------------------------------------------------
class SignupIn(BaseModel):
    role: Literal["farmer", "society-manager", "society-resident", "government"]
    name: str = Field(min_length=2)
    phone: str
    place: str = Field(min_length=1)
    lang: Literal["mr", "hi", "en"] = "mr"


@app.get("/api/health")
def health():
    out = {"ok": True, "app_db": True}
    try:
        with pipeline_db() as con:
            for t in ("wells", "gw_observations", "reservoir_daily", "urban_stress"):
                out[t] = con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
    except Exception as e:                          # noqa: BLE001
        out["ok"] = False
        out["pipeline_db_error"] = str(e)
    return out


# ---- figures -------------------------------------------------------------
@app.get("/api/figures")
def get_figures():
    """Landing-page numbers with provenance, derived from reservoir_seeds.csv.

    The page should render whatever this returns. That is the point: a
    correction in the data cannot leave a stale number on the site.
    """
    return figures_mod.load()


# ---- places --------------------------------------------------------------
@app.get("/api/places")
def get_places(q: str = Query(min_length=2), limit: int = 10):
    return {"query": q, "results": places_mod.search(q, limit)}


@app.get("/api/places/resolve")
def resolve_place(place: str, role: str = "farmer"):
    return places_mod.resolve(place, role)


@app.get("/api/districts")
def get_districts():
    """Districts that have wells behind them, for the demo cascade."""
    with pipeline_db() as con:
        rows = con.execute(
            "SELECT district, COUNT(DISTINCT taluka) n_talukas, COUNT(*) n_wells "
            "FROM wells WHERE district IS NOT NULL "
            "GROUP BY district ORDER BY district").fetchall()
    return {"districts": [dict(r) for r in rows]}


@app.get("/api/talukas")
def get_talukas(district: str, min_wells: int = 1):
    """Talukas in a district.

    `n_wells` is returned on every row and the demo shows it: 29 of the 247
    talukas have exactly one well, and a score built on a single borehole is
    real but thin. Better to display the count than to quietly imply that
    every taluka is equally well observed.
    """
    with pipeline_db() as con:
        rows = con.execute(
            "SELECT taluka, COUNT(*) n_wells, MAX(last_obs) last_obs "
            "FROM wells WHERE district = ? AND taluka IS NOT NULL "
            "GROUP BY taluka HAVING COUNT(*) >= ? ORDER BY taluka",
            (district, min_wells)).fetchall()
    return {"district": district, "talukas": [dict(r) for r in rows]}


# ---- signup --------------------------------------------------------------
@app.post("/api/signup", status_code=201)
def signup(body: SignupIn):
    try:
        phone = normalise_phone(body.phone)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    res = places_mod.resolve(body.place, body.role)
    entity_type = res.get("entity_type") if res["status"] == "ok" else "unresolved"
    entity_id = res.get("entity_id") if res["status"] == "ok" else None
    label = res.get("label") if res["status"] == "ok" else body.place

    user_id = new_id("usr")
    with app_db() as con:
        existing = con.execute("SELECT user_id FROM users WHERE phone_e164=?",
                               (phone,)).fetchone()
        if existing:
            raise HTTPException(409, "That number is already registered.")
        con.execute(
            "INSERT INTO users (user_id,role,name,phone_e164,lang,place_raw,"
            "entity_type,entity_id,entity_label,verified,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, body.role, body.name.strip(), phone, body.lang,
             body.place.strip(), entity_type, entity_id, label,
             0 if body.role == "government" else 1, utcnow()))

    card = None
    if entity_id:
        card = scoring.score_for(entity_type, entity_id)

    return {
        "user_id": user_id,
        "phone": phone,
        "lang": body.lang,
        "entity": {"type": entity_type, "id": entity_id, "label": label},
        "resolution": res["status"],
        "candidates": res.get("candidates", []),
        "requires_verification": body.role == "government",
        "score": card,
    }


# ---- score ---------------------------------------------------------------
@app.get("/api/score/{user_id}")
def score_for_user(user_id: str, on: Optional[str] = None, horizon_d: int = 30):
    with app_db() as con:
        u = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not u:
        raise HTTPException(404, "No such user.")
    u = dict(u)
    if not u["entity_id"]:
        return {"status": "unresolved", "user": _public(u),
                "reason": f"{u['place_raw']!r} did not resolve to a known "
                          f"taluka, village or city. Use /api/places to pick one."}
    card = scoring.score_for(u["entity_type"], u["entity_id"], on, horizon_d)
    return {"user": _public(u), "card": card}


@app.get("/api/score")
def score_direct(entity_type: str, entity_id: str,
                 on: Optional[str] = None, horizon_d: int = 30):
    return scoring.score_for(entity_type, entity_id, on, horizon_d)


@app.get("/api/timeline")
def timeline(entity_id: str, limit: int = 400):
    """Storage / score series for the dashboard chart."""
    with pipeline_db() as con:
        rows = con.execute(
            "SELECT date, live_storage_pct, score, band, inputs_source "
            "FROM urban_stress WHERE entity_id=? ORDER BY date LIMIT ?",
            (entity_id, limit)).fetchall()
    return {"entity_id": entity_id, "points": [dict(r) for r in rows]}


# ---- alerts --------------------------------------------------------------
class AlertIn(BaseModel):
    user_id: str
    on: Optional[str] = None
    force: bool = False


@app.get("/api/alerts/templates")
def alert_templates():
    """Every string, for the native-reader review on the Phase 8 checklist."""
    return {"templates": alerts_mod.TEMPLATES,
            "alert_bands": sorted(alerts_mod.ALERT_BANDS),
            "review_status": "NOT yet checked by a native Marathi/Hindi reader"}


@app.post("/api/alerts/preview")
def preview_alert(body: AlertIn):
    u, card = _user_and_card(body.user_id, body.on)
    return {"band": card.get("band"),
            "would_send": alerts_mod.should_alert(card.get("band", "SAFE")),
            "lang": u["lang"],
            "body": alerts_mod.render(u, card),
            "all_languages": {lg: alerts_mod.render({**u, "lang": lg}, card)
                              for lg in ("mr", "hi", "en")}}


@app.post("/api/alerts/send")
def send_alert(body: AlertIn):
    u, card = _user_and_card(body.user_id, body.on)
    return alerts_mod.send(u, card, force=body.force)


@app.get("/api/alerts/log")
def alert_log(user_id: Optional[str] = None, limit: int = 50):
    with app_db() as con:
        if user_id:
            rows = con.execute("SELECT * FROM alert_log WHERE user_id=? "
                               "ORDER BY created_at DESC LIMIT ?",
                               (user_id, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM alert_log ORDER BY created_at "
                               "DESC LIMIT ?", (limit,)).fetchall()
    return {"alerts": [dict(r) for r in rows]}


# --------------------------------------------------------------------------
def _public(u: dict) -> dict:
    return {k: u[k] for k in ("user_id", "role", "name", "lang", "place_raw",
                              "entity_type", "entity_id", "entity_label",
                              "verified")}


def _user_and_card(user_id: str, on: Optional[str]):
    with app_db() as con:
        u = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not u:
        raise HTTPException(404, "No such user.")
    u = dict(u)
    if not u["entity_id"]:
        raise HTTPException(409, "This user's place has not been resolved yet.")
    card = scoring.score_for(u["entity_type"], u["entity_id"], on)
    if card.get("status") != "ok":
        raise HTTPException(409, card.get("reason", "No score available."))
    return u, card


# ---- static site ---------------------------------------------------------
if WEB.exists():
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
