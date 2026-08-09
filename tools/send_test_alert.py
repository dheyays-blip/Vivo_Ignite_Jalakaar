#!/usr/bin/env python3
"""
JALAAKAR — send one real WhatsApp alert and tell you exactly what happened.

    python tools/send_test_alert.py --phone 9123456780 --place Baglan --lang mr

This is Phase 8.1: "end-to-end run — raw data to score to WhatsApp alert
received on a real phone". Until that has actually happened once, assume it
will not happen on stage.

It talks to the modules directly, so the API server does not need to be
running. What it checks, in order, because each step fails differently:

  1. Twilio credentials present?      -> otherwise it renders and says so
  2. Does the place resolve?          -> a farmer subscribed to nothing is
                                         worse than an error
  3. Does the score warrant an alert? -> SAFE sends nothing by design, which
                                         is the single most common reason a
                                         test "silently fails"
  4. Did Twilio accept it?            -> prints the message SID
  5. What went into the log?          -> the permanent record of whether this
                                         was a real send or a dry run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import alerts as alerts_mod          # noqa: E402
from api import places as places_mod          # noqa: E402
from api import scoring                       # noqa: E402
from api.appdb import app_db, new_id, normalise_phone, utcnow  # noqa: E402

SANDBOX = "whatsapp:+14155238886"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", required=True, help="your number, e.g. 9123456780")
    ap.add_argument("--place", default="Baglan",
                    help="Baglan scores ACT NOW; Mumbai scores SAFE and will "
                         "not send unless you pass --force")
    ap.add_argument("--lang", default="mr", choices=["mr", "hi", "en"])
    ap.add_argument("--role", default="farmer",
                    choices=["farmer", "society-manager", "society-resident"])
    ap.add_argument("--on", default="2023-05-15",
                    help="scenario date; rural data ends 2023-08-15")
    ap.add_argument("--force", action="store_true",
                    help="send even if the band is SAFE")
    ap.add_argument("--dry-run", action="store_true",
                    help="render only, never contact Twilio")
    args = ap.parse_args()

    print()
    # ---- 1. credentials --------------------------------------------------
    sid, tok = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_WHATSAPP_FROM", SANDBOX)
    if args.dry_run:
        print("  1. credentials .......... skipped (--dry-run)")
    elif sid and tok:
        print(f"  1. credentials .......... found, sending from {frm}")
        try:
            import twilio  # noqa: F401
        except ImportError:
            print("     twilio package missing: pip install twilio")
            return 1
    else:
        print("  1. credentials .......... MISSING")
        print("     The message will be rendered and logged, not delivered.")
        print("     export TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=...")

    # ---- 2. place --------------------------------------------------------
    try:
        phone = normalise_phone(args.phone)
    except ValueError as e:
        print(f"  2. phone ................ REJECTED: {e}")
        return 1
    res = places_mod.resolve(args.place, args.role)
    if res.get("status") != "ok":
        print(f"  2. place ................ {args.place!r} did not resolve "
              f"({res.get('status')})")
        return 1
    print(f"  2. place ................ {res['label']}  [{phone}]")

    # ---- 3. score --------------------------------------------------------
    card = scoring.score_for(res["entity_type"], res["entity_id"],
                             args.on if res["entity_type"] != "reservoir" else None,
                             lang=args.lang)
    if card.get("status") != "ok":
        print(f"  3. score ................ none: {card.get('reason', '')[:70]}")
        return 1
    print(f"  3. score ................ {card['score']}/100  {card['band']} "
          f"({card['band_label']})  via {card['method']}")

    if not alerts_mod.should_alert(card["band"]) and not args.force:
        print(f"\n  {card['band']} does not warrant an alert, so nothing was sent.")
        print("  That is the design, not a failure — a system that only ever")
        print("  screams red is not a forecaster.")
        print("  Re-run with --force, or use a stressed place like Baglan.\n")
        return 0

    # ---- 4. user ---------------------------------------------------------
    with app_db() as con:
        row = con.execute("SELECT * FROM users WHERE phone_e164=?",
                          (phone,)).fetchone()
        if row:
            user = dict(row)
            print(f"  4. user ................. existing {user['user_id']}")
        else:
            user = {"user_id": new_id("usr"), "role": args.role,
                    "name": "Demo Recipient", "phone_e164": phone,
                    "lang": args.lang, "place_raw": args.place,
                    "entity_type": res["entity_type"],
                    "entity_id": res["entity_id"], "entity_label": res["label"],
                    "verified": 1}
            con.execute(
                "INSERT INTO users (user_id,role,name,phone_e164,lang,place_raw,"
                "entity_type,entity_id,entity_label,verified,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*[user[k] for k in ("user_id", "role", "name", "phone_e164",
                                     "lang", "place_raw", "entity_type",
                                     "entity_id", "entity_label", "verified")],
                 utcnow()))
            print(f"  4. user ................. created {user['user_id']}")

    body = alerts_mod.render(user, card)
    print("\n  ---- message ----")
    for line in body.splitlines():
        print(f"  | {line}")
    print("  -----------------\n")

    if args.dry_run:
        print("  --dry-run: not sent.\n")
        return 0

    # ---- 5. send ---------------------------------------------------------
    out = alerts_mod.send(user, card, force=args.force)
    print(f"  5. send ................. {out['status']}  via {out['channel']}")
    if out.get("provider_sid"):
        print(f"     Twilio SID ........... {out['provider_sid']}")
    if out.get("error"):
        print(f"     ERROR ................ {out['error']}")
        print("     Common causes: the recipient never sent the sandbox join")
        print("     code, or the 72-hour sandbox session has expired. Re-send")
        print("     'join <your-code>' to the sandbox number and try again.")
    if out.get("note"):
        print(f"     {out['note']}")

    with app_db() as con:
        n = con.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0]
    print(f"  6. alert_log ............ {n} row(s) total\n")

    if out["status"] == "sent":
        print("  Check the phone. If it arrived, Phase 8.1 is done.\n")
        return 0
    return 0 if out["status"] == "rendered" else 1


if __name__ == "__main__":
    sys.exit(main())
