"""
JALAAKAR — the state-wide view, and the one button that acts on it.

What this adds that `/api/score` did not
---------------------------------------
`/api/score` answers "how is Baglan?". An official does not have a taluka in
mind; they have a state and a morning. This answers "where in Maharashtra is
the water in trouble right now, and can I warn those people in one click?"

So: score every taluka and every reservoir, sort by severity, and let the
official broadcast to a severity bucket. Every recipient is scored for THEIR
OWN place in THEIR OWN language — the bucket decides who is in scope, never
what they are told.

Buckets are the bands, and the bands are now the same on both tracks
---------------------------------------------------------------------
    ACT NOW   71-100   the caution alert
    MONITOR    41-70   the ordinary notice
    SAFE        0-40   no alert, ever, unless a human explicitly forces it

Rural used to break at 53. It now breaks at 70 like urban, because this page
puts a rural 68 and an urban 68 in one sorted table and it would be indefensible
for them to mean different things. `api/model.py` documents the recall this
costs and why it is still right for a broadcast product.

Dates: two tracks, two honest answers
-------------------------------------
Urban scores at its latest published reading, which is current to yesterday.
Rural scores at EACH TALUKA'S OWN last real CGWB reading, because that is the
only date a rural score can honestly exist for. Most land on 2023-05-15 or
2023-08-15. Every row carries `date` and `days_stale` so the table shows its
own age rather than implying the whole state was measured this morning.

Why an in-memory cache and not a table
--------------------------------------
A full sweep is ~940 model forecasts, each building 26 features against a
3.86M-row weather table. That is slow enough that nobody would click it twice.
It is cached in memory, built on first request, and rebuilt only when someone
asks. Deliberately NOT persisted: a stored snapshot is a number with no
visible age, and this project has a rule about those. Restart the server and
it rebuilds from the database, so the cache can never disagree with the data.
"""

from __future__ import annotations

import threading
import time
from datetime import date

from .appdb import app_db, pipeline_db
from . import alerts as alerts_mod
from . import model as model_mod
from . import scoring

# ACT NOW is the caution alert, MONITOR the ordinary notice.
BUCKETS = ("all", "act_now", "monitor")
BUCKET_BANDS = {"act_now": ("ACT NOW",), "monitor": ("MONITOR",),
                "all": ("ACT NOW", "MONITOR")}

_LOCK = threading.Lock()
_CACHE: dict | None = None


# --------------------------------------------------------------------------
def _subscriber_counts(audience: list[dict] | None = None) -> dict[str, int]:
    """entity_id -> how many people the SEND would actually reach there.

    Counted off the same `auth.audience(sender)` list the broadcast iterates,
    not a raw GROUP BY over users. Those two differ, and the difference was a
    visible bug: the button offered to message 3 people when it would message
    2, because the raw count included the signed-in official themselves — and
    `auth.audience` excludes the sender, since broadcasting a warning to
    yourself inflates the number and tells you nothing.

    Falling back to the raw count when no audience is supplied would
    reintroduce exactly that, so there is no fallback.
    """
    counts: dict[str, int] = {}
    for u in (audience or []):
        eid = u.get("entity_id")
        if eid:
            counts[eid] = counts.get(eid, 0) + 1
    return counts


def _row(card: dict, *, track: str, entity_type: str, entity_id: str,
         extra: dict) -> dict:
    """One table row. Unscorable entities are KEPT, with a reason.

    Dropping them would quietly shrink the state: 29 talukas have a single
    well and some have too little history to score. An official reading
    "247 talukas" should be able to see which ones the system cannot speak for.
    """
    base = {"track": track, "entity_type": entity_type,
            "entity_id": entity_id, **extra}

    if card.get("status") != "ok":
        return {**base, "label": extra.get("label") or entity_id,
                "score": None, "band": None, "colour": None,
                "date": card.get("data_through"), "days_stale": None,
                "reason": card.get("reason", "not scorable")}

    on = card.get("date")
    stale = None
    if on:
        try:
            stale = (date.today() - date.fromisoformat(on)).days
        except ValueError:
            stale = None

    head = card.get("headline") or {}
    return {
        **base,
        "label": card.get("entity_label", entity_id),
        "score": card["score"],
        "band": card["band"],
        "colour": card["colour"],
        "date": on,
        "days_stale": stale,
        "days_to_crisis": card.get("days_to_crisis"),
        "headline": head.get("value"),
        "headline_unit": head.get("unit"),
        "method": card.get("method"),
        "provenance": card.get("provenance"),
    }


def _build() -> dict:
    """Score the whole state. Slow and deliberate; the caller caches it.

    Deliberately does NOT include subscriber counts. Those live in app.db and
    change every time somebody signs up, and throwing away a 940-forecast
    sweep because one person registered would be absurd. They are joined on
    in `overview()`, which is a single cheap GROUP BY.
    """
    t0 = time.time()
    rows: list[dict] = []

    with pipeline_db() as con:
        talukas = con.execute(
            "SELECT taluka, district, COUNT(*) n_wells, MAX(last_obs) last_obs "
            "FROM wells WHERE taluka IS NOT NULL "
            "GROUP BY taluka ORDER BY taluka").fetchall()
        # urban_stress, not reservoirs: a reservoir with no scored row is not
        # something the dashboard can offer an opinion on.
        reservoirs = con.execute(
            "SELECT DISTINCT u.entity_id, r.name, r.city "
            "FROM urban_stress u LEFT JOIN reservoirs r "
            "ON r.reservoir_id = u.entity_id ORDER BY u.entity_id").fetchall()

    for t in talukas:
        card = scoring.rural_score("taluka", t["taluka"])
        rows.append(_row(card, track="rural", entity_type="taluka",
                         entity_id=t["taluka"],
                         extra={"district": t["district"],
                                "n_wells": t["n_wells"],
                                "label": f"{t['taluka']} Taluka, {t['district']}"}))

    for r in reservoirs:
        card = scoring.urban_score(r["entity_id"])
        rows.append(_row(card, track="urban", entity_type="reservoir",
                         entity_id=r["entity_id"],
                         extra={"district": r["city"],
                                "n_wells": None,
                                "label": r["name"] or r["entity_id"]}))

    # Worst first, then by name. Unscorable rows sort last rather than as 0 —
    # "we cannot say" is not the same claim as "it is fine".
    rows.sort(key=lambda x: (x["score"] is None,
                             -(x["score"] or 0), x["label"]))

    return {
        "built_at": time.time(),
        "build_seconds": round(time.time() - t0, 1),
        "rows": rows,
        "bands": {"monitor_above": model_mod.MONITOR_CUTOFF,
                  "act_now_above": model_mod.ACT_NOW_CUTOFF},
        "model": ("xgboost" if model_mod.available() else "climatology"),
    }


def _bucket_of(row: dict) -> str:
    if row["score"] is None:
        return "unscorable"
    return ("act_now" if row["band"] == "ACT NOW"
            else "monitor" if row["band"] == "MONITOR" else "safe")


def overview(bucket: str = "all", refresh: bool = False,
             scope_entity: str | None = None,
             audience: list[dict] | None = None) -> dict:
    """Cached state-wide sweep, optionally filtered to one severity bucket.

    `scope_entity` restricts the result to a single entity, which is how a
    society manager gets this page without seeing the whole state.

    `audience` is the sender's real broadcast list. Passing it makes the
    subscriber numbers on this page identical to the number of messages the
    Send button will produce — they are derived from the same list, so they
    cannot drift apart.
    """
    global _CACHE
    with _LOCK:
        if refresh or _CACHE is None:
            _CACHE = _build()
        snap = _CACHE

    subs = _subscriber_counts(audience)
    rows = [{**r, "subscribers": subs.get(r["entity_id"], 0)}
            for r in snap["rows"]
            if scope_entity is None or r["entity_id"] == scope_entity]

    counts = {"act_now": 0, "monitor": 0, "safe": 0, "unscorable": 0}
    reach = {"act_now": 0, "monitor": 0, "safe": 0, "unscorable": 0}
    for r in rows:
        k = _bucket_of(r)
        counts[k] += 1
        reach[k] += r["subscribers"]

    total = len(rows)
    if bucket in ("act_now", "monitor"):
        rows = [r for r in rows if _bucket_of(r) == bucket]

    return {
        "bucket": bucket,
        "rows": rows,
        "shown": len(rows),
        "total": total,
        "counts": counts,
        "subscriber_reach": reach,
        "bands": snap["bands"],
        "model": snap["model"],
        "built_at": snap["built_at"],
        "build_seconds": snap["build_seconds"],
        "age_seconds": round(time.time() - snap["built_at"]),
        "scoped_to": scope_entity,
        "note": ("Rural talukas are scored at their own last real CGWB "
                 "reading; urban at its latest published reading. Each row "
                 "carries that date and its age."),
    }


def cache_state() -> dict:
    return {"warm": _CACHE is not None,
            "age_seconds": (None if _CACHE is None
                            else round(time.time() - _CACHE["built_at"]))}


def invalidate() -> None:
    """Drop the snapshot. Called after anything that changes what it says."""
    global _CACHE
    with _LOCK:
        _CACHE = None


# --------------------------------------------------------------------------
# Message preview.
#
# The question an official actually has before pressing Send is "what will
# this say?", not "who exactly gets it". So the preview shows the WORDING —
# both bands, both audience types, all three languages — with sample values
# in the slots that vary per recipient.
#
# Rendered through `alerts.render`, the same function the real send calls.
# Retyping the templates here so the preview could be prettier is how a
# preview starts lying about what goes out.
# --------------------------------------------------------------------------
PREVIEW_ROLES = {"farmer": "farmer", "society": "society-manager"}

_SAMPLE = {
    "ACT NOW": {"score": 78, "days_to_crisis": 42,
                "headline": {"value": "9%", "unit": ""}},
    "MONITOR": {"score": 57, "days_to_crisis": 96,
                "headline": {"value": "34%", "unit": ""}},
}
SAMPLE_PLACE = "Baglan Taluka, Nashik"


def previews() -> dict:
    """Every message this system can send, as it will be worded."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    for band, card in _SAMPLE.items():
        out[band] = {}
        for group, role in PREVIEW_ROLES.items():
            out[band][group] = {
                lg: alerts_mod.render(
                    {"role": role, "lang": lg, "name": "Jal Mitra",
                     "entity_label": SAMPLE_PLACE},
                    {**card, "band": band})
                for lg in ("mr", "hi", "en")
            }
    return {
        "messages": out,
        "bands": list(_SAMPLE),
        "languages": ["mr", "hi", "en"],
        "sample": {"place": SAMPLE_PLACE,
                   **{b: {"score": c["score"], "days": c["days_to_crisis"]}
                      for b, c in _SAMPLE.items()}},
        "note": ("Place, score and days shown are samples. Every recipient "
                 "gets their own, computed for the place they registered."),
        "review_status": alerts_mod.TEMPLATES and
                         "Marathi and Hindi NOT yet checked by a native reader",
    }


# --------------------------------------------------------------------------
def broadcast(sender: dict, audience: list[dict], bucket: str = "all",
              dry_run: bool = False) -> dict:
    """One click: warn everyone whose OWN place is in the chosen bucket.

    The bucket selects the audience. It never selects the message — that comes
    from each recipient's own band, so a farmer in an ACT NOW taluka gets the
    caution alert and a resident in a MONITOR one gets the notice, from the
    same click. Sending one bucket's wording to the other bucket's people is
    exactly the failure this is built to avoid.

    SAFE recipients are unreachable here by construction. There is no bucket
    that includes them, because a broadcast that wakes up people whose water
    is fine is how an alerting channel gets muted.
    """
    want = BUCKET_BANDS.get(bucket, BUCKET_BANDS["all"])

    sent, skipped, failed = [], [], []
    for u in audience:
        card = scoring.score_for(u["entity_type"], u["entity_id"], lang=u["lang"])
        if card.get("status") != "ok":
            skipped.append({"user_id": u["user_id"], "entity": u["entity_label"],
                            "score": None, "band": None,
                            "reason": card.get("reason", "no score")[:110]})
            continue
        if card["band"] not in want:
            skipped.append({"user_id": u["user_id"], "entity": u["entity_label"],
                            "score": card["score"], "band": card["band"],
                            "reason": f"{card['band']} is not in this bucket"})
            continue

        rec = {"user_id": u["user_id"], "name": u.get("name"),
               "entity": u["entity_label"], "lang": u["lang"],
               "score": card["score"], "band": card["band"],
               "alert_type": ("caution" if card["band"] == "ACT NOW"
                              else "notice")}

        if dry_run:
            # Render without sending and without writing to alert_log. The
            # official can read the exact words before committing to them.
            rec.update({"status": "preview", "channel": "none",
                        "body": alerts_mod.render(u, card)})
            sent.append(rec)
            continue

        out = alerts_mod.send(u, card)
        rec.update({"status": out["status"], "channel": out["channel"],
                    "body": out.get("body"), "error": out.get("error")})
        (sent if out["status"] in ("sent", "rendered") else failed).append(rec)

    delivered = sum(1 for r in sent if r["channel"] == "whatsapp")
    return {
        "dry_run": dry_run,
        "bucket": bucket,
        "bands_included": list(want),
        "sender": {"name": sender["name"], "role": sender["role"],
                   "entity_label": sender["entity_label"]},
        "audience": len(audience),
        "sent": len(sent),
        "delivered": delivered,
        "rendered_only": len(sent) - delivered,
        "caution": sum(1 for r in sent if r["alert_type"] == "caution"),
        "notice": sum(1 for r in sent if r["alert_type"] == "notice"),
        "skipped": len(skipped),
        "failed": len(failed),
        "detail": {"sent": sent, "skipped": skipped, "failed": failed},
        "note": (None if dry_run or delivered == len(sent) else
                 "Messages with channel 'console' were rendered and logged, "
                 "not delivered — WhatsApp credentials are not configured."),
    }
