"""
JALAAKAR — sign-in for the roles allowed to send alerts.

Sign-in is phone number + password. The password is hashed with
PBKDF2-HMAC-SHA256 (240k iterations, per-user salt) in appdb.py — never
stored in the clear, and compared in constant time.

Two separate ideas, deliberately kept apart:

  AUTHENTICATION  who are you        -> anyone with an account can sign in
  AUTHORISATION   what may you do    -> only government officials and
                                        housing society managers may send

So a farmer can sign in and see their own score and alert history, and
simply has no send controls. That keeps "Sign in" in the nav honest for
every visitor instead of rejecting most of them.

What is enforced on the sending path, and all of it is real:
  * role must be `government` or `society-manager`
  * government accounts must be verified first (signup sets verified=0)
  * tokens expire, and are revoked on logout
  * a role change or a revocation kills live sessions on the next request
  * a society manager can only ever reach their own society

Still missing for production: rate limiting on failed logins, and account
recovery. Both are noted rather than quietly omitted.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from .appdb import app_db, utcnow, verify_password

SENDER_ROLES = ("government", "society-manager")
TOKEN_TTL_HOURS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def ensure_schema(con) -> None:
    con.executescript(SCHEMA)


def _expiry() -> str:
    return (datetime.now(timezone.utc)
            + timedelta(hours=TOKEN_TTL_HOURS)).isoformat(timespec="seconds")


def can_send(u: dict) -> bool:
    """Authorisation, kept separate from authentication on purpose."""
    return u.get("role") in SENDER_ROLES and bool(u.get("verified"))


def login(phone_e164: str, password: str) -> dict:
    """Returns {ok, token, user} or {ok: False, error, reason}."""
    with app_db() as con:
        ensure_schema(con)
        row = con.execute("SELECT * FROM users WHERE phone_e164=?",
                          (phone_e164,)).fetchone()

        # Same message whether the number is unknown or the password is wrong.
        # Distinguishing them turns the login form into a way to discover which
        # numbers are registered.
        if not row or not verify_password(password, row["pw_hash"]):
            return {"ok": False, "error": "bad_credentials",
                    "reason": "That number and password do not match."}
        u = dict(row)

        if u["pw_hash"] is None:
            return {"ok": False, "error": "no_password",
                    "reason": "This account predates passwords. Sign up again "
                              "or set one with tools/set_password.py."}

        token = secrets.token_urlsafe(32)
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (utcnow(),))
        con.execute("INSERT INTO sessions (token,user_id,created_at,expires_at) "
                    "VALUES (?,?,?,?)", (token, u["user_id"], utcnow(), _expiry()))
    return {"ok": True, "token": token, "user": _public(u)}


def resolve(token: str | None) -> dict | None:
    """Token -> user, or None. Expired tokens are deleted as they are found."""
    if not token:
        return None
    with app_db() as con:
        ensure_schema(con)
        row = con.execute(
            "SELECT u.*, s.expires_at FROM sessions s "
            "JOIN users u ON u.user_id = s.user_id WHERE s.token = ?",
            (token,)).fetchone()
        if not row:
            return None
        u = dict(row)
        if u["expires_at"] < utcnow():
            con.execute("DELETE FROM sessions WHERE token=?", (token,))
            return None
        # A role or verification change must take effect immediately, not
        # whenever the token happens to expire.
        # A signed-in farmer stays signed in; only the SEND path checks role.
        # What must invalidate immediately is a sender losing that right.
    return u


def logout(token: str) -> None:
    with app_db() as con:
        ensure_schema(con)
        con.execute("DELETE FROM sessions WHERE token=?", (token,))


def _public(u: dict) -> dict:
    out = {k: u[k] for k in ("user_id", "role", "name", "lang",
                             "entity_type", "entity_id", "entity_label",
                             "verified")}
    out["can_send"] = can_send(u)
    return out


# --------------------------------------------------------------------------
def audience(sender: dict) -> list[dict]:
    """Who this sender may broadcast to.

    government        every subscriber in the system
    society-manager   only accounts attached to the same entity

    The sender is excluded — broadcasting a warning to yourself inflates the
    delivery count and tells you nothing.
    """
    with app_db() as con:
        if sender["role"] == "government":
            rows = con.execute(
                "SELECT * FROM users WHERE user_id != ? AND entity_id IS NOT NULL",
                (sender["user_id"],)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM users WHERE user_id != ? AND entity_id = ? "
                "AND entity_id IS NOT NULL",
                (sender["user_id"], sender["entity_id"])).fetchall()
    return [dict(r) for r in rows]
