"""
JALAAKAR — landing-page figures, served with provenance.

The frontend currently hardcodes these in `window.JALAAKAR_FIGURES`, and three
of them were already stale by the time the data was re-sourced on 8 Aug:

    6.93%  was labelled 30 June. It is 29 June. 30 June is 6.75%.
    53.38% was on the page at all. It is contradicted by BMC's own record
           (77.62% on 24 Jul, 88.40% on 27 Jul) and has been deleted.
    8.34%  was tagged unverified. It now has a Free Press Journal source.

That is the whole argument for this endpoint. A number on the landing page and
a number in the database should not be able to disagree, and the only way to
guarantee that is to stop maintaining two copies. Here the copy on the page is
derived from `ingest/reservoir_seeds.csv`, which is also what the pipeline
loads, so correcting the data corrects the site.

Non-reservoir figures (tanker cost, CGWB counts) are not in the database and
are declared below with their status stated plainly.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEDS = ROOT / "ingest" / "reservoir_seeds.csv"

# Figures the site quotes that do not come from reservoir_daily.
STATIC_FIGURES = {
    "warningWindowDays": {"value": 30, "unit": "days", "confidence": "primary",
                          "source_org": "product spec", "source_url": None},
    "deployedSystemCost": {"value": 0, "unit": "INR", "confidence": "primary",
                           "source_org": "open data only, no paid API in the stack",
                           "source_url": None},
    "validationRigCost": {"value": 2645, "unit": "INR", "confidence": "primary",
                          "source_org": "bill of materials", "source_url": None},
    "tankerCostPune": {"value": 3000, "unit": "INR", "confidence": "unsourced",
                       "source_org": None, "source_url": None},
    "cgwbOverExploited": {"value": 730, "unit": "units", "confidence": "unsourced",
                          "source_org": "CGWB", "source_url": None},
    "wellsDecliningPct": {"value": 33, "unit": "%", "confidence": "unsourced",
                          "source_org": "CGWB", "source_url": None},
    "interpolationMae": {"value": 1.32, "unit": "m", "confidence": "primary",
                         "source_org": "measured on 1,088 held-out CGWB readings",
                         "source_url": None},
}

ENTITY_LABEL = {
    "MUM_ALL": "Mumbai, all 7 lakes",
    "PUN_KHW": "Pune, Khadakwasla chain (4 dams)",
    "PUN_ALL": "Pune, all 5 dams",
}

# The handful the landing page actually quotes, by seed row.
HEADLINE_KEYS = {
    ("MUM_ALL", "2026-06-29"): "mumbai7Lakes_29Jun2026",
    ("MUM_ALL", "2026-06-30"): "mumbai7Lakes_30Jun2026",
    ("MUM_ALL", "2026-08-03"): "mumbai7Lakes_03Aug2026",
    ("MUM_ALL", "2026-08-07"): "mumbai7Lakes_07Aug2026",
    ("MUM_ALL", "2026-06-16"): "mumbai_16Jun2026",
    ("MUM_ALL", "2026-06-23"): "mumbai_23Jun2026",
    ("PUN_ALL", "2026-08-07"): "pune5Dams_07Aug2026",
    ("PUN_KHW", "2026-07-05"): "puneKhadakwasla_05Jul2026",
}


@lru_cache(maxsize=1)
def load() -> dict:
    if not SEEDS.exists():
        raise FileNotFoundError(f"{SEEDS} missing")

    figures: dict = {}
    anchors: list[dict] = []
    with SEEDS.open() as fh:
        for row in csv.DictReader(r for r in fh if not r.lstrip().startswith("#")):
            if not row.get("entity_id"):
                continue
            rec = {
                "entity_id": row["entity_id"],
                "entity_label": ENTITY_LABEL.get(row["entity_id"], row["entity_id"]),
                "date": row["date"],
                "value": float(row["live_storage_pct"]),
                "unit": "%",
                "confidence": row.get("confidence"),
                "verified": row.get("confidence") in ("primary", "reported"),
                "source_org": row.get("source_org"),
                "source_url": row.get("source_url"),
                "note": row.get("source_note"),
            }
            anchors.append(rec)
            key = HEADLINE_KEYS.get((row["entity_id"], row["date"]))
            if key:
                figures[key] = rec

    for k, v in STATIC_FIGURES.items():
        figures[k] = {**v, "verified": v["confidence"] in ("primary", "reported")}

    counts: dict[str, int] = {}
    for a in anchors:
        counts[a["confidence"]] = counts.get(a["confidence"], 0) + 1

    return {
        "figures": figures,
        "anchors": sorted(anchors, key=lambda a: (a["entity_id"], a["date"])),
        "summary": {
            "total_anchors": len(anchors),
            "by_confidence": counts,
            "unverified": [f"{a['entity_id']} {a['date']}" for a in anchors
                           if not a["verified"]],
        },
        "retracted": [{
            "key": "statewide_25Jun2026",
            "value": 53.38,
            "reason": ("Cited the Jalaakar poster only, and BMC's own record "
                       "contradicts it: 77.62% on 24 Jul and 88.40% on 27 Jul. "
                       "A 53% reading cannot sit between them. Deleted 8 Aug 2026."),
        }, {
            "key": "mumbai7Lakes_30Jun2026 = 6.93",
            "value": 6.93,
            "reason": ("Right number, wrong date. FPJ's table is captioned "
                       "'Water Stock As On June 29'. 30 June is 6.75%, "
                       "confirmed by Mid-Day. Both dates are now anchored."),
        }],
    }
