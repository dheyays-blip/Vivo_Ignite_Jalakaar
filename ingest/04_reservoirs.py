#!/usr/bin/env python3
"""
JALAAKAR — Stage 4: reservoirs (urban track).
Owner: Dev B.

12 water bodies (Mumbai 7 + Pune 5) plus two city aggregate entities,
MUM_ALL and PUN_ALL, which is the level most public reporting is actually
published at.

Honesty model — read this before you touch the data
---------------------------------------------------
`reservoir_daily.source` records where every single row came from:

    'wrd_pravah'   scraped live from mumbailakewaterlevel.in (WRD / BMC)
    'manual'       hand-verified anchor from a named public source
                   (see ingest/reservoir_seeds.csv — each row cites it)
    'interpolated' filled between two 'manual'/'wrd_pravah' anchors

Only 'manual' and 'wrd_pravah' rows are real readings. If a judge asks
"where did this number come from?", `SELECT source` answers it.

Usage
-----
    python ingest/04_reservoirs.py --seed              # registry + anchors (offline)
    python ingest/04_reservoirs.py --seed --interpolate
    python ingest/04_reservoirs.py --live              # scrape today (needs internet)
    python ingest/04_reservoirs.py --all               # live + seed + interpolate
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import ROOT, cfg, connect, log_run, read, upsert  # noqa: E402

SEEDS = Path(__file__).parent / "reservoir_seeds.csv"

MUM_URL = "https://www.mumbailakewaterlevel.in/"
PUN_URL = "https://www.mumbailakewaterlevel.in/pune-dam-water-levels/"

# --------------------------------------------------------------------------
# registry — useful (live) capacity in ML; coords are for the weather pull
# Mumbai capacities: BMC Hydraulic Engineer's Dept. Sum = 1,447,363 ML,
# which matches the published combined total exactly.
# --------------------------------------------------------------------------
REGISTRY = pd.DataFrame(
    [
        # reservoir_id,   name,               city,     lat,    lon,    ML
        ("UPPER_VAITARNA", "Upper Vaitarna",  "Mumbai", 19.85, 73.50, 227_047),
        ("MODAK_SAGAR",    "Modak Sagar",     "Mumbai", 19.62, 73.32, 128_925),
        ("TANSA",          "Tansa",           "Mumbai", 19.60, 73.15, 145_080),
        ("MIDDLE_VAITARNA", "Middle Vaitarna", "Mumbai", 19.75, 73.42, 193_530),
        ("BHATSA",         "Bhatsa",          "Mumbai", 19.52, 73.42, 717_037),
        ("VIHAR",          "Vihar",           "Mumbai", 19.15, 72.91, 27_698),
        ("TULSI",          "Tulsi",           "Mumbai", 19.19, 72.90, 8_046),
        ("KHADAKWASLA",    "Khadakwasla",     "Pune",   18.44, 73.77, 55_910),
        ("PANSHET",        "Panshet",         "Pune",   18.39, 73.61, 301_610),
        ("VARASGAON",      "Varasgaon",       "Pune",   18.36, 73.56, 363_130),
        ("TEMGHAR",        "Temghar",         "Pune",   18.44, 73.53, 105_010),
        ("PAVANA",         "Pavana",          "Pune",   18.67, 73.48, 241_270),
    ],
    columns=["reservoir_id", "name", "city", "lat", "lon", "capacity_ml"],
)

# city aggregates — the entity most public reporting is published at
#
# PUN_KHW added 8 Aug. Pune storage is published for the *Khadakwasla chain*
# (Khadakwasla + Panshet + Varasgaon + Temghar, 29.15 TMC), which is what the
# Irrigation Department reports and what every Pune anchor in
# reservoir_seeds.csv actually measures. Pavana is a separate PCMC-side source
# and is NOT in that number. Feeding a 4-dam percentage into a 5-dam
# denominator understated Pune storage by ~23%.
#
# PUN_ALL capacity corrected 1,099,980 -> 1,066,930 ML. The old value matched
# no sum of the registry; the members total 1,066,930. See _check_aggregates.
AGGREGATES = pd.DataFrame(
    [
        ("MUM_ALL", "Mumbai — all 7 lakes",       "Mumbai", 19.55, 73.30, 1_447_363),
        ("PUN_KHW", "Pune — Khadakwasla chain",   "Pune",   18.42, 73.62,   825_660),
        ("PUN_ALL", "Pune — all 5 dams",          "Pune",   18.45, 73.60, 1_066_930),
    ],
    columns=["reservoir_id", "name", "city", "lat", "lon", "capacity_ml"],
)

# which water bodies each aggregate is the sum of — asserted at load time so
# a capacity edit can never silently desync the two again
AGGREGATE_MEMBERS = {
    "MUM_ALL": ["UPPER_VAITARNA", "MODAK_SAGAR", "TANSA", "MIDDLE_VAITARNA",
                "BHATSA", "VIHAR", "TULSI"],
    "PUN_KHW": ["KHADAKWASLA", "PANSHET", "VARASGAON", "TEMGHAR"],
    "PUN_ALL": ["KHADAKWASLA", "PANSHET", "VARASGAON", "TEMGHAR", "PAVANA"],
}


def _check_aggregates() -> None:
    """Every aggregate must equal the sum of its members. No exceptions.

    This is the invariant that failed silently before: PUN_ALL claimed
    1,099,980 ML while its five members summed to 1,066,930 ML, so every
    Pune storage_mcm was ~3% low and nothing complained.
    """
    body = dict(zip(REGISTRY.reservoir_id, REGISTRY.capacity_ml))
    agg = dict(zip(AGGREGATES.reservoir_id, AGGREGATES.capacity_ml))
    for aid, members in AGGREGATE_MEMBERS.items():
        want = sum(body[m] for m in members)
        got = agg[aid]
        if want != got:
            sys.exit(
                f"ERROR: {aid} capacity is {got:,} ML but its {len(members)} "
                f"members sum to {want:,} ML (difference {got - want:+,}). "
                f"Fix AGGREGATES or AGGREGATE_MEMBERS — do not load."
            )
    print(f"[check] {len(AGGREGATE_MEMBERS)} aggregates match the sum of their members")

NAME_TO_ID = {
    "upper vaitarna": "UPPER_VAITARNA", "modak sagar": "MODAK_SAGAR",
    "tansa": "TANSA", "middle vaitarna": "MIDDLE_VAITARNA", "bhatsa": "BHATSA",
    "vihar": "VIHAR", "vehar": "VIHAR", "tulsi": "TULSI",
    "khadakwasla": "KHADAKWASLA", "panshet": "PANSHET",
    "varasgaon": "VARASGAON", "temghar": "TEMGHAR", "pavana": "PAVANA",
}


def capacities() -> dict[str, float]:
    reg = pd.concat([REGISTRY, AGGREGATES])
    return dict(zip(reg.reservoir_id, reg.capacity_ml))


# --------------------------------------------------------------------------
# registry load
# --------------------------------------------------------------------------
def load_registry(con) -> int:
    _check_aggregates()
    reg = pd.concat([REGISTRY, AGGREGATES], ignore_index=True)
    reg["capacity_mcm"] = (reg["capacity_ml"] / 1000).round(3)   # 1000 ML = 1 MCM
    n = upsert(con, "reservoirs", reg.drop(columns=["capacity_ml"]))
    print(f"[registry] {n} rows ({len(REGISTRY)} water bodies + {len(AGGREGATES)} aggregates)")

    out = ROOT / "data" / "interim" / "reservoirs.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    reg.to_csv(out, index=False)
    print(f"[registry] coords for the weather pull → {out}")
    return n


# --------------------------------------------------------------------------
# seeds
# --------------------------------------------------------------------------
def load_seeds(con) -> int:
    if not SEEDS.exists():
        sys.exit(f"ERROR: {SEEDS} missing")
    s = pd.read_csv(SEEDS, comment="#")
    cap = capacities()

    s["date"] = pd.to_datetime(s["date"])
    s["storage_mcm"] = (
        s["live_storage_pct"] / 100 * s["entity_id"].map(cap) / 1000
    ).round(3)
    s["reservoir_id"] = s["entity_id"]
    s["source"] = "manual"
    s["pct_same_day_last_yr"] = pd.NA

    unknown = set(s.entity_id) - set(cap)
    if unknown:
        sys.exit(f"ERROR: seeds reference unknown entities {sorted(unknown)}")

    n = upsert(con, "reservoir_daily",
               s[["reservoir_id", "date", "live_storage_pct", "storage_mcm",
                  "pct_same_day_last_yr", "source"]])
    print(f"[seeds] {n} hand-verified anchor rows loaded")
    for eid, g in s.groupby("entity_id"):
        print(f"        {eid}: {len(g)} anchors, "
              f"{g.date.min().date()} → {g.date.max().date()}, "
              f"{g.live_storage_pct.min():.2f}% – {g.live_storage_pct.max():.2f}%")

    # chain of custody — the whole point of the CSV rewrite. If 'secondhand'
    # ever climbs, somebody is adding numbers without reading the source.
    if "confidence" in s.columns:
        print("[seeds] chain of custody:")
        for conf, g in s.groupby("confidence"):
            print(f"        {conf:<11} {len(g):>2}")
        if "source_url" in s.columns and s.source_url.isna().any():
            print("  WARNING: anchors with no source_url:", file=sys.stderr)
            print(s[s.source_url.isna()][["entity_id", "date"]].to_string(index=False),
                  file=sys.stderr)
    return n


# --------------------------------------------------------------------------
# live scrape
# --------------------------------------------------------------------------
def scrape(url: str) -> pd.DataFrame:
    """Pull name / % full / YoY % out of the WRD page. Regex, deliberately.

    The page is a small HTML table; a full parser buys nothing here. If the
    layout changes this returns 0 rows rather than wrong rows — check the
    printout before trusting it.
    """
    import requests

    html = requests.get(url, timeout=45,
                        headers={"User-Agent": "jalaakar-research/0.1"}).text
    text = re.sub(r"<[^>]+>", "|", html)
    text = re.sub(r"\s+", " ", text)

    rows = []
    for name, rid in NAME_TO_ID.items():
        m = re.search(
            rf"{re.escape(name)}\b(.{{0,400}}?)(\d{{1,3}}(?:\.\d+)?)\s*%",
            text, re.IGNORECASE,
        )
        if not m:
            continue
        seg = m.group(0)
        pcts = [float(x) for x in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", seg)]
        if not pcts:
            continue
        rows.append({
            "reservoir_id": rid,
            "live_storage_pct": pcts[0],
            "pct_same_day_last_yr": pcts[1] if len(pcts) > 1 else None,
        })

    df = pd.DataFrame(rows).drop_duplicates("reservoir_id")
    print(f"[scrape] {url} → {len(df)} water bodies parsed")
    if len(df):
        print(df.to_string(index=False))
    return df


def load_live(con, when: str) -> int:
    frames = []
    for url in (MUM_URL, PUN_URL):
        try:
            frames.append(scrape(url))
        except Exception as e:
            print(f"  [scrape] FAILED {url}: {type(e).__name__}: {e}", file=sys.stderr)
    if not frames or all(len(f) == 0 for f in frames):
        print("  [scrape] nothing parsed — hand-enter into reservoir_seeds.csv instead",
              file=sys.stderr)
        return 0

    df = pd.concat(frames, ignore_index=True).drop_duplicates("reservoir_id")
    cap = capacities()
    df["date"] = pd.Timestamp(when)
    df["storage_mcm"] = (
        df["live_storage_pct"] / 100 * df["reservoir_id"].map(cap) / 1000
    ).round(3)
    df["source"] = "wrd_pravah"

    n = upsert(con, "reservoir_daily", df)
    print(f"[live] {n} rows for {when}")
    return n


# --------------------------------------------------------------------------
# interpolation between anchors — clearly flagged, never overwrites a real row
# --------------------------------------------------------------------------
def interpolate(con) -> int:
    real = read(con,
                "SELECT reservoir_id, date, live_storage_pct, source "
                "FROM reservoir_daily WHERE source IN ('manual','wrd_pravah') "
                "ORDER BY reservoir_id, date")
    if real.empty:
        print("[interp] no anchors — nothing to do")
        return 0

    real["date"] = pd.to_datetime(real["date"])
    cap = capacities()
    out = []

    for rid, g in real.groupby("reservoir_id"):
        if len(g) < 2:
            print(f"  [interp] {rid}: only {len(g)} anchor — skipping "
                  f"(cannot interpolate from a single point)")
            continue
        g = g.sort_values("date").set_index("date")
        full = g["live_storage_pct"].reindex(
            pd.date_range(g.index.min(), g.index.max(), freq="D")
        )
        anchors = full.notna()
        full = full.interpolate(method="time")

        d = pd.DataFrame({
            "reservoir_id": rid,
            "date": full.index,
            "live_storage_pct": full.round(2).values,
        })
        d = d[~anchors.values]                      # never touch a real reading
        d["storage_mcm"] = (d["live_storage_pct"] / 100 * cap[rid] / 1000).round(3)
        d["pct_same_day_last_yr"] = pd.NA
        d["source"] = "interpolated"
        out.append(d)
        print(f"  [interp] {rid}: {len(d)} filled days between "
              f"{g.index.min().date()} and {g.index.max().date()} "
              f"({len(g)} real anchors)")

    if not out:
        return 0
    df = pd.concat(out, ignore_index=True)
    n = upsert(con, "reservoir_daily", df, mode="ignore")   # anchors win
    print(f"[interp] {n} interpolated rows")
    return n


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="scrape today's values (internet)")
    ap.add_argument("--seed", action="store_true", help="load hand-verified anchors")
    ap.add_argument("--interpolate", action="store_true", help="fill between anchors")
    ap.add_argument("--all", action="store_true", help="live + seed + interpolate")
    ap.add_argument("--date", default=None, help="date for --live, default config.today")
    args = ap.parse_args()

    if not (args.live or args.seed or args.interpolate or args.all):
        args.seed = args.interpolate = True   # sensible offline default

    when = args.date or str(cfg.end_date)

    with log_run("04_reservoirs.py") as run:
        total = 0
        with connect() as con:
            load_registry(con)
            if args.live or args.all:
                total += load_live(con, when)
            if args.seed or args.all:
                total += load_seeds(con)
            if args.interpolate or args.all:
                total += interpolate(con)

            print("\n[check] provenance breakdown:")
            for r in con.execute(
                "SELECT source, COUNT(*) n, MIN(date) a, MAX(date) b "
                "FROM reservoir_daily GROUP BY source ORDER BY n DESC"
            ):
                print(f"   {r['source']:<14} {r['n']:>5}  {r['a']} → {r['b']}")

            print("\n[check] the two numbers the demo rests on:")
            for label, rid, d in [
                ("Mumbai, scenario date", "MUM_ALL", cfg.scenario_date),
                ("Mumbai, today",         "MUM_ALL", when),
                ("Pune (Khadakwasla)",    "PUN_KHW", when),
                ("Pune, today",           "PUN_ALL", when),
            ]:
                row = con.execute(
                    "SELECT live_storage_pct, source FROM reservoir_daily "
                    "WHERE reservoir_id=? AND date=?", (rid, str(d))
                ).fetchone()
                if row:
                    print(f"   {label:<24} {row['live_storage_pct']:>6.2f}%  ({row['source']})")
                else:
                    print(f"   {label:<24}   MISSING  ← poster claims a value here")

            run.rows_out = total


if __name__ == "__main__":
    main()
