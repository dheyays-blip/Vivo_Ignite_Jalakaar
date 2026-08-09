#!/usr/bin/env python3
"""
JALAAKAR — API smoke test. 23 assertions, no pytest, no network.

    python api/test_smoke.py

Writes to a throwaway app database under /tmp, so it never touches
data/app.db and never sends a real WhatsApp message. It reads the real
data/jalaakar.db, so it fails honestly if the pipeline has not been run.

What it is actually guarding
----------------------------
Most of these are ordinary endpoint checks. Four are guarding specific bugs
that were live in this repo and would be easy to reintroduce:

  * `signup 91-prefix phone` — 9123456780 is a valid Indian mobile. Stripping
    a leading "91" as a country code mangles it to 8 digits. Both this file
    and web/script.js must strip by length, not by prefix.
  * `rural refuses 2026` — CGWB observations end 2023-08-15. Asking for a
    score today must return no_data with a reason, never an extrapolation.
  * `6.93 is 29 Jun` / `30 Jun is 6.75` — the figure was mis-dated on the
    landing page for days.
  * `53.38 retracted` — a number that never had a source outside our own
    poster must stay deleted.
"""

from __future__ import annotations

import contextlib
import pathlib
import sqlite3
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import appdb  # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="jalaakar-smoke-")) / "app.db"
appdb.APP_DB = TMP


@contextlib.contextmanager
def _app_db():
    con = sqlite3.connect(appdb.APP_DB)
    con.row_factory = sqlite3.Row
    con.executescript(appdb.SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


appdb.app_db = _app_db

import api.alerts as alerts_mod   # noqa: E402
import api.main as main_mod       # noqa: E402

main_mod.app_db = _app_db
alerts_mod.app_db = _app_db

try:
    from fastapi.testclient import TestClient  # noqa: E402
except RuntimeError as e:                       # starlette needs an HTTP client
    sys.exit(f"{e}\n\nThis is a test-only dependency. The server itself runs "
             f"without it:\n    uvicorn api.main:app --port 8000")

c = TestClient(main_mod.app)
checks: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    checks.append((name, bool(cond)))


def run() -> int:
    h = c.get("/api/health").json()
    check("health", h["ok"] and h["wells"] == 940)

    r = c.post("/api/signup", json={"role": "farmer", "name": "Ramesh Patil",
                                    "phone": "9123456780",
                                    "place": "Baglan Taluka, Nashik", "lang": "mr",
                                    "password": "demo-pass-123"})
    d = r.json()
    uid = d.get("user_id")
    check("signup 91-prefix phone", r.status_code == 201 and d["entity"]["id"] == "Baglan")

    check("dup phone 409", c.post("/api/signup", json={
        "role": "farmer", "name": "Suresh Kale", "phone": "9123456780",
        "place": "Baglan", "lang": "en", "password": "demo-pass-123"}).status_code == 409)
    check("bad phone 422", c.post("/api/signup", json={
        "role": "farmer", "name": "Ok Name", "phone": "12345",
        "place": "Baglan", "lang": "en", "password": "demo-pass-123"}).status_code == 422)

    g = c.post("/api/signup", json={"role": "government", "name": "Dept Officer",
                                    "phone": "9876500011",
                                    "place": "GSDA, Nashik Division",
                                    "lang": "en", "password": "demo-pass-123"}).json()
    check("govt needs verification", g["requires_verification"] is True)

    card = c.get(f"/api/score/{uid}?on=2023-05-15").json()["card"]
    # Deliberately not pinning the exact score: it legitimately changes when
    # the XGBoost model is present versus the climatology fallback. What must
    # ALWAYS hold is that the band matches the cutoffs the response declares —
    # a band that disagrees with its own score is a bug either way.
    b = card.get("bands", {})
    expect = ("ACT NOW" if card["score"] > b.get("act_now_above", 70)
              else "MONITOR" if card["score"] > b.get("monitor_above", 40)
              else "SAFE")
    check("rural score band matches cutoffs", card["band"] == expect)
    check("rural score is Baglan and stressed",
          card["entity_label"].startswith("Baglan") and card["score"] >= 50)
    check("method names the forecaster",
          card["method"] in ("rural-stress-1.0/climatology",
                             "rural-stress-1.1/xgboost"))
    check("rural refuses 2026", c.get(
        "/api/score?entity_type=taluka&entity_id=Dindori&on=2026-08-07"
    ).json()["status"] == "no_data")

    u = c.get("/api/score?entity_type=reservoir&entity_id=MUM_ALL&on=2026-06-29").json()
    check("urban 29 Jun = 90 ACT NOW", u["score"] == 90 and u["band"] == "ACT NOW")
    check("urban today SAFE", c.get(
        "/api/score?entity_type=reservoir&entity_id=MUM_ALL").json()["band"] == "SAFE")

    p = c.post("/api/alerts/preview", json={"user_id": uid, "on": "2023-05-15"}).json()
    check("preview 3 languages",
          set(p["all_languages"]) == {"mr", "hi", "en"} and p["would_send"])

    s = c.post("/api/alerts/send", json={"user_id": uid, "on": "2023-05-15"}).json()
    check("send logs as rendered",
          s["status"] == "rendered" and s["channel"] == "console")
    check("alert log", len(c.get("/api/alerts/log").json()["alerts"]) == 1)

    soc = c.post("/api/signup", json={"role": "society-manager", "name": "Asha Rao",
                                      "phone": "9876543210",
                                      "place": "Shivneri CHS, Kothrud, Pune",
                                      "lang": "en", "password": "demo-pass-123"}).json()
    check("society -> PUN_KHW", soc["entity"]["id"] == "PUN_KHW")
    check("SAFE sends nothing", c.post(
        "/api/alerts/preview", json={"user_id": soc["user_id"]}
    ).json()["would_send"] is False)

    f = c.get("/api/figures").json()
    check("figures 18 anchors", f["summary"]["total_anchors"] == 18)
    check("6.93 is 29 Jun", f["figures"]["mumbai7Lakes_29Jun2026"]["value"] == 6.93)
    check("30 Jun is 6.75", f["figures"]["mumbai7Lakes_30Jun2026"]["value"] == 6.75)
    check("53.38 retracted",
          any("53.38" in str(x["value"]) for x in f["retracted"]))

    # ---- 4.5 language tag ------------------------------------------------
    mr = c.get("/api/score?entity_type=taluka&entity_id=Baglan"
               "&on=2023-05-15&lang=mr").json()
    check("score card carries language",
          mr["lang"] == "mr" and mr["lang_name"] == "MARATHI"
          and mr["band_label"] != mr["band"])
    check("signup card uses chosen language",
          (c.post("/api/signup", json={
              "role": "farmer", "name": "Lang Test", "phone": "9800000011",
              "place": "Baglan", "lang": "mr", "password": "demo-pass-123"}).json()
           .get("score") or {}).get("lang_name") == "MARATHI")

    # ---- 4.8 rural history ----------------------------------------------
    tl = c.get("/api/timeline?entity_type=taluka&entity_id=Baglan&limit=8").json()
    check("rural score history", tl["track"] == "rural" and len(tl["points"]) > 1)

    # ---- 2.1 Measure -----------------------------------------------------
    wa = "/api/whatsapp/simulate?phone=9876500123&body="
    check("wa asks for place when unknown",
          c.post(wa + "hi").json()["action"] == "ask_place")
    check("wa resolves a taluka",
          c.post(wa + "Baglan").json()["action"] == "ask_depth")
    rep = c.post(wa + "17.4").json()
    check("wa records a reading",
          rep["action"] == "report" and rep["report"]["status"] == "accepted")
    check("wa SCORE works", c.post(wa + "SCORE").json()["action"] == "score")
    check("wa BOOK works", c.post(wa + "BOOK").json()["action"] == "book")

    tw = c.post("/api/whatsapp/webhook",
                content="From=whatsapp%3A%2B919876500999&Body=HELP",
                headers={"Content-Type": "application/x-www-form-urlencoded"})
    check("twilio webhook returns TwiML",
          tw.status_code == 200 and "<Message>" in tw.text)

    # ---- 2.2 Validate ----------------------------------------------------
    deep = c.post(wa + "450").json()
    check("validator rejects the impossible",
          deep["report"]["status"] == "rejected")
    check("report log records the verdict",
          len(c.get("/api/reports").json()["reports"]) >= 2)

    # ---- regressions: bugs found in the adversarial pass, 8 Aug -----------
    # Each of these was a live defect. Left as named tests so a refactor that
    # reintroduces one fails loudly instead of quietly.

    # was HTTP 500: an impossible date sorts before last_obs as a STRING, so
    # the guard let it through to date.fromisoformat()
    check("invalid date -> 422 not 500", all(
        c.get(f"/api/score?entity_type=taluka&entity_id=Baglan&on={d}"
              ).status_code == 422
        for d in ("2023-02-30", "2023-00-01", "not-a-date", "2022-99-01")))

    # was HTTP 200: negative horizon produced a target date in the past
    check("bad horizon -> 422", all(
        c.get(f"/api/score?entity_type=taluka&entity_id=Baglan"
              f"&on=2023-05-15&horizon_d={h}").status_code == 422
        for h in (0, -30, 999999)))
    check("valid horizon still 200",
          c.get("/api/score?entity_type=taluka&entity_id=Baglan"
                "&on=2023-05-15&horizon_d=30").status_code == 200)

    c.post("/api/signup", json={"role": "farmer", "name": "Regression Farmer",
                                "phone": "9811111111", "place": "Baglan",
                                "lang": "en", "password": "demo-pass-123"})
    wr = "/api/whatsapp/simulate?phone=9811111111&body="

    # was: the BOOK prompt says "reply 1, 2 or 3" and that reply was stored
    # as a 1 m groundwater reading
    c.post(wr + "BOOK")
    pick = c.post(wr + "1").json()
    check("BOOK reply is not a depth reading",
          pick["action"] == "booked" and "report" not in pick)

    # was: any message containing a digit became a reading
    ward = c.post(wr + "Ward%2012%20Baglan").json()
    check("place with digits is not a depth reading", "report" not in ward)

    good = c.post(wr + "17.4").json()
    check("a bare number is still a reading",
          good.get("report", {}).get("level_mbgl") == 17.4)

    # was: first message of a village name replied "which village?"
    check("village as first message resolves",
          c.post("/api/whatsapp/simulate?phone=9844444444&body=Baglan"
                 ).json()["action"] == "ask_depth")

    # was: unknown lang returned the raw enum "ACT NOW" instead of a label
    check("unknown lang falls back to English label",
          c.get("/api/score?entity_type=taluka&entity_id=Baglan"
                "&on=2023-05-15&lang=zz").json()["band_label"] == "Act now")

    check("limit bounds enforced", all(
        c.get(f"/api/timeline?entity_id=MUM_ALL&limit={n}").status_code == 422
        for n in (0, -5, 100000)))

    # parameterised SQL — these must be treated as ordinary strings
    inj = c.get("/api/score", params={"entity_type": "taluka",
                                      "entity_id": "'; DROP TABLE wells;--"})
    check("sql injection is inert",
          inj.status_code == 200
          and c.get("/api/health").json()["wells"] == 940)

    # was: demo.html hardcoded Mumbai dates and applied them to all three
    # supply systems, so 4 of 12 urban combinations returned no_data and the
    # demo showed an error card. The dropdown is now built from each entity's
    # own series; this asserts every option it can produce actually scores.
    urban_ok = True
    for ent in ("MUM_ALL", "PUN_KHW", "PUN_ALL"):
        pts = c.get(f"/api/timeline?entity_id={ent}").json()["points"]
        if not pts:
            urban_ok = False
            break
        worst = max(pts, key=lambda p: p["score"])
        best = min(pts, key=lambda p: p["score"])
        dates = {p["date"] for p in (worst, best, pts[0], pts[-1])}
        if c.get(f"/api/score?entity_type=reservoir&entity_id={ent}"
                 ).json().get("status") != "ok":
            urban_ok = False
        for d in dates:
            if c.get(f"/api/score?entity_type=reservoir&entity_id={ent}&on={d}"
                     ).json().get("status") != "ok":
                urban_ok = False
    check("every urban dropdown option scores", urban_ok)

    # ---- auth + broadcast -------------------------------------------------
    c.post("/api/signup", json={"role": "government", "name": "GSDA Officer",
                                "phone": "9800000001",
                                "place": "GSDA, Nashik Division", "lang": "en", "password": "demo-pass-123"})
    c.post("/api/signup", json={"role": "society-manager", "name": "Asha Rao",
                                "phone": "9800000002",
                                "place": "Shivneri CHS, Kothrud, Pune",
                                "lang": "en", "password": "demo-pass-123"})
    c.post("/api/signup", json={"role": "farmer", "name": "Sita More",
                                "phone": "9800000004", "place": "Jat",
                                "lang": "hi", "password": "demo-pass-123"})

    farmer = c.post("/api/auth/login",
                    json={"phone": "9800000004", "password": "demo-pass-123"})
    check("farmer CAN sign in", farmer.status_code == 200)
    check("farmer cannot send", farmer.json()["user"]["can_send"] is False)
    fhdr = {"Authorization": f"Bearer {farmer.json()['token']}"}
    check("farmer broadcast -> 403", c.post(
        "/api/alerts/broadcast", headers=fhdr,
        json={"entity_type": "taluka", "entity_id": "Baglan"}).status_code == 403)

    unv = c.post("/api/auth/login",
                 json={"phone": "9800000001", "password": "demo-pass-123"})
    check("unverified govt signs in but cannot send",
          unv.status_code == 200 and unv.json()["user"]["can_send"] is False)

    check("wrong password rejected", c.post(
        "/api/auth/login",
        json={"phone": "9800000004", "password": "wrong"}).status_code == 401)
    check("unknown number gives the SAME error as a wrong password",
          c.post("/api/auth/login",
                 json={"phone": "9999999999", "password": "x" * 9}
                 ).json()["detail"] ==
          c.post("/api/auth/login",
                 json={"phone": "9800000004", "password": "wrong"}
                 ).json()["detail"])
    check("short password rejected at signup", c.post(
        "/api/signup", json={"role": "farmer", "name": "Short Pw",
                             "phone": "9700000001", "place": "Baglan",
                             "lang": "en", "password": "abc"}).status_code == 422)
    check("broadcast needs a token", c.post(
        "/api/alerts/broadcast",
        json={"entity_type": "taluka", "entity_id": "Baglan"}).status_code == 401)
    check("single send needs a token", c.post(
        "/api/alerts/send-demo",
        json={"entity_type": "taluka", "entity_id": "Baglan",
              "phone": "9800000009"}).status_code == 401)

    with _app_db() as con:
        con.execute("UPDATE users SET verified=1 WHERE phone_e164=?",
                    ("+919800000001",))
    lg = c.post("/api/auth/login",
                json={"phone": "9800000001", "password": "demo-pass-123"})
    check("verified govt can send", lg.json()["user"]["can_send"] is True)
    tok = lg.json().get("token", "")
    hdr = {"Authorization": f"Bearer {tok}"}

    b = c.post("/api/alerts/broadcast", headers=hdr,
               json={"entity_type": "taluka", "entity_id": "Baglan"}).json()
    check("broadcast reaches subscribers", b["audience"] >= 2 and b["sent"] >= 1)
    # The whole point: each recipient is scored for their OWN place, not the
    # sender's, and gets their OWN language.
    langs = {r["lang"] for r in b["detail"]["sent"]}
    places = {r["entity"] for r in b["detail"]["sent"]}
    check("recipients scored for their own place", len(places) >= 2)
    check("recipients messaged in their own language", len(langs) >= 2)
    check("SAFE recipients are skipped",
          all(r["band"] != "SAFE" for r in b["detail"]["sent"]))

    mgr = c.post("/api/auth/login", json={"phone": "9800000002", "password": "demo-pass-123"})
    mhdr = {"Authorization": f"Bearer {mgr.json()['token']}"}
    mb = c.post("/api/alerts/broadcast", headers=mhdr,
                json={"entity_type": "reservoir", "entity_id": "PUN_KHW"}).json()
    check("society manager scope is their society only",
          mb["audience"] < b["audience"])

    c.post("/api/auth/logout", headers=hdr)
    check("logout revokes the token", c.post(
        "/api/alerts/broadcast", headers=hdr,
        json={"entity_type": "taluka", "entity_id": "Baglan"}).status_code == 401)

    check("places typeahead", len(c.get("/api/places?q=dind").json()["results"]) >= 2)
    check("timeline", len(c.get("/api/timeline?entity_id=MUM_ALL").json()["points"]) == 85)
    check("static site", c.get("/").status_code == 200)
    check("signup.html", c.get("/signup.html").status_code == 200)
    check("openapi docs", c.get("/docs").status_code == 200)

    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    n_ok = sum(1 for _, v in checks if v)
    print(f"\n{n_ok}/{len(checks)} passed")
    return 0 if n_ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
