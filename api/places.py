"""
JALAAKAR — resolve free-text place strings to a forecastable entity.

The signup form asks for "Village / Taluka" or "Housing Society" as free text.
Scoring needs an entity id. This module is the bridge, and it is deliberately
conservative: if it cannot resolve a place with confidence it says so rather
than guessing, because a farmer silently subscribed to the wrong taluka gets
alerts about somebody else's water.

Resolution order
----------------
1. exact taluka match          -> entity_type 'taluka'  (all wells in it)
2. exact village match         -> entity_type 'well'
3. city keyword (mumbai/pune)  -> entity_type 'reservoir' aggregate
4. fuzzy prefix / substring    -> ranked candidates, caller must disambiguate
5. nothing                     -> unresolved, stored raw, flagged for follow-up
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from .appdb import pipeline_db

CITY_KEYWORDS = {
    "mumbai": ("MUM_ALL", "Mumbai — all 7 lakes"),
    "bombay": ("MUM_ALL", "Mumbai — all 7 lakes"),
    "thane": ("MUM_ALL", "Mumbai — all 7 lakes"),
    "pune": ("PUN_KHW", "Pune — Khadakwasla chain"),
    "pimpri": ("PUN_ALL", "Pune — all 5 dams"),
    "chinchwad": ("PUN_ALL", "Pune — all 5 dams"),
    "kothrud": ("PUN_KHW", "Pune — Khadakwasla chain"),
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    # drop the words people always type but that carry no location
    s = re.sub(r"\b(taluka|tehsil|tal|dist|district|village|gaon|"
               r"chs|society|housing|co-?op(erative)?)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@lru_cache(maxsize=1)
def gazetteer() -> dict:
    """Talukas, districts and villages that actually have wells behind them."""
    with pipeline_db() as con:
        talukas = con.execute(
            "SELECT taluka, district, COUNT(*) n FROM wells "
            "WHERE taluka IS NOT NULL GROUP BY taluka, district").fetchall()
        villages = con.execute(
            "SELECT well_id, village, taluka, district FROM wells "
            "WHERE village IS NOT NULL").fetchall()
    return {
        "talukas": [{"taluka": r["taluka"], "district": r["district"],
                     "n_wells": r["n"], "key": norm(r["taluka"])}
                    for r in talukas],
        "villages": [{"well_id": r["well_id"], "village": r["village"],
                      "taluka": r["taluka"], "district": r["district"],
                      "key": norm(r["village"])} for r in villages],
    }


def _taluka_hit(t: dict) -> dict:
    return {"entity_type": "taluka", "entity_id": t["taluka"],
            "label": f"{t['taluka']} Taluka, {t['district']}",
            "n_wells": t["n_wells"]}


def _village_hit(v: dict) -> dict:
    return {"entity_type": "well", "entity_id": v["well_id"],
            "label": f"{v['village']}, {v['taluka']} Taluka, {v['district']}",
            "n_wells": 1}


def resolve(place: str, role: str = "farmer") -> dict:
    """Returns {status, entity_type, entity_id, label, candidates}."""
    g = gazetteer()
    key = norm(place)
    if not key:
        return {"status": "unresolved", "candidates": []}

    tokens = key.split()

    # Urban roles: a city keyword is the right answer, not a well.
    if role in ("society-manager", "society-resident"):
        for tok in tokens:
            if tok in CITY_KEYWORDS:
                eid, label = CITY_KEYWORDS[tok]
                return {"status": "ok", "entity_type": "reservoir",
                        "entity_id": eid, "label": label, "candidates": []}

    for t in g["talukas"]:
        if t["key"] and t["key"] in tokens:
            return {"status": "ok", **_taluka_hit(t), "candidates": []}

    for v in g["villages"]:
        if v["key"] and v["key"] in tokens:
            return {"status": "ok", **_village_hit(v), "candidates": []}

    for tok in tokens:
        if tok in CITY_KEYWORDS:
            eid, label = CITY_KEYWORDS[tok]
            return {"status": "ok", "entity_type": "reservoir",
                    "entity_id": eid, "label": label, "candidates": []}

    # fuzzy: substring either direction, talukas ranked first
    cands = []
    for t in g["talukas"]:
        if t["key"] and (t["key"] in key or key in t["key"]):
            cands.append(_taluka_hit(t))
    for v in g["villages"]:
        if v["key"] and (v["key"] in key or key in v["key"]):
            cands.append(_village_hit(v))

    if len(cands) == 1:
        return {"status": "ok", **cands[0], "candidates": []}
    if cands:
        return {"status": "ambiguous", "candidates": cands[:8]}
    return {"status": "unresolved", "candidates": []}


def search(q: str, limit: int = 10) -> list[dict]:
    """Typeahead for the signup field."""
    g = gazetteer()
    key = norm(q)
    if len(key) < 2:
        return []
    out = [_taluka_hit(t) for t in g["talukas"] if t["key"].startswith(key)]
    out += [_taluka_hit(t) for t in g["talukas"]
            if key in t["key"] and not t["key"].startswith(key)]
    out += [_village_hit(v) for v in g["villages"] if v["key"].startswith(key)]
    for name, (eid, label) in CITY_KEYWORDS.items():
        if name.startswith(key):
            out.append({"entity_type": "reservoir", "entity_id": eid,
                        "label": label, "n_wells": None})
    seen, uniq = set(), []
    for o in out:
        k = (o["entity_type"], o["entity_id"])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq[:limit]
