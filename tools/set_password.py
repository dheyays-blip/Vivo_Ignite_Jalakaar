#!/usr/bin/env python3
"""
JALAAKAR — set or reset an account password.

    python tools/set_password.py --phone 9800000001 --password 'something long'

Needed for two cases: accounts created before passwords existed (their
pw_hash is NULL and they cannot sign in), and the ordinary "I forgot it"
that has no self-service flow yet. Account recovery is a real gap and this
is the stopgap, not a feature.
"""
import argparse, getpass, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from api.appdb import APP_DB, hash_password, normalise_phone  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", required=True)
    ap.add_argument("--password", help="prompted for if omitted")
    a = ap.parse_args()

    if not APP_DB.exists():
        print("  No app.db yet."); return 1
    phone = normalise_phone(a.phone)
    con = sqlite3.connect(APP_DB); con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM users WHERE phone_e164=?", (phone,)).fetchone()
    if not r:
        print(f"  {phone} is not registered."); return 1

    pw = a.password or getpass.getpass("  New password (min 8): ")
    try:
        h = hash_password(pw)
    except ValueError as e:
        print(f"  {e}"); return 1
    con.execute("UPDATE users SET pw_hash=? WHERE phone_e164=?", (h, phone))
    # Any existing session was issued under the old credential.
    try:
        con.execute("DELETE FROM sessions WHERE user_id=?", (r["user_id"],))
    except sqlite3.OperationalError:
        pass
    con.commit()
    print(f"  Password set for {r['name']} ({r['role']}) — {phone}")
    print("  Existing sessions revoked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
