#!/usr/bin/env python3
"""
JALAAKAR — approve a government account so it can sign in and send alerts.

    python tools/verify_user.py --list
    python tools/verify_user.py --phone 9876500011
    python tools/verify_user.py --phone 9876500011 --revoke

Signup deliberately creates government accounts with verified=0, matching the
copy on the form: "Government Official accounts require department
verification before dashboard access is granted." Until someone approves the
account it cannot sign in, so this is the approval step.

In production this would be a department workflow. For the prototype it is a
human running one command, which is at least an explicit human decision
rather than an implicit one.
"""
import argparse, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from api.appdb import APP_DB, normalise_phone  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revoke", action="store_true")
    a = ap.parse_args()

    if not APP_DB.exists():
        print("  No app.db yet — nobody has signed up.")
        return 0
    con = sqlite3.connect(APP_DB); con.row_factory = sqlite3.Row

    if a.list or not a.phone:
        rows = con.execute("SELECT phone_e164,name,role,verified,entity_label "
                           "FROM users ORDER BY role, name").fetchall()
        if not rows:
            print("  No accounts."); return 0
        print(f"\n  {'phone':<16}{'role':<18}{'ok':<4}{'name':<20}place")
        print(f"  {'-'*76}")
        for r in rows:
            print(f"  {r['phone_e164']:<16}{r['role']:<18}"
                  f"{'yes' if r['verified'] else 'NO':<4}{r['name'][:19]:<20}"
                  f"{r['entity_label'] or '—'}")
        print("\n  Only government and society-manager accounts can send.")
        print("  Government accounts start unverified.\n")
        return 0

    phone = normalise_phone(a.phone)
    r = con.execute("SELECT * FROM users WHERE phone_e164=?", (phone,)).fetchone()
    if not r:
        print(f"  {phone} is not registered."); return 1
    con.execute("UPDATE users SET verified=? WHERE phone_e164=?",
                (0 if a.revoke else 1, phone))
    # A revoked account must lose its live sessions immediately.
    if a.revoke:
        try:
            con.execute("DELETE FROM sessions WHERE user_id=?", (r["user_id"],))
        except sqlite3.OperationalError:
            pass
    con.commit()
    print(f"  {r['name']} ({r['role']}) {'REVOKED' if a.revoke else 'verified'} — {phone}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
