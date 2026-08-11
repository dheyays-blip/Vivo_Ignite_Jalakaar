#!/usr/bin/env python3
"""
JALAAKAR — who has registered, and when.

    python tools/list_users.py                    # everyone, newest first
    python tools/list_users.py --role farmer      # one role
    python tools/list_users.py --since 2026-08-10 # registered on or after
    python tools/list_users.py --place Baglan     # substring, case-insensitive
    python tools/list_users.py --csv > users.csv  # for a spreadsheet
    python tools/list_users.py --full             # unmask phone numbers

Phone numbers are masked by default
-----------------------------------
`+91 XXXXX 6780`. This is a list of real people who handed over a number to
get water warnings, and the most likely way it leaks is not a breach — it is a
terminal window on a projector during a demo. `--full` when you actually need
to debug a delivery, not by habit.

Times are shown in IST
----------------------
`created_at` is stored UTC, which is correct and which nobody can read at a
glance. A signup at 11:56 UTC happened at 17:26 in Nashik. Both are printed so
you can match a row against a Twilio log without doing arithmetic.

The `origin` column
-------------------
`signup` means the account has a password, so a human completed the form.
`auto` means it does not — `send_test_alert.py` and `/api/alerts/send-demo`
create a user row for any number you send to, so test sends silently become
permanent subscribers who will receive the next broadcast. That is the column
to check before you press Send.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "app.db"
IST = timezone(timedelta(hours=5, minutes=30))

COLUMNS = ["registered_ist", "registered_utc", "role", "name", "phone",
           "lang", "place", "verified", "origin", "alerts", "user_id"]


def mask(phone: str) -> str:
    """+919123456780 -> +91 XXXXX 6780. Keeps enough to recognise a number
    you already know, not enough to dial one you don't."""
    if not phone:
        return "—"
    tail = phone[-4:]
    return f"{phone[:3]} XXXXX {tail}" if phone.startswith("+91") else f"…{tail}"


def pretty(phone: str) -> str:
    return (f"{phone[:3]} {phone[3:8]} {phone[8:]}"
            if phone.startswith("+91") and len(phone) == 13 else phone)


def to_ist(stamp: str) -> tuple[str, str]:
    """Returns (ist, utc) as 'YYYY-MM-DD HH:MM'. Tolerates a missing or
    unparseable timestamp rather than crashing the whole listing."""
    if not stamp:
        return "—", "—"
    raw = stamp.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return stamp[:16], stamp[:16]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"))


def fetch(args) -> list[dict]:
    if not DB.is_file():
        # NOT an error, and NOT a reason to re-run setup. data/app.db is
        # created by the first signup, so on a fresh clone it legitimately
        # does not exist yet. Saying "run 'make setup' first" sent people
        # back to a step they had just completed successfully, and exiting 1
        # made `make users` look like a broken target.
        print("\n  No accounts yet — data/app.db is created by the first "
              "signup.\n  Try 'make demo-user' for five, or sign up at "
              "http://localhost:8000/signup.html\n")
        raise SystemExit(0)

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # LEFT JOIN, not a subquery per row: a user with zero alerts must still
    # appear. Someone who registered and was never contacted is the single
    # most important row in this table.
    sql = """
        SELECT u.*, COUNT(a.alert_id) AS alerts
        FROM users u
        LEFT JOIN alert_log a ON a.user_id = u.user_id
        GROUP BY u.user_id
    """
    rows = [dict(r) for r in con.execute(sql).fetchall()]
    con.close()

    if args.role:
        rows = [r for r in rows if r["role"] == args.role]
    if args.lang:
        rows = [r for r in rows if r["lang"] == args.lang]
    if args.place:
        needle = args.place.lower()
        rows = [r for r in rows
                if needle in ((r.get("entity_label") or "") + " " +
                              (r.get("place_raw") or "")).lower()]
    if args.since:
        rows = [r for r in rows if (r.get("created_at") or "") >= args.since]
    if args.auto_only:
        rows = [r for r in rows if not r.get("pw_hash")]

    rows.sort(key=lambda r: r.get("created_at") or "", reverse=not args.oldest)
    return rows


def shape(r: dict, full: bool) -> dict:
    ist, utc = to_ist(r.get("created_at"))
    phone = r.get("phone_e164") or ""
    return {
        "registered_ist": ist,
        "registered_utc": utc,
        "role": r.get("role") or "—",
        "name": r.get("name") or "—",
        "phone": pretty(phone) if full else mask(phone),
        "lang": r.get("lang") or "—",
        "place": r.get("entity_label") or r.get("place_raw") or "—",
        "verified": "yes" if r.get("verified") else "NO",
        "origin": "signup" if r.get("pw_hash") else "auto",
        "alerts": r.get("alerts", 0),
        "user_id": r.get("user_id") or "—",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--role", choices=["farmer", "society-manager",
                                       "society-resident", "government"])
    ap.add_argument("--lang", choices=["mr", "hi", "en"])
    ap.add_argument("--place", help="substring match on place")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="registered on or after this UTC date")
    ap.add_argument("--auto-only", action="store_true",
                    help="only rows a test send created (no password)")
    ap.add_argument("--oldest", action="store_true", help="oldest first")
    ap.add_argument("--full", action="store_true",
                    help="show complete phone numbers")
    ap.add_argument("--csv", action="store_true", help="CSV to stdout")
    args = ap.parse_args()

    rows = [shape(r, args.full) for r in fetch(args)]

    if args.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
        return 0

    if not rows:
        print("\n  No users match those filters.\n")
        return 0

    print()
    print(f"  {len(rows)} user(s) · {DB.relative_to(ROOT)}"
          f"{'' if args.full else '  · phones masked, --full to reveal'}")
    print()
    head = (f"  {'registered (IST)':<17}  {'role':<16}  {'name':<15}  "
            f"{'phone':<17}  {'lg':<2}  {'orig':<6}  {'alrt':>4}  place")
    print(head)
    print("  " + "-" * (len(head) - 2))
    for r in rows:
        flag = "" if r["verified"] == "yes" else "  [unverified]"
        print(f"  {r['registered_ist']:<17}  {r['role']:<16}  "
              f"{r['name'][:15]:<15}  {r['phone']:<17}  {r['lang']:<2}  "
              f"{r['origin']:<6}  {r['alerts']:>4}  {r['place'][:34]}{flag}")

    # Summaries, because "how many farmers" is the next question every time.
    print()
    for field, label in (("role", "by role"), ("lang", "by language")):
        tally: dict[str, int] = {}
        for r in rows:
            tally[r[field]] = tally.get(r[field], 0) + 1
        parts = "   ".join(f"{k} {v}" for k, v in sorted(tally.items()))
        print(f"  {label:<12} {parts}")

    days: dict[str, int] = {}
    for r in rows:
        days[r["registered_ist"][:10]] = days.get(r["registered_ist"][:10], 0) + 1
    print("  by day (IST) " + "   ".join(f"{k} {v}" for k, v in sorted(days.items())))

    auto = sum(1 for r in rows if r["origin"] == "auto")
    if auto:
        print()
        print(f"  {auto} row(s) marked 'auto' — created by a test send, not by")
        print("  a person filling in the form. They are real subscribers as far")
        print("  as broadcast is concerned. Review with --auto-only.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
