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
from datetime import date as _date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import alerts as alerts_mod
from . import auth
from . import community
from . import figures as figures_mod
from . import places as places_mod
from . import scoring
from .appdb import (app_db, hash_password, new_id, normalise_phone,
                    pipeline_db, utcnow)

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
    password: str = Field(min_length=8)
    lang: Literal["mr", "hi", "en"] = "mr"


def _valid_date(s: Optional[str], field: str = "on") -> Optional[str]:
    """Reject a malformed date at the edge, not three frames deep.

    BUG: `?on=2023-02-30` returned HTTP 500. The guard in rural_score compares
    dates as STRINGS, so an impossible date that sorts before the last
    observation slipped past it and reached date.fromisoformat(), which raised
    ValueError into an unhandled 500. Anyone typing a date into the URL bar
    could produce a stack trace.
    """
    if s is None or s == "":
        return None
    try:
        return _date.fromisoformat(s).isoformat()
    except ValueError:
        raise HTTPException(
            422, f"{field}={s!r} is not a valid date. Use YYYY-MM-DD.") from None


def _valid_horizon(h: int) -> int:
    """BUG: horizon_d=-30 produced a 'forecast' with a target date in the past,
    and horizon_d=0 forecast the present. Both scored happily."""
    if h < 1 or h > 365:
        raise HTTPException(
            422, f"horizon_d must be between 1 and 365 days, got {h}.")
    return h


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
def get_places(q: str = Query(min_length=2),
               limit: int = Query(10, ge=1, le=100)):
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
        try:
            pw = hash_password(body.password)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        con.execute(
            "INSERT INTO users (user_id,role,name,phone_e164,pw_hash,lang,"
            "place_raw,entity_type,entity_id,entity_label,verified,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, body.role, body.name.strip(), phone, pw, body.lang,
             body.place.strip(), entity_type, entity_id, label,
             0 if body.role == "government" else 1, utcnow()))

    card = None
    if entity_id:
        # 4.5 — the very first card a user sees must already be in the
        # language they just chose, not English with a language label on it.
        card = scoring.score_for(entity_type, entity_id, lang=body.lang)

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
def score_for_user(user_id: str, on: Optional[str] = None, horizon_d: int = 30,
                   lang: Optional[str] = None):
    with app_db() as con:
        u = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not u:
        raise HTTPException(404, "No such user.")
    u = dict(u)
    if not u["entity_id"]:
        return {"status": "unresolved", "user": _public(u),
                "reason": f"{u['place_raw']!r} did not resolve to a known "
                          f"taluka, village or city. Use /api/places to pick one."}
    # 4.5 — default to the language the user chose at signup.
    card = scoring.score_for(u["entity_type"], u["entity_id"],
                             _valid_date(on), _valid_horizon(horizon_d),
                             lang or u["lang"])
    return {"user": _public(u), "card": card}


@app.get("/api/score")
def score_direct(entity_type: str, entity_id: str,
                 on: Optional[str] = None, horizon_d: int = 30,
                 lang: str = "en"):
    return scoring.score_for(entity_type, entity_id, _valid_date(on),
                             _valid_horizon(horizon_d), lang)


@app.get("/api/timeline")
def timeline(entity_id: str, entity_type: str = "reservoir",
             limit: int = Query(400, ge=1, le=2000), lang: str = "en"):
    """Score history — 4.8.

    Urban reads the precomputed series. Rural is scored on demand at each of
    that entity's REAL observation dates, because those are the only dates a
    rural score can honestly exist for; interpolating a score history between
    quarterly readings would draw a smooth line through nothing.
    """
    if entity_type == "reservoir":
        with pipeline_db() as con:
            rows = con.execute(
                "SELECT date, live_storage_pct, score, band, inputs_source "
                "FROM urban_stress WHERE entity_id=? ORDER BY date LIMIT ?",
                (entity_id, limit)).fetchall()
        return {"entity_id": entity_id, "track": "urban",
                "points": [dict(r) for r in rows]}

    wells = scoring._wells_for(entity_type, entity_id)
    if not wells:
        raise HTTPException(404, f"No wells for {entity_type} {entity_id}")
    ph = ",".join("?" * len(wells))
    with pipeline_db() as con:
        dates = [r["d"] for r in con.execute(
            f"SELECT DISTINCT obs_date d FROM gw_observations "
            f"WHERE well_id IN ({ph}) ORDER BY obs_date DESC LIMIT ?",
            wells + [limit]).fetchall()]

    pts = []
    for d in sorted(dates):
        c = scoring.rural_score(entity_type, entity_id, d, lang=lang)
        if c.get("status") == "ok":
            pts.append({"date": d, "score": c["score"], "band": c["band"],
                        "colour": c["colour"],
                        "forecast_level": c["headline"]["value"],
                        "days_to_crisis": c["days_to_crisis"]})
    return {"entity_id": entity_id, "track": "rural", "points": pts,
            "note": "one point per real CGWB observation date; CGWB measures "
                    "roughly four times a year"}


# ---- alerts --------------------------------------------------------------
class AlertIn(BaseModel):
    user_id: str
    on: Optional[str] = None
    force: bool = False


# ---- community reports: Measure (2.1) + Validate (2.2) --------------------
class ReportIn(BaseModel):
    level_mbgl: float = Field(ge=0, le=300)
    well_id: Optional[str] = None
    taluka: Optional[str] = None
    place: Optional[str] = None
    phone: Optional[str] = None
    user_id: Optional[str] = None
    reported_for: Optional[str] = None


@app.post("/api/reports", status_code=201)
def submit_report(body: ReportIn):
    """A Jal Mitra borewell reading. Validated before it is trusted."""
    res = community.submit(
        body.level_mbgl, source="web", well_id=body.well_id,
        taluka=body.taluka, place=body.place,
        phone=(normalise_phone(body.phone) if body.phone else None),
        user_id=body.user_id,
        when=_valid_date(body.reported_for, "reported_for"))
    if not res.get("ok"):
        raise HTTPException(422, res.get("message", "Could not resolve place."))
    return res


@app.get("/api/reports")
def list_reports(well_id: Optional[str] = None, phone: Optional[str] = None,
                 limit: int = Query(50, ge=1, le=500)):
    return {"reports": community.history(well_id, phone, limit)}


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """Twilio inbound. Returns TwiML so the reply goes straight back.

    Twilio posts application/x-www-form-urlencoded with From and Body.
    Kept dependency-free and synchronous: one message in, one reply out, no
    queue to go wrong live on stage.
    """
    # Parsed by hand rather than via request.form(), which asserts on
    # python-multipart being installed. One fewer package to be missing on
    # demo day, and Twilio's payload is plain urlencoded anyway. JSON is
    # accepted too so the endpoint can be driven from curl or Postman.
    raw = (await request.body()).decode("utf-8", "replace")
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        import json as _json
        try:
            data = _json.loads(raw or "{}")
        except ValueError:
            data = {}
    else:
        from urllib.parse import parse_qs
        data = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    frm = str(data.get("From") or data.get("from") or "")
    body = str(data.get("Body") or data.get("body") or "")
    phone = frm.replace("whatsapp:", "").strip()
    if not phone:
        raise HTTPException(422, "No From on the inbound message.")

    out = community.handle_message(phone, body)
    reply = (out["reply"].replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;"))
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?>'
                f"<Response><Message>{reply}</Message></Response>",
        media_type="application/xml")


@app.post("/api/whatsapp/simulate")
def whatsapp_simulate(phone: str, body: str):
    """The same flow without Twilio, so the demo works offline."""
    return community.handle_message(normalise_phone(phone), body)


# ---- ad-hoc alerts, for the live demo ------------------------------------
# The demo scores a place the visitor picked; there is no account behind it.
# These accept an entity directly so the page can show the exact message the
# system would send, in all three languages, without creating a user first.
class DemoAlertIn(BaseModel):
    entity_type: Literal["taluka", "well", "reservoir"]
    entity_id: str
    on: Optional[str] = None
    lang: Literal["mr", "hi", "en"] = "mr"
    role: Literal["farmer", "society-manager", "society-resident"] = "farmer"
    name: str = "Jal Mitra"
    phone: Optional[str] = None
    force: bool = False


def _adhoc(body: DemoAlertIn) -> tuple[dict, dict]:
    card = scoring.score_for(body.entity_type, body.entity_id,
                             _valid_date(body.on), lang=body.lang)
    if card.get("status") != "ok":
        raise HTTPException(409, card.get("reason", "No score available."))
    user = {"user_id": None, "role": body.role, "name": body.name,
            "lang": body.lang, "phone_e164": None,
            "place_raw": body.entity_id,
            "entity_label": card.get("entity_label", body.entity_id)}
    return user, card


@app.post("/api/alerts/render")
def render_alert(body: DemoAlertIn):
    """Exactly what would be sent, in all three languages. Writes nothing."""
    user, card = _adhoc(body)
    return {
        "score": card["score"], "band": card["band"],
        "band_label": card["band_label"], "colour": card["colour"],
        "entity_label": card["entity_label"], "date": card["date"],
        "days_to_crisis": card.get("days_to_crisis"),
        "would_send": alerts_mod.should_alert(card["band"]),
        "why_not": (None if alerts_mod.should_alert(card["band"]) else
                    f"{card['band']} does not warrant an alert. A system that "
                    f"only ever sends warnings is not a forecaster."),
        "lang": body.lang,
        "messages": {lg: alerts_mod.render({**user, "lang": lg}, card)
                     for lg in ("mr", "hi", "en")},
    }


# ---- auth ----------------------------------------------------------------
class LoginIn(BaseModel):
    phone: str
    password: str


def _bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def _user(request: Request) -> dict:
    """Authentication only — any signed-in account."""
    u = auth.resolve(_bearer(request))
    if not u:
        raise HTTPException(401, "Sign in to continue.")
    return u


def _sender(request: Request) -> dict:
    """Authorisation — signed in AND allowed to send.

    Kept separate from _user so a farmer can sign in and see their own score
    without being able to broadcast. 401 means "who are you", 403 means "not
    you"; conflating them makes both confusing to debug.
    """
    u = _user(request)
    if not auth.can_send(u):
        raise HTTPException(
            403, "Only government officials and verified housing society "
                 "managers can send alerts. This account is registered as a "
                 f"{u['role'].replace('-', ' ')}."
                 + ("" if u["verified"] else
                    " It is also awaiting department verification."))
    return u


@app.post("/api/auth/login")
def login(body: LoginIn):
    try:
        phone = normalise_phone(body.phone)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    res = auth.login(phone, body.password)
    if not res["ok"]:
        raise HTTPException(401, res["reason"])
    u = res["user"]
    res["audience_size"] = (len(auth.audience(u)) if u["can_send"] else 0)
    return res


@app.get("/api/auth/me")
def whoami(request: Request):
    u = _user(request)
    pub = auth._public(u)
    card = None
    if u.get("entity_id"):
        card = scoring.score_for(u["entity_type"], u["entity_id"], lang=u["lang"])
    return {"user": pub,
            "audience_size": len(auth.audience(u)) if pub["can_send"] else 0,
            "score": card}


@app.post("/api/auth/logout")
def logout(request: Request):
    t = _bearer(request)
    if t:
        auth.logout(t)
    return {"ok": True}


@app.post("/api/alerts/broadcast")
def broadcast(request: Request, body: DemoAlertIn = None, force: bool = False):
    """Send every subscriber the alert for THEIR OWN place, in THEIR language.

    Not one message copy-pasted. A farmer in Baglan and a society in Kothrud
    have different water, so they get different scores — sending one text to
    both would be warning people about somebody else's reservoir.

    Recipients whose own score is SAFE are skipped unless force is set, which
    is the same gate the scheduled path uses.
    """
    sender = _sender(request)
    people = auth.audience(sender)

    sent, skipped, failed = [], [], []
    for u in people:
        card = scoring.score_for(u["entity_type"], u["entity_id"],
                                 lang=u["lang"])
        if card.get("status") != "ok":
            skipped.append({"user_id": u["user_id"],
                            "entity": u["entity_label"],
                            "reason": card.get("reason", "no score")[:90]})
            continue
        if not alerts_mod.should_alert(card["band"]) and not force:
            skipped.append({"user_id": u["user_id"],
                            "entity": u["entity_label"],
                            "score": card["score"], "band": card["band"],
                            "reason": f"{card['band']} — no alert warranted"})
            continue
        out = alerts_mod.send(u, card, force=force)
        rec = {"user_id": u["user_id"], "entity": u["entity_label"],
               "lang": u["lang"], "score": card["score"], "band": card["band"],
               "status": out["status"], "channel": out["channel"]}
        (sent if out["status"] in ("sent", "rendered") else failed).append(rec)

    delivered = sum(1 for r in sent if r["channel"] == "whatsapp")
    return {
        "sender": {"name": sender["name"], "role": sender["role"],
                   "entity_label": sender["entity_label"]},
        "audience": len(people),
        "sent": len(sent), "delivered": delivered,
        "rendered_only": len(sent) - delivered,
        "skipped": len(skipped), "failed": len(failed),
        "detail": {"sent": sent, "skipped": skipped, "failed": failed},
        "note": (None if delivered == len(sent) else
                 "Messages with channel 'console' were rendered and logged, "
                 "not delivered — WhatsApp credentials are not configured."),
    }


@app.post("/api/alerts/send-demo")
def send_demo_alert(body: DemoAlertIn, request: Request):
    """Send to one phone. Requires a signed-in official or society manager.

    The number is stored, because a delivery log with no recipient is not a
    log. If it is already registered we reuse that account rather than
    silently creating a second one for the same person.
    """
    sender = _sender(request)
    if not body.phone:
        raise HTTPException(422, "A phone number is required to send.")
    try:
        phone = normalise_phone(body.phone)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    user, card = _adhoc(body)

    with app_db() as con:
        row = con.execute("SELECT * FROM users WHERE phone_e164=?",
                          (phone,)).fetchone()
        if row:
            user = {**dict(row), "lang": body.lang,
                    "entity_label": card["entity_label"]}
        else:
            uid = new_id("usr")
            con.execute(
                "INSERT INTO users (user_id,role,name,phone_e164,lang,place_raw,"
                "entity_type,entity_id,entity_label,verified,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (uid, body.role, body.name.strip() or "Jal Mitra", phone,
                 body.lang, body.entity_id, body.entity_type, body.entity_id,
                 card["entity_label"], 1, utcnow()))
            user = {**user, "user_id": uid, "phone_e164": phone}

    out = alerts_mod.send(user, card, force=body.force)
    out["to"] = phone
    out["band"] = card["band"]
    out["score"] = card["score"]
    out["sent_by"] = {"name": sender["name"], "role": sender["role"]}
    return out


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
def alert_log(user_id: Optional[str] = None,
              limit: int = Query(50, ge=1, le=500)):
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
    card = scoring.score_for(u["entity_type"], u["entity_id"], _valid_date(on))
    if card.get("status") != "ok":
        raise HTTPException(409, card.get("reason", "No score available."))
    return u, card


# ---- static site ---------------------------------------------------------
if WEB.exists():
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
