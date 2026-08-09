#!/usr/bin/env python3
"""
JALAAKAR — create demo accounts so a fresh clone has something to show.

    python tools/seed_demo.py          (or: make demo-user)

A clone starts with an empty data/app.db, so "Broadcast to all subscribers"
would reach nobody and the sign-in gate has nothing to sign in with. This
creates one of each role, with a stated password, and approves the government
account the way an administrator would.

Everything here is obviously fake and says so — the names are placeholders and
the phone numbers are in the 98000000xx block. Delete it all with
`python tools/reset_app_db.py --users`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import places as places_mod          # noqa: E402
from api.appdb import (app_db, hash_password, new_id,  # noqa: E402
                       normalise_phone, utcnow)

PASSWORD = "jalaakar-demo"

PEOPLE = [
    ("government",       "GSDA Officer",  "9800000001", "GSDA, Nashik Division", "en"),
    ("society-manager",  "Asha Rao",      "9800000002", "Shivneri CHS, Kothrud, Pune", "en"),
    ("farmer",           "Ramesh Patil",  "9800000003", "Baglan", "mr"),
    ("farmer",           "Sita More",     "9800000004", "Jat", "hi"),
    ("society-resident", "Vikram Shinde", "9800000005", "Kothrud, Pune", "en"),
]


def main() -> int:
    print(f"\n  Creating {len(PEOPLE)} demo accounts (password: {PASSWORD})\n")
    made = skipped = 0
    with app_db() as con:
        for role, name, phone, place, lang in PEOPLE:
            e164 = normalise_phone(phone)
            if con.execute("SELECT 1 FROM users WHERE phone_e164=?",
                           (e164,)).fetchone():
                print(f"    {phone}  {name:<15} already exists")
                skipped += 1
                continue
            res = places_mod.resolve(place, role)
            ok = res.get("status") == "ok"
            con.execute(
                "INSERT INTO users (user_id,role,name,phone_e164,pw_hash,lang,"
                "place_raw,entity_type,entity_id,entity_label,verified,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("usr"), role, name, e164, hash_password(PASSWORD), lang,
                 place,
                 res.get("entity_type") if ok else "unresolved",
                 res.get("entity_id") if ok else None,
                 res.get("label") if ok else place,
                 # The government account is approved here so the demo works.
                 # In the product this is a department decision, which is why
                 # signup sets verified=0 and tools/verify_user.py exists.
                 1, utcnow()))
            print(f"    {phone}  {name:<15} {role:<17} "
                  f"{res.get('label') if ok else 'UNRESOLVED'}")
            made += 1

    print(f"\n  {made} created, {skipped} already there.\n")
    print("  Sign in at http://localhost:8000/login.html")
    print(f"    9800000001 / {PASSWORD}   government — can broadcast to all")
    print(f"    9800000002 / {PASSWORD}   society manager — Kothrud only")
    print(f"    9800000003 / {PASSWORD}   farmer — can sign in, cannot send")
    print("\n  Remove them with: python tools/reset_app_db.py --users\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
