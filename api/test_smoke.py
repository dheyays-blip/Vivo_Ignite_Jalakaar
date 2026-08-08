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
                                    "place": "Baglan Taluka, Nashik", "lang": "mr"})
    d = r.json()
    uid = d.get("user_id")
    check("signup 91-prefix phone", r.status_code == 201 and d["entity"]["id"] == "Baglan")

    check("dup phone 409", c.post("/api/signup", json={
        "role": "farmer", "name": "Suresh Kale", "phone": "9123456780",
        "place": "Baglan", "lang": "en"}).status_code == 409)
    check("bad phone 422", c.post("/api/signup", json={
        "role": "farmer", "name": "Ok Name", "phone": "12345",
        "place": "Baglan", "lang": "en"}).status_code == 422)

    g = c.post("/api/signup", json={"role": "government", "name": "Dept Officer",
                                    "phone": "9876500011",
                                    "place": "GSDA, Nashik Division",
                                    "lang": "en"}).json()
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
                                      "lang": "en"}).json()
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
