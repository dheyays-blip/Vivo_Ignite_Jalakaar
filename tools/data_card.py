#!/usr/bin/env python3
"""
JALAAKAR — generate DATA_CARD.md from the frozen database.
Owner: Dev B.

The card is GENERATED, never hand-written, so the numbers in it cannot drift
from the numbers in the DB. Run it last, right before the freeze.

    python tools/data_card.py                 # -> DATA_CARD.md
    python tools/data_card.py --out /tmp/x.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import cfg, connect, read, table_count  # noqa: E402


def q1(con, sql, params=()):
    r = con.execute(sql, params).fetchone()
    return r[0] if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "DATA_CARD.md"))
    ap.add_argument("--mae", default=None,
                    help="interpolation MAE from Dev A (task A5), e.g. 0.42")
    args = ap.parse_args()
    L: list[str] = []

    with connect(readonly=True) as con:
        n_wells = table_count(con, "wells")
        n_obs = table_count(con, "gw_observations")
        n_daily = table_count(con, "gw_daily")
        n_wx = table_count(con, "weather_daily")
        n_res = table_count(con, "reservoir_daily")
        n_feat = table_count(con, "features")

        L += [
            "# JALAAKAR — DATA CARD",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"· **Source DB:** `{cfg.db_path.name}`",
            f"**Demo taluka:** {cfg.demo_taluka}, {cfg.demo_district}",
            "",
            f"**Scenario date:** {cfg.scenario_date} (pre-monsoon)",
            "",
            "## Season matching — say this before a judge asks",
            "",
            f"The scenario date is **{cfg.scenario_date}**. The groundwater "
            f"dataset's last real reading is **{cfg.gw_end}**. Those are not "
            f"the same period, and we do not pretend they are.",
            "",
            "The rural model is validated on a **real pre-monsoon round inside "
            "the test split** — the same *season* as the scenario, not the "
            "same date. Seasonal groundwater behaviour is what the model "
            "learns; a pre-monsoon low in one year is the same hydrological "
            "regime as a pre-monsoon low in another.",
            "",
            "What we do NOT claim: that the model has seen 2026 groundwater "
            "data, or that a 2026 rural number is a validated forecast. "
            "Extrapolating three years past the last measurement and calling "
            "it a 30-day forecast is the one move that would turn an honest "
            "system into an overclaim.",
            "",
            "The urban track is different: BMC / WRD reporting is current, so "
            "the 2026 reservoir figures are directly observed, not modelled.",
            "",
            "This file is generated from the database by `tools/data_card.py`. "
            "Do not edit it by hand — regenerate it.",
            "",
            "## What is in here",
            "",
            "| Table | Rows | What it is |",
            "|---|---:|---|",
            f"| `wells` | {n_wells:,} | rural well registry |",
            f"| `gw_observations` | {n_obs:,} | **real measured** groundwater readings |",
            f"| `gw_daily` | {n_daily:,} | daily levels, real + interpolated |",
            f"| `weather_daily` | {n_wx:,} | Open-Meteo daily weather per entity |",
            f"| `reservoir_daily` | {n_res:,} | urban storage, real + interpolated |",
            f"| `features` | {n_feat:,} | final joined training table |",
            "",
        ]

        # ---- honesty section -------------------------------------------
        L += ["## Real vs interpolated — read this first", ""]
        if n_daily:
            r = con.execute("SELECT * FROM v_observed_ratio").fetchone()
            L += [
                f"- **{r['n_observed']:,} of {r['n_daily_rows']:,} daily "
                f"groundwater rows ({r['pct_observed']}%) are genuine "
                f"measurements.** The rest are interpolated.",
                "- `gw_daily.is_observed` separates the two. Every accuracy "
                "number must be computed against `is_observed = 1` rows only.",
            ]
        if args.mae:
            L += [f"- **Interpolation MAE (held-out every 4th observation): "
                  f"{args.mae} m.**"]
        else:
            L += ["- **Interpolation MAE: NOT YET RECORDED.** Dev A owes this "
                  "(task A5). Re-run with `--mae <value>` before the freeze."]
        if n_res:
            prov = read(con, "SELECT source, COUNT(*) n FROM reservoir_daily "
                             "GROUP BY source ORDER BY n DESC")
            L += ["- Urban rows carry `reservoir_daily.source`: " +
                  ", ".join(f"`{r.source}` {r.n}" for r in prov.itertuples()) + "."]
        L += [
            "",
            "> The sentence to say out loud: *\"We anchor on quality-controlled "
            "seasonal observations and interpolate daily using rainfall-"
            "conditioned recession curves scaled by each well's specific yield, "
            "validated against held-out readings.\"*",
            "",
            "> Never say: *\"we trained on 5 years of daily GSDA data.\"*",
            "",
        ]

        # ---- coverage ---------------------------------------------------
        L += ["## Coverage", ""]
        if n_obs:
            a = q1(con, "SELECT MIN(obs_date) FROM gw_observations")
            b = q1(con, "SELECT MAX(obs_date) FROM gw_observations")
            per = read(con, "SELECT well_id, COUNT(*) n FROM gw_observations "
                            "GROUP BY well_id")
            L += [
                f"- Groundwater observations span **{a} → {b}**.",
                f"- Per well: min {per.n.min()}, median {int(per.n.median())}, "
                f"max {per.n.max()} readings.",
                f"- Flagged last-5-years (`is_last_5y`, from "
                f"{cfg.last5_start}): "
                f"{q1(con, 'SELECT SUM(is_last_5y) FROM gw_observations'):,} "
                f"readings.",
            ]
            src = read(con, "SELECT source, COUNT(*) n FROM gw_observations "
                            "GROUP BY source")
            L += ["- By source: " + ", ".join(
                f"`{r.source}` {r.n:,}" for r in src.itertuples()) + "."]
            d = read(con, "SELECT district, COUNT(*) n FROM wells "
                          "GROUP BY district ORDER BY n DESC")
            if len(d):
                L += [f"- Districts covered: {len(d)} "
                      f"({', '.join(f'{r.district} ({r.n})' for r in d.head(6).itertuples())}"
                      f"{'…' if len(d) > 6 else ''})."]
                n_demo = q1(con, "SELECT COUNT(*) FROM wells WHERE LOWER(taluka)=?",
                            (cfg.demo_taluka.lower(),))
                L += [f"- Wells in the demo taluka **{cfg.demo_taluka}**: "
                      f"**{n_demo}**." +
                      ("  ⚠️ zero — the poster names this taluka." if not n_demo else "")]
        if n_wx:
            a = q1(con, "SELECT MIN(date) FROM weather_daily")
            b = q1(con, "SELECT MAX(date) FROM weather_daily")
            L += [f"- Weather spans **{a} → {b}** across "
                  f"{q1(con, 'SELECT COUNT(DISTINCT well_id) FROM weather_daily')} "
                  f"entities."]
        L += [""]

        # ---- splits -----------------------------------------------------
        if n_feat:
            L += ["## Splits — chronological, never random", ""]
            for et, label in (("well", "Rural (wells)"),
                              ("reservoir", "Urban (reservoirs)")):
                sp = read(con, "SELECT split, COUNT(*) n, MIN(date) a, "
                               "MAX(date) b, COUNT(DISTINCT entity_id) e "
                               "FROM features WHERE entity_type=? "
                               "GROUP BY split ORDER BY a", (et,))
                if sp.empty:
                    continue
                L += [f"**{label}**", "",
                      "| Split | Rows | From | To | Entities |",
                      "|---|---:|---|---|---:|"]
                L += [f"| {r.split} | {r.n:,} | {r.a} | {r.b} | {r.e} |"
                      for r in sp.itertuples()]
                L += [""]
            L += ["The urban track is labelled entirely `test`: it is never "
                  "trained on, so it cannot leak into a training set.", ""]
            L += [
                "",
                f"Target is level at **t+{cfg.horizon} days**. "
                f"A random split would leak the future into training and "
                f"inflate reported accuracy; these splits are strictly ordered "
                f"in time, and `tools/validate.py` fails the build if they ever "
                f"overlap.",
                "",
            ]

        # ---- reservoirs -------------------------------------------------
        if n_res:
            L += ["## Urban track", ""]
            for label, rid, d in [
                ("Mumbai, scenario date", "MUM_ALL", str(cfg.scenario_date)),
                ("Mumbai, today",         "MUM_ALL", str(cfg.end_date)),
                ("Pune, today",           "PUN_ALL", str(cfg.end_date)),
            ]:
                row = con.execute("SELECT live_storage_pct, source FROM "
                                  "reservoir_daily WHERE reservoir_id=? AND date=?",
                                  (rid, d)).fetchone()
                if row:
                    L += [f"- **{label} ({d}): {row['live_storage_pct']}%** "
                          f"(`{row['source']}`)"]
            L += [
                "",
                "The urban series covers roughly one season of publicly "
                "reported aggregates. It is sufficient for the demo narrative "
                "and the stress score; it is **not** enough to claim a trained "
                "urban forecast.",
                "",
            ]

        # ---- sources ----------------------------------------------------
        L += [
            "## Sources and licences", "",
            "| Source | Used for | Licence |",
            "|---|---|---|",
            "| [Sci Data 2025 / IISc groundwater dataset](https://doi.org/10.6084/m9.figshare.29293877.v3) "
            "| well registry, seasonal levels, specific yield | CC BY 4.0 |",
            "| [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) "
            "| daily rainfall, ET0, soil moisture, temperature, humidity | CC BY 4.0 |",
            "| [Mumbai lake & Pune dam levels](https://www.mumbailakewaterlevel.in/) "
            "(Maharashtra WRD / BMC Hydraulic Engineer's Dept) | urban storage | public reporting |",
            "| [GSDA / MRSAC State WRIS](http://mrsac.maharashtra.gov.in/nhpgis/) "
            "| optional telemetry (Appendix A) | public government data |",
            "",
            "Total data cost: **₹0**.",
            "",
        ]

        # ---- limitations ------------------------------------------------
        L += [
            "## Known limitations", "",
            "1. Groundwater readings are **seasonal, not daily**. Daily values "
            "are modelled. `is_observed` tells you which is which.",
            "2. Weather is ERA5 reanalysis on a ~0.1° grid, not station data. "
            "Coordinates are deduped to that grid, so nearby wells share a "
            "weather series.",
            "3. The urban track rests on published **city aggregates**, not "
            "per-lake daily telemetry, for most dates.",
            "4. Coverage is **Maharashtra only**. Nothing here generalises to "
            "other states without re-running ingestion.",
            "5. The scenario date is deliberately **pre-monsoon 2026**. Run the "
            "model on today's data and it should return SAFE — the reservoirs "
            "are full. That contrast is the point, not a bug.",
            "",
        ]

        # ---- run log ----------------------------------------------------
        if table_count(con, "ingest_log"):
            lg = read(con, "SELECT script, started_at, rows_in, rows_out, status "
                           "FROM ingest_log ORDER BY run_id DESC LIMIT 12")
            L += [
                "## Last ingest runs", "",
                "| Script | Started | Rows in | Rows out | Status |",
                "|---|---|---:|---:|---|",
            ]
            L += [f"| `{r.script}` | {r.started_at} | "
                  f"{'' if pd.isna(r.rows_in) else f'{int(r.rows_in):,}'} | "
                  f"{'' if pd.isna(r.rows_out) else f'{int(r.rows_out):,}'} | "
                  f"{r.status} |" for r in lg.itertuples()]
            L += [""]

    out = Path(args.out)
    out.write_text("\n".join(L))
    print(f"wrote {out}  ({len(L)} lines)")


if __name__ == "__main__":
    main()
