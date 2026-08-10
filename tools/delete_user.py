#!/usr/bin/env python3
"""
JALAAKAR — delete ONE user, deliberately.

    python tools/delete_user.py --phone 9123456780 --dry-run   # look first
    python tools/delete_user.py --phone 9123456780             # asks to confirm
    python tools/delete_user.py --user-id usr_ab12cd34ef56
    python tools/delete_user.py --phone 9123456780 --purge-alerts
    python tools/delete_user.py --auto --dry-run   # every test-send leftover

For clearing everything at once, use tools/reset_app_db.py. This is the
scalpel: one person asked to be removed, or one test row should never have
existed.

The cascade this script exists to prevent
-----------------------------------------
`alert_log.user_id` is declared REFERENCES users(user_id) ON DELETE CASCADE.
That pragma is off by default in SQLite, so whether a plain `DELETE FROM users`
also erases that person's entire alert history depends on a per-connection
setting — the same command destroys evidence or preserves it depending on how
you happened to connect. That is not a decision to leave to chance.

So this script makes it explicit and picks the safer default:

  default          alert_log rows are KEPT and DETACHED (user_id set to NULL).
                   The bodies contain a place, a score and a band — never a
                   name or a number, because no template interpolates {name} —
                   so the delivery record survives as anonymous evidence that
                   the Alert step ran, while the person is gone.

  --purge-alerts   alert_log rows are deleted too. Use this when the row was
                   never a real person and its sends would inflate your
                   delivery numbers.

Sessions are always deleted, both kinds
---------------------------------------
`sessions` holds live bearer tokens. A token outliving its user is an
authenticated request from an account that no longer exists.

`wa_sessions`, if present, is keyed by PHONE and not by user_id, so no foreign
key reaches it and no cascade will ever clear it. Leave it and that number can
still submit well readings against the deleted account's well. It is created
lazily by api/community.py, so on most machines it will not exist yet — absent
is fine, stale is not.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.appdb import APP_DB, normalise_phone  # noqa: E402


def table_exists(con, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name=?", (name,)).fetchone() is not None


def find(con, *, phone: str | None, user_id: str | None,
         auto: bool) -> list[sqlite3.Row]:
    if auto:
        return con.execute("SELECT * FROM users WHERE pw_hash IS NULL "
                           "ORDER BY created_at").fetchall()
    if user_id:
        return con.execute("SELECT * FROM users WHERE user_id=?",
                           (user_id,)).fetchall()
    e164 = normalise_phone(phone)
    return con.execute("SELECT * FROM users WHERE phone_e164=?",
                       (e164,)).fetchall()


def mask(phone: str) -> str:
    return f"{phone[:3]} XXXXX {phone[-4:]}" if phone.startswith("+91") else phone


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--phone", help="any format; normalised before lookup")
    who.add_argument("--user-id")
    who.add_argument("--auto", action="store_true",
                     help="every user with no password, i.e. rows a test send "
                          "created rather than a person")
    ap.add_argument("--purge-alerts", action="store_true",
                    help="delete their alert_log rows too (default: keep, "
                         "detached and anonymous)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not Path(APP_DB).exists():
        print(f"\n  No database at {APP_DB} — nobody has signed up.\n")
        return 0

    con = sqlite3.connect(APP_DB)
    con.row_factory = sqlite3.Row

    try:
        rows = find(con, phone=args.phone, user_id=args.user_id, auto=args.auto)
    except ValueError as e:
        print(f"\n  Not a usable phone number: {e}\n", file=sys.stderr)
        return 2

    if not rows:
        target = args.user_id or args.phone or "auto-created users"
        print(f"\n  No user matches {target!r}. Nothing to do.")
        print("  See who exists with:  make users\n")
        return 1

    has_wa = table_exists(con, "wa_sessions")

    print()
    print(f"  {APP_DB}")
    print()
    for u in rows:
        n_alerts = con.execute("SELECT COUNT(*) FROM alert_log WHERE user_id=?",
                               (u["user_id"],)).fetchone()[0]
        n_sess = con.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?",
                             (u["user_id"],)).fetchone()[0]
        n_wa = (con.execute("SELECT COUNT(*) FROM wa_sessions WHERE phone_e164=?",
                            (u["phone_e164"],)).fetchone()[0] if has_wa else 0)
        origin = "signup" if u["pw_hash"] else "auto (created by a test send)"
        print(f"  {u['name']}  ·  {u['role']}")
        print(f"    user_id ........ {u['user_id']}")
        print(f"    phone .......... {mask(u['phone_e164'])}")
        print(f"    place .......... {u['entity_label'] or u['place_raw']}")
        print(f"    registered ..... {u['created_at']}")
        print(f"    origin ......... {origin}")
        print(f"    alert_log ...... {n_alerts} row(s) — "
              f"{'DELETE' if args.purge_alerts else 'keep, detach to NULL'}")
        print(f"    sessions ....... {n_sess} token(s) — DELETE")
        if has_wa:
            print(f"    wa_sessions .... {n_wa} row(s) — DELETE")
        print()

    if args.dry_run:
        print("  --dry-run: nothing changed.\n")
        return 0

    if not args.yes:
        label = (f"{len(rows)} users" if len(rows) > 1 else rows[0]["name"])
        try:
            ok = input(f"  Type DELETE to remove {label}: ").strip()
        except EOFError:
            ok = ""
        if ok != "DELETE":
            print("  Cancelled. Nothing changed.\n")
            return 1

    if not args.no_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = Path(APP_DB).with_name(f"app_backup_{stamp}.db")
        shutil.copy2(APP_DB, bak)
        print(f"\n  Backup: {bak.name}")

    # foreign_keys stays OFF on purpose. With it ON, the DELETE below fires
    # ON DELETE CASCADE and takes alert_log with it regardless of what the
    # user asked for. Children are handled explicitly instead, in order.
    con.execute("PRAGMA foreign_keys = OFF")

    kept = purged = 0
    for u in rows:
        uid, phone = u["user_id"], u["phone_e164"]
        if args.purge_alerts:
            purged += con.execute("DELETE FROM alert_log WHERE user_id=?",
                                  (uid,)).rowcount
        else:
            # NULL, not the literal string 'deleted': the column is a foreign
            # key, and a value that points at no row is worse than no value.
            kept += con.execute("UPDATE alert_log SET user_id=NULL "
                                "WHERE user_id=?", (uid,)).rowcount
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if has_wa:
            con.execute("DELETE FROM wa_sessions WHERE phone_e164=?", (phone,))
        con.execute("DELETE FROM users WHERE user_id=?", (uid,))
    con.commit()

    left = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    logs = con.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0]
    orphan = con.execute("SELECT COUNT(*) FROM alert_log "
                         "WHERE user_id IS NULL").fetchone()[0]
    con.close()

    print()
    print(f"  Deleted {len(rows)} user(s). {left} remain.")
    if purged:
        print(f"  alert_log: {purged} row(s) deleted.")
    if kept:
        print(f"  alert_log: {kept} row(s) kept, now anonymous.")
    print(f"  alert_log total {logs}, of which {orphan} unattributed.")
    print()
    print("  That phone number can sign up again — the UNIQUE constraint on")
    print("  phone_e164 is now free.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
