"""
JALAAKAR — read `.env` into the environment, with no dependency.

Why this exists
---------------
`alerts.send()` reads TWILIO_* with `os.getenv`. That works, but it means the
credentials live in one shell only: open a second terminal, or let `--reload`
respawn the worker, and the same command that delivered a message five minutes
ago silently falls back to `channel='console'`. On a demo day that reads as
"the WhatsApp integration is broken" when the truth is "the export was in the
other tab".

So: a five-line parser, called once at import. `python-dotenv` would do this
too, but it is a runtime dependency for a file format that is `KEY=value`.

Rules, deliberately boring
--------------------------
* A real environment variable always wins. Nothing here overwrites an export,
  so `TWILIO_AUTH_TOKEN=xxx make run` still overrides the file.
* Blank lines and `#` comments are skipped. `export ` prefixes are tolerated,
  because everyone pastes those in from the README.
* One layer of matching quotes is stripped. No interpolation, no multi-line
  values, no `$OTHER_VAR` expansion — if you need those, you need a real
  secret manager, not a text file.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path | None = None, *, override: bool = False) -> list[str]:
    """Load `path` (default: repo-root `.env`). Returns the keys it set.

    Missing file is not an error. Running without credentials is a supported
    mode in this project, not a broken one.
    """
    path = path or ENV_PATH
    if not path.is_file():
        return []

    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()

        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not key:
            continue
        # Strip one matching pair of quotes, so both TOKEN=abc and
        # TOKEN="abc" mean the same thing.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]

        if override or key not in os.environ:
            os.environ[key] = val
            loaded.append(key)

    return loaded


def twilio_status() -> dict:
    """What the send path will actually do, without contacting Twilio.

    Useful before a demo: it answers "will this deliver?" in one call, and it
    never reports success on the strength of a variable merely being set.
    """
    sid = os.getenv("TWILIO_ACCOUNT_SID") or ""
    tok = os.getenv("TWILIO_AUTH_TOKEN") or ""
    frm = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    try:
        import twilio  # noqa: F401
        pkg = True
    except ImportError:
        pkg = False

    problems = []
    if not sid:
        problems.append("TWILIO_ACCOUNT_SID is not set")
    elif not sid.startswith("AC"):
        problems.append("TWILIO_ACCOUNT_SID does not start with 'AC' — that "
                        "looks like an API key SID or a Messaging Service "
                        "SID, not the Account SID")
    if not tok:
        problems.append("TWILIO_AUTH_TOKEN is not set")
    if not pkg:
        problems.append("the twilio package is not installed "
                        "(pip install twilio)")
    if not frm.startswith("whatsapp:"):
        problems.append(f"TWILIO_WHATSAPP_FROM={frm!r} is missing the "
                        "'whatsapp:' prefix")

    return {
        "will_deliver": not problems,
        "from": frm,
        "sandbox": frm == "whatsapp:+14155238886",
        # Never return the token, and show only enough of the SID to tell two
        # accounts apart in a screenshot.
        "account_sid": (f"{sid[:6]}…{sid[-4:]}" if len(sid) > 10 else
                        ("set" if sid else None)),
        "problems": problems,
    }


# Import-time load. `api.alerts` imports this module, so both the server and
# tools/send_test_alert.py get the same credentials from the same file.
load_env()
