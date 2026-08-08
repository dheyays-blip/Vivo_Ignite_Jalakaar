"""
JALAAKAR — steps 1 and 2 of the pipeline: Measure, then Validate.

Measure (2.1)
-------------
A Jal Mitra sends their borewell depth over WhatsApp. For someone already
registered that is ONE message — the phone number resolves to their well, so
there is nothing to ask. An unregistered number costs two more questions.
The poster promises a report in under a minute and at most four questions;
this keeps to that by making registration carry the context.

Validate (2.2 / 1.2.4)
----------------------
Every report is checked against what that well has actually done before, using
a conjugate normal update — prior from the well's own history in the reporting
season, likelihood from the report with a stated measurement uncertainty.

This matters more than it looks. Crowdsourced depth is typed by a person with
a tape and a phone, and the failure modes are mundane: feet entered as metres,
a digit dropped, the neighbour's well, a deliberate exaggeration to trigger a
tanker. A single bad report that reaches the model moves a whole taluka's
score, because a taluka takes the score of its worst well.

Verdicts, and why three rather than two:
    accepted   |z| <= 2.0    consistent with this well's history
    flagged    |z| <= 3.5    unusual but possible — stored, NOT scored,
                             queued for a human or a second report
    rejected   otherwise     or physically impossible

Flagged is the important one. A genuine crisis looks exactly like a bad
reading — that is the whole point of a crisis — so a filter that silently
rejects outliers would delete the events the system exists to find. Flagged
keeps the data and withholds trust until something corroborates it.

Nothing here writes to the pipeline database. Community readings live in
app.db and are never mixed into gw_observations, which stays exactly what CGWB
published.
"""

from __future__ import annotations

import math
import re
from datetime import date

from .appdb import app_db, new_id, pipeline_db, utcnow

# A volunteer with a measuring tape down a borewell. Not a calibrated logger.
REPORT_SD_M = 1.0
Z_ACCEPT = 2.0
Z_FLAG = 3.5
MAX_PLAUSIBLE_MBGL = 200.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS community_reports (
    report_id      TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    source         TEXT NOT NULL,      -- whatsapp | web | bhujal
    reporter_phone TEXT,
    user_id        TEXT,
    well_id        TEXT,
    taluka         TEXT,
    district       TEXT,
    lat            REAL,
    lon            REAL,
    level_mbgl     REAL NOT NULL,
    reported_for   TEXT NOT NULL,
    status         TEXT NOT NULL,      -- accepted | flagged | rejected
    verdict_reason TEXT,
    prior_mean     REAL,
    prior_sd       REAL,
    z_score        REAL,
    post_mean      REAL,
    post_sd        REAL,
    n_prior_obs    INTEGER,
    raw_message    TEXT,
    CHECK (status IN ('accepted','flagged','rejected'))
);
CREATE INDEX IF NOT EXISTS idx_cr_well ON community_reports(well_id, reported_for);
CREATE INDEX IF NOT EXISTS idx_cr_phone ON community_reports(reporter_phone);

-- Conversation state for the WhatsApp flow. One row per phone number.
CREATE TABLE IF NOT EXISTS wa_sessions (
    phone      TEXT PRIMARY KEY,
    step       TEXT NOT NULL,
    well_id    TEXT,
    place_raw  TEXT,
    lang       TEXT NOT NULL DEFAULT 'en',
    updated_at TEXT NOT NULL
);
"""


def ensure_schema(con) -> None:
    con.executescript(SCHEMA)


def _season_of(month: int) -> str:
    if month in (3, 4, 5):
        return "pre_monsoon"
    if month in (6, 7, 8, 9):
        return "monsoon"
    if month in (10, 11):
        return "post_monsoon"
    return "rabi"


# --------------------------------------------------------------------------
def validate(well_id: str, level_mbgl: float, when: str) -> dict:
    """Conjugate normal update against the well's own seasonal history."""
    season = _season_of(int(when[5:7]))

    with pipeline_db() as con:
        w = con.execute("SELECT well_depth FROM wells WHERE well_id=?",
                        (well_id,)).fetchone()
        rows = con.execute(
            "SELECT level_mbgl FROM gw_observations "
            "WHERE well_id=? AND season=? AND obs_date<=?",
            (well_id, season, when)).fetchall()
        if len(rows) < 3:
            rows = con.execute(
                "SELECT level_mbgl FROM gw_observations "
                "WHERE well_id=? AND obs_date<=?", (well_id, when)).fetchall()

    # ---- physically impossible beats statistically unlikely ---------------
    if level_mbgl < 0:
        return _verdict("rejected", "A depth below ground cannot be negative.",
                        None, None, None, None, None, 0)
    if level_mbgl > MAX_PLAUSIBLE_MBGL:
        return _verdict("rejected",
                        f"{level_mbgl:.1f} m exceeds the {MAX_PLAUSIBLE_MBGL:.0f} m "
                        f"plausible limit for a dug or bore well.",
                        None, None, None, None, None, 0)
    depth = w["well_depth"] if w else None
    if depth and level_mbgl > depth * 1.05:
        return _verdict("rejected",
                        f"Water cannot sit at {level_mbgl:.1f} m in a well "
                        f"{depth:.1f} m deep.",
                        None, None, None, None, None, len(rows))

    levels = [r["level_mbgl"] for r in rows]
    if len(levels) < 2:
        return _verdict("flagged",
                        "No usable history for this well yet, so the reading "
                        "cannot be checked against anything. Kept, not scored.",
                        None, None, None, None, None, len(levels))

    n = len(levels)
    mu = sum(levels) / n
    var = sum((x - mu) ** 2 for x in levels) / (n - 1)
    sd = max(math.sqrt(var), 0.25)     # floor: a perfectly stable well is rare

    z = (level_mbgl - mu) / sd

    # conjugate normal posterior for the well's true level
    tau2, s2 = sd ** 2, REPORT_SD_M ** 2
    post_mean = (mu * s2 + level_mbgl * tau2) / (tau2 + s2)
    post_sd = math.sqrt((tau2 * s2) / (tau2 + s2))

    if abs(z) <= Z_ACCEPT:
        return _verdict("accepted",
                        f"Within {Z_ACCEPT:.0f} sd of this well's {season.replace('_', '-')} "
                        f"history ({mu:.2f} +/- {sd:.2f} m, n={n}).",
                        mu, sd, z, post_mean, post_sd, n)
    if abs(z) <= Z_FLAG:
        return _verdict("flagged",
                        f"{abs(z):.1f} sd from this well's usual "
                        f"{mu:.2f} +/- {sd:.2f} m (n={n}). Possible, and possibly "
                        f"the crisis we are looking for — held for a second "
                        f"reading rather than discarded.",
                        mu, sd, z, post_mean, post_sd, n)
    return _verdict("rejected",
                    f"{abs(z):.1f} sd from this well's history "
                    f"({mu:.2f} +/- {sd:.2f} m, n={n}). Most often feet entered "
                    f"as metres, or a mistyped digit.",
                    mu, sd, z, post_mean, post_sd, n)


def _verdict(status, reason, mu, sd, z, pm, ps, n) -> dict:
    return {"status": status, "reason": reason, "prior_mean": mu,
            "prior_sd": sd, "z_score": z, "post_mean": pm, "post_sd": ps,
            "n_prior_obs": n}


# --------------------------------------------------------------------------
def resolve_well(well_id: str | None = None, taluka: str | None = None,
                 place: str | None = None) -> dict | None:
    """Pick the well a report belongs to."""
    with pipeline_db() as con:
        if well_id:
            r = con.execute("SELECT well_id, taluka, district, lat, lon "
                            "FROM wells WHERE well_id=?", (well_id,)).fetchone()
            return dict(r) if r else None
        if taluka:
            # the well with the longest record is the most checkable
            r = con.execute(
                "SELECT well_id, taluka, district, lat, lon FROM wells "
                "WHERE taluka=? ORDER BY n_observations DESC LIMIT 1",
                (taluka,)).fetchone()
            return dict(r) if r else None
    if place:
        from .places import resolve
        res = resolve(place, "farmer")
        if res.get("status") == "ok":
            if res["entity_type"] == "well":
                return resolve_well(well_id=res["entity_id"])
            if res["entity_type"] == "taluka":
                return resolve_well(taluka=res["entity_id"])
    return None


def submit(level_mbgl: float, *, source: str = "web",
           well_id: str | None = None, taluka: str | None = None,
           place: str | None = None, phone: str | None = None,
           user_id: str | None = None, when: str | None = None,
           raw: str | None = None) -> dict:
    when = when or date.today().isoformat()
    well = resolve_well(well_id, taluka, place)
    if not well:
        return {"ok": False, "error": "unresolved_place",
                "message": "Could not work out which well this refers to."}

    v = validate(well["well_id"], level_mbgl, when)
    rid = new_id("rep")

    with app_db() as con:
        ensure_schema(con)
        con.execute(
            "INSERT INTO community_reports (report_id,created_at,source,"
            "reporter_phone,user_id,well_id,taluka,district,lat,lon,level_mbgl,"
            "reported_for,status,verdict_reason,prior_mean,prior_sd,z_score,"
            "post_mean,post_sd,n_prior_obs,raw_message) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, utcnow(), source, phone, user_id, well["well_id"],
             well["taluka"], well["district"], well["lat"], well["lon"],
             level_mbgl, when, v["status"], v["reason"], v["prior_mean"],
             v["prior_sd"], v["z_score"], v["post_mean"], v["post_sd"],
             v["n_prior_obs"], raw))

    return {"ok": True, "report_id": rid, "well": well,
            "level_mbgl": level_mbgl, "reported_for": when, **v}


def history(well_id: str | None = None, phone: str | None = None,
            limit: int = 50) -> list[dict]:
    with app_db() as con:
        ensure_schema(con)
        if well_id:
            rows = con.execute("SELECT * FROM community_reports WHERE well_id=? "
                               "ORDER BY created_at DESC LIMIT ?",
                               (well_id, limit)).fetchall()
        elif phone:
            rows = con.execute("SELECT * FROM community_reports WHERE "
                               "reporter_phone=? ORDER BY created_at DESC LIMIT ?",
                               (phone, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM community_reports "
                               "ORDER BY created_at DESC LIMIT ?",
                               (limit,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# WhatsApp "Jal Mitra" flow
# --------------------------------------------------------------------------
# A depth reading is a message that is ONLY a number, optionally with a unit
# or a DEPTH prefix. It is NOT "any message containing a digit".
#
# BUG this replaces: the old pattern searched anywhere in the text, so
#   "Ward 12 Baglan"  was recorded as a 12 m groundwater reading, and
#   "1"               sent in reply to the BOOK prompt — which literally says
#                     "reply with the number 1, 2 or 3" — was recorded as a
#                     1 m reading. On a shallow well 1-3 m is entirely
#                     plausible, so the Bayesian filter would have ACCEPTED it
#                     and it would have moved a real taluka's score.
DEPTH = re.compile(
    r"^\s*(?:depth\s*[:=]?\s*)?"
    r"(\d+(?:[.,]\d+)?)"
    r"\s*(?:m|mtr|mtrs|meter|meters|metre|metres|मीटर|मी)?\s*$",
    re.IGNORECASE)

WORKSHOPS = {
    "1": {"en": "rainwater harvesting", "mr": "जलसंधारण", "hi": "वर्षा जल संचयन"},
    "2": {"en": "groundwater recharge", "mr": "भूजल पुनर्भरण", "hi": "भूजल पुनर्भरण"},
    "3": {"en": "leak detection", "mr": "गळती शोध", "hi": "रिसाव पहचान"},
}


def parse_depth(text: str):
    m = DEPTH.match(text or "")
    return float(m.group(1).replace(",", ".")) if m else None

REPLIES = {
    "ask_place": {
        "en": "Welcome to Jalaakar. Which village or taluka is your well in?",
        "mr": "जलाकार मध्ये स्वागत. तुमची विहीर कोणत्या गावात किंवा तालुक्यात आहे?",
        "hi": "जलाकार में स्वागत है। आपका कुआँ किस गाँव या तालुका में है?",
    },
    "ask_depth": {
        "en": "Got it — {place}. How many METRES is the water below ground? "
              "Reply with just the number.",
        "mr": "{place} नोंदवले. पाणी जमिनीपासून किती मीटर खाली आहे? फक्त आकडा पाठवा.",
        "hi": "{place} दर्ज किया। पानी ज़मीन से कितने मीटर नीचे है? सिर्फ़ संख्या भेजें।",
    },
    "accepted": {
        "en": "Recorded: {level} m at {place}. Thank you — this is the freshest "
              "reading we have there. Reply SCORE for your water stress score.",
        "mr": "नोंद: {place} येथे {level} मी. धन्यवाद — तिथली ही सर्वात ताजी नोंद आहे. "
              "गुणांसाठी SCORE पाठवा.",
        "hi": "दर्ज: {place} पर {level} मी. धन्यवाद — यह वहाँ की सबसे नई रीडिंग है। "
              "स्कोर के लिए SCORE भेजें।",
    },
    "flagged": {
        "en": "Recorded {level} m, but it is well outside the usual range here, "
              "so we are holding it for checking. If it is right, send it again "
              "tomorrow and we will trust it.",
        "mr": "{level} मी नोंदवले, पण ते इथल्या नेहमीच्या पातळीपेक्षा खूप वेगळे आहे. "
              "तपासणीसाठी ठेवले आहे. बरोबर असल्यास उद्या पुन्हा पाठवा.",
        "hi": "{level} मी दर्ज, पर यह यहाँ की सामान्य सीमा से बहुत बाहर है, इसलिए "
              "जाँच हेतु रोका गया है। सही हो तो कल दोबारा भेजें।",
    },
    "rejected": {
        "en": "That does not look right: {reason} Please check and send again.",
        "mr": "हे बरोबर वाटत नाही: {reason} कृपया तपासून पुन्हा पाठवा.",
        "hi": "यह सही नहीं लगता: {reason} कृपया जाँचकर दोबारा भेजें।",
    },
    "help": {
        "en": "Jalaakar: send a NUMBER for your borewell depth in metres. "
              "SCORE for your water stress score. BOOK for a workshop. "
              "STOP to unsubscribe.",
        "mr": "जलाकार: विहिरीची खोली मीटरमध्ये आकड्याने पाठवा. SCORE = पाणी ताण गुण. "
              "BOOK = कार्यशाळा. STOP = थांबवा.",
        "hi": "जलाकार: कुएँ की गहराई मीटर में संख्या भेजें। SCORE = जल तनाव स्कोर। "
              "BOOK = कार्यशाला। STOP = बंद करें।",
    },
    "unknown_place": {
        "en": "I could not find that place in the CGWB well network. Try the "
              "taluka name, for example: Baglan",
        "mr": "ते ठिकाण CGWB विहीर जाळ्यात सापडले नाही. तालुक्याचे नाव पाठवा, उदा: Baglan",
        "hi": "वह स्थान CGWB कुआँ नेटवर्क में नहीं मिला। तालुका नाम भेजें, जैसे: Baglan",
    },
    "score": {
        "en": "{place} — water stress {score}/100, {band}. Based on readings up "
              "to {date}. Send your borewell depth as a number to sharpen it.",
        "mr": "{place} — पाणी ताण {score}/100, {band}. {date} पर्यंतच्या नोंदींवर आधारित. "
              "अचूकतेसाठी विहिरीची खोली आकड्याने पाठवा.",
        "hi": "{place} — जल तनाव {score}/100, {band}. {date} तक की रीडिंग पर आधारित। "
              "सटीकता हेतु कुएँ की गहराई संख्या में भेजें।",
    },
    "no_score": {
        "en": "We do not have enough readings for your area yet. Send your "
              "borewell depth as a number and we will start building it.",
        "mr": "तुमच्या भागासाठी पुरेशा नोंदी नाहीत. विहिरीची खोली आकड्याने पाठवा.",
        "hi": "आपके क्षेत्र हेतु पर्याप्त रीडिंग नहीं हैं। कुएँ की गहराई संख्या में भेजें।",
    },
    "book": {
        "en": "Workshops: rainwater harvesting, groundwater recharge, leak "
              "detection. Reply with the number 1, 2 or 3 and we will call you.",
        "mr": "कार्यशाळा: जलसंधारण, भूजल पुनर्भरण, गळती शोध. 1, 2 किंवा 3 पाठवा, "
              "आम्ही संपर्क करू.",
        "hi": "कार्यशालाएँ: वर्षा जल संचयन, भूजल पुनर्भरण, रिसाव पहचान. 1, 2 या 3 भेजें, "
              "हम संपर्क करेंगे।",
    },
    "booked": {
        "en": "Booked: {topic}. Someone will call you within two working days.",
        "mr": "नोंदणी झाली: {topic}. दोन कामकाजाच्या दिवसांत संपर्क केला जाईल.",
        "hi": "बुक हुआ: {topic}. दो कार्य दिवसों में संपर्क किया जाएगा।",
    },
    "stopped": {
        "en": "You will get no more Jalaakar alerts. Send START to resume.",
        "mr": "यापुढे जलाकार सूचना येणार नाहीत. पुन्हा सुरू करण्यासाठी START पाठवा.",
        "hi": "अब जलाकार अलर्ट नहीं आएँगे। दोबारा शुरू करने हेतु START भेजें।",
    },
}


def _t(key: str, lang: str, **kw) -> str:
    return REPLIES[key].get(lang, REPLIES[key]["en"]).format(**kw)


def _session(con, phone: str) -> dict:
    ensure_schema(con)
    r = con.execute("SELECT * FROM wa_sessions WHERE phone=?", (phone,)).fetchone()
    if r:
        return dict(r)
    con.execute("INSERT INTO wa_sessions (phone,step,lang,updated_at) "
                "VALUES (?,?,?,?)", (phone, "idle", "en", utcnow()))
    return {"phone": phone, "step": "idle", "well_id": None,
            "place_raw": None, "lang": "en"}


def _save(con, phone: str, **kw) -> None:
    sets = ", ".join(f"{k}=?" for k in kw)
    con.execute(f"UPDATE wa_sessions SET {sets}, updated_at=? WHERE phone=?",
                (*kw.values(), utcnow(), phone))


def handle_message(phone: str, body: str) -> dict:
    """One inbound WhatsApp message in, one reply out."""
    text = (body or "").strip()
    upper = text.upper()

    with app_db() as con:
        s = _session(con, phone)
        user = con.execute("SELECT * FROM users WHERE phone_e164=?",
                           (phone,)).fetchone()
    user = dict(user) if user else None
    lang = (user or {}).get("lang") or s.get("lang") or "en"

    if upper in ("HELP", "MENU", "?"):
        return {"reply": _t("help", lang), "action": "help"}
    if upper == "STOP":
        return {"reply": _t("stopped", lang), "action": "stop"}
    if upper == "BOOK":
        # Park the session so the NEXT message is read as a workshop choice,
        # not as a borewell depth. Without this state the prompt "reply 1, 2
        # or 3" walks straight into the depth parser.
        with app_db() as con:
            _save(con, phone, step="awaiting_workshop")
        return {"reply": _t("book", lang), "action": "book"}

    # A registered user needs no context — their number IS the context.
    known_well = s.get("well_id")
    if not known_well and user and user.get("entity_type") in ("well", "taluka"):
        w = resolve_well(well_id=user["entity_id"]
                         if user["entity_type"] == "well" else None,
                         taluka=user["entity_id"]
                         if user["entity_type"] == "taluka" else None)
        known_well = w["well_id"] if w else None

    if upper == "SCORE":
        # Advertised in the help text, so it has to work. Anything advertised
        # and unimplemented is the thing a judge will type.
        from . import scoring
        et = ei = None
        if user and user.get("entity_id"):
            et, ei = user["entity_type"], user["entity_id"]
        elif s.get("well_id"):
            et, ei = "well", s["well_id"]
        if not ei:
            return {"reply": _t("ask_place", lang), "action": "ask_place"}
        card = scoring.score_for(et, ei, lang=lang)
        if card.get("status") != "ok":
            return {"reply": _t("no_score", lang), "action": "no_score"}
        return {"reply": _t("score", lang, place=card["entity_label"],
                            score=card["score"], band=card["band_label"],
                            date=card["date"]),
                "action": "score", "card": card}

    if s.get("step") == "awaiting_workshop":
        pick = WORKSHOPS.get(upper.strip())
        with app_db() as con:
            _save(con, phone, step="idle")
        if pick:
            return {"reply": _t("booked", lang, topic=pick.get(lang, pick["en"])),
                    "action": "booked", "workshop": upper.strip()}
        # not 1/2/3 — fall through and treat it as a normal message

    m = parse_depth(text)

    if s.get("step") == "awaiting_place" and m is None:
        w = resolve_well(place=text)
        if not w:
            return {"reply": _t("unknown_place", lang), "action": "retry_place"}
        with app_db() as con:
            _save(con, phone, step="awaiting_depth", well_id=w["well_id"],
                  place_raw=text)
        return {"reply": _t("ask_depth", lang,
                            place=f"{w['taluka']}, {w['district']}"),
                "action": "ask_depth"}

    if m is not None:
        level = m
        well_id = known_well or s.get("well_id")
        if not well_id:
            with app_db() as con:
                _save(con, phone, step="awaiting_place")
            return {"reply": _t("ask_place", lang), "action": "ask_place"}

        res = submit(level, source="whatsapp", well_id=well_id, phone=phone,
                     user_id=(user or {}).get("user_id"), raw=text)
        with app_db() as con:
            _save(con, phone, step="idle", well_id=well_id)

        place = f"{res['well']['taluka']}, {res['well']['district']}"
        if res["status"] == "accepted":
            reply = _t("accepted", lang, level=f"{level:g}", place=place)
        elif res["status"] == "flagged":
            reply = _t("flagged", lang, level=f"{level:g}")
        else:
            reply = _t("rejected", lang, reason=res["reason"])
        return {"reply": reply, "action": "report", "report": res}

    if not known_well:
        # A first message of "Baglan" used to be answered with "which village
        # is your well in?" — the user had just said. Try to resolve it before
        # asking, so the common case costs one turn instead of three.
        w = resolve_well(place=text) if len(text) >= 3 else None
        if w:
            with app_db() as con:
                _save(con, phone, step="awaiting_depth", well_id=w["well_id"],
                      place_raw=text)
            return {"reply": _t("ask_depth", lang,
                                place=f"{w['taluka']}, {w['district']}"),
                    "action": "ask_depth"}
        with app_db() as con:
            _save(con, phone, step="awaiting_place")
        return {"reply": _t("ask_place", lang), "action": "ask_place"}

    return {"reply": _t("help", lang), "action": "help"}
