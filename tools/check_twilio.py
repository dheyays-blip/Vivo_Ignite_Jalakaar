#!/usr/bin/env python3
"""
JALAAKAR — will a send actually deliver? Answer before you need it to.

    python tools/check_twilio.py

Contacts nothing. Reads `.env` plus the environment and reports what the send
path will do. This exists because the failure mode it catches is silent: with
no credentials, `alerts.send()` returns status='rendered' and a perfectly good
message body, which looks like success in a terminal and is not one.

Exit codes: 0 = will deliver, 1 = will render only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import env as env_mod  # noqa: E402


def main() -> int:
    st = env_mod.twilio_status()
    found = env_mod.ENV_PATH.is_file()

    print()
    print(f"  .env .................... {'found' if found else 'not present'}"
          f"  ({env_mod.ENV_PATH})")
    print(f"  account sid ............. {st['account_sid'] or 'MISSING'}")
    print(f"  from .................... {st['from']}"
          f"{'  (shared sandbox)' if st['sandbox'] else ''}")
    print()

    if st["will_deliver"]:
        print("  Credentials look usable — a send will go to WhatsApp.")
        print()
        print("  One thing this cannot check: whether the RECIPIENT has joined")
        print("  your sandbox, and whether that 3-day session is still alive.")
        print("  Only Twilio knows, and it tells you by failing the send with")
        print("  error 63015 / 63016. If that happens, re-send the join phrase")
        print("  from the recipient's phone and try again.")
        print()
        return 0

    print("  Will NOT deliver. Messages get rendered and logged instead:")
    for p in st["problems"]:
        print(f"    • {p}")
    print()
    print("  Fix: cp .env.example .env, then fill in the two values from")
    print("  console.twilio.com -> Admin -> Account management -> API keys.")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
