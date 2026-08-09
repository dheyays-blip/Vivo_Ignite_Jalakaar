#!/usr/bin/env python3
"""
JALAAKAR — clear signups and other user-generated data from data/app.db.

    python tools/reset_app_db.py --dry-run     # show what would go
    python tools/reset_app_db.py --users       # signups + their alerts + sessions
    python tools/reset_app_db.py --all         # everything, including reports
    python tools/reset_app_db.py --all --yes   # no confirmation prompt

Why a script rather than `rm data/app.db`
-----------------------------------------
Deleting the file works, but it takes community_reports and alert_log with it,
and those are the only record that the Measure and Alert steps ever ran. Before
a demo you usually want the test signups gone and the evidence kept.

Three tables hold user data and they are NOT all linked:

    users             the signups
    alert_log         FK to users ON DELETE CASCADE — goes automatically
    community_reports user_id column but NO foreign key — orphaned, not deleted
    wa_sessions       keyed by PHONE, not user_id — no link to users at all

That last one matters. wa_sessions remembers which well a phone number is
reporting against. Delete a user without clearing their session and that phone
can still send readings, resolved to the well of an account that no longer
exists. This script clears them together.

It will not touch data/jalaakar.db. Pipeline data is regenerable; nothing in
here should be able to reach it.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DB = ROOT / "data" / "app.db"

TABLES = ["users", "alert_log", "community_reports", "wa_sessions"]
USER_TABLES = ["users", "alert_log", "wa_sessions"]


def counts(con) -> dict:
    out = {}
    for t in TABLES:
        try:
            out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None          # table not created yet
    return out


def show(label: str, c: dict) -> None:
    print(f"  {label}")
    for t in TABLES:
        n = c[t]
        print(f"    {t:<20} {'—' if n is None else format(n, ',')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--users", action="store_true",
                   help="signups, their alerts, and WhatsApp sessions")
    g.add_argument("--all", action="store_true",
                   help="the above plus community_reports")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not APP_DB.exists():
        print(f"  {APP_DB} does not exist — nothing to clear.")
        print("  It is created on the first signup, so you are already clean.")
        return 0

    scope = USER_TABLES if args.users else TABLES if args.all else None
    if scope is None:
        ap.error("choose --users or --all (or --dry-run to look first)")

    con = sqlite3.connect(APP_DB)
    before = counts(con)
    print(f"\n  {APP_DB}")
    show("before:", before)

    doomed = sum(before[t] or 0 for t in scope)
    print(f"\n  Would delete {doomed:,} rows from: {', '.join(scope)}")
    if args.users and before.get("community_reports"):
        print(f"  Keeping {before['community_reports']:,} community_reports — "
              f"their user_id will be orphaned but the readings survive.")

    if args.dry_run:
        print("\n  --dry-run: nothing changed.\n")
        return 0

    if not doomed:
        print("\n  Already empty.\n")
        return 0

    if not args.yes:
        try:
            ok = input(f"\n  Type DELETE to remove {doomed:,} rows: ").strip()
        except EOFError:
            ok = ""
        if ok != "DELETE":
            print("  Cancelled.\n")
            return 1

    if not args.no_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = APP_DB.with_name(f"app_backup_{stamp}.db")
        shutil.copy2(APP_DB, bak)
        print(f"\n  Backup: {bak.name}")

    # Order matters: children before parents, in case foreign keys are off.
    # ON DELETE CASCADE only fires when PRAGMA foreign_keys is ON, and that
    # pragma is per-connection — a plain sqlite3 CLI session has it OFF.
    #
    # Skip tables that do not exist. community_reports and wa_sessions are
    # created lazily by api/community.py on first use, so on a machine that has
    # taken signups but never a WhatsApp message they are simply absent. The
    # count pass above already reports those as None; this used to ignore that
    # and DELETE FROM them anyway, which raised OperationalError mid-loop.
    con.execute("PRAGMA foreign_keys = ON")
    skipped = []
    for t in ("alert_log", "community_reports", "wa_sessions", "users"):
        if t not in scope:
            continue
        if before[t] is None:
            skipped.append(t)
            continue
        con.execute(f"DELETE FROM {t}")
    con.commit()
    if skipped:
        print(f"  Skipped (not created yet): {', '.join(skipped)}")
    con.execute("VACUUM")
    con.commit()

    show("after:", counts(con))
    con.close()
    print("\n  Done. The next signup recreates whatever is needed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
