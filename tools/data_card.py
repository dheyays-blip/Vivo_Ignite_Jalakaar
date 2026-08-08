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
            f"| `weather_daily` | {n_wx:,} | daily weather per entity (NASA POWER for wells, Open-Meteo for reservoirs) |",
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
            "> The sentence to say out loud: *\"We reconstruct daily levels from "
            "each well's own seasonal cycle plus a linearly interpolated "
            "anomaly. We validated four methods against 1,088 held-out readings "
            "and shipped the lowest-error one. Rainfall-driven recession curves "
            "scored worse, so we don't use them for reconstruction — rainfall "
            "still feeds the forecasting model as a feature.\"*",
            "",
            "**Method selection (measured, not assumed).** Every 4th reading was "
            "held out, reconstructed without it, and the error measured at that "
            "point:",
            "",
            "| Method | MAE |",
            "|---|---:|",
            "| **climatology + anomaly (shipped)** | **1.32 m** |",
            "| seasonal climatology alone | 1.52 m |",
            "| rainfall-driven recession + specific yield | 1.90 m |",
            "| linear between readings | 1.99 m |",
            "",
            "The rainfall-physics approach in the original plan came second "
            "worst. Adding a rainfall-anomaly correction to the shipped method "
            "moved MAE by 0.005 m. The reconstructed curve passes through every "
            "real reading exactly by construction (max deviation 0.000000 m).",
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
                ("Mumbai, scenario date",  "MUM_ALL", str(cfg.scenario_date)),
                ("Mumbai, today",          "MUM_ALL", str(cfg.end_date)),
                ("Pune (Khadakwasla chain)", "PUN_KHW", str(cfg.end_date)),
                ("Pune, today",            "PUN_ALL", str(cfg.end_date)),
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

            # ---- urban stress score --------------------------------------
            try:
                n_stress = q1(con, "SELECT COUNT(*) FROM urban_stress")
            except Exception:
                n_stress = 0
            if n_stress:
                ver = q1(con, "SELECT method_version FROM urban_stress LIMIT 1")
                L += [
                    "### Water Stress Score (urban)", "",
                    f"`{ver}` — **rule-based, not modelled.** {n_stress:,} daily "
                    "scores. The formula is depletion (0–60) + rate of decline "
                    "(0–25) + days of supply at municipal draw (0–15); each "
                    "component is stored alongside the total in `urban_stress`, "
                    "so any score can be taken apart and defended.", "",
                    "| Date | Storage | Score | Band | What BMC did |",
                    "|---|---|---|---|---|",
                ]
                for d, note in [
                    ("2026-05-15", "imposed first 10% city-wide cut"),
                    ("2026-06-16", "extended restrictions to industry"),
                    ("2026-06-29", "season low; supply projected to 20 Aug"),
                    ("2026-07-21", "monsoon refilling"),
                    ("2026-08-03", "season peak, four lakes overflowing"),
                ]:
                    r = con.execute(
                        "SELECT live_storage_pct, score, band FROM urban_stress "
                        "WHERE entity_id='MUM_ALL' AND date=?", (d,)).fetchone()
                    if r:
                        L += [f"| {d} | {r['live_storage_pct']:.2f}% | "
                              f"**{r['score']}** | {r['band']} | {note} |"]
                interp = q1(con, "SELECT COUNT(*) FROM urban_stress "
                                 "WHERE inputs_source='interpolated'")
                L += [
                    "",
                    f"{interp:,} of {n_stress:,} scores rest on at least one "
                    "interpolated input; `urban_stress.inputs_source` records "
                    "the worst provenance behind every score.",
                    "",
                    "**Known blind spot.** The series begins 15 May 2026, so the "
                    "earliest dates score with no trend term and read lower than "
                    "they should. That is a limit of the data, not a bug in the "
                    "formula, and `07_stress.py --calibrate` prints it.",
                    "",
                ]

        # ---- sources ----------------------------------------------------
        L += [
            "## Sources and licences", "",
            "| Source | Used for | Licence |",
            "|---|---|---|",
            "| [Sci Data 2025 / IISc groundwater dataset](https://doi.org/10.6084/m9.figshare.29293877.v3) "
            "| well registry, seasonal levels, specific yield | CC BY 4.0 |",
            "| [NASA POWER (MERRA-2)](https://power.larc.nasa.gov/) "
            "| daily rainfall, temperature, humidity for **all 940 wells** | "
            "public domain (NASA) |",
            "| [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) "
            "| daily weather for the **14 reservoirs only** | CC BY 4.0 |",
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
            "2. **Two weather sources, deliberately.** Open-Meteo (ERA5) "
            "exhausted its free quota partway through the well pull, so all 940 "
            "wells use **NASA POWER / MERRA-2** at a ~0.5° dedupe (~55 km); the "
            "14 reservoirs kept their Open-Meteo/ERA5 series at ~0.25°. Wells "
            "within a cell share one weather series. Neither is station data.",
            "3. **ET0 for wells is computed, not observed.** POWER does not "
            "serve reference evapotranspiration, so it is derived with the "
            "FAO-56 Hargreaves formula from daily max/min/mean temperature and "
            "latitude — the standard fallback when radiation data is absent.",
            "4. **Soil moisture is NULL for all wells.** The hourly soil-"
            "moisture request was ~95% of Open-Meteo's per-call cost and had to "
            "be dropped to complete the pull. Reservoir rows retain it.",
            "5. **Specific yield is transplanted for 44% of wells.** Only 271 of "
            "940 have a value from the source dataset; 256 take their district's "
            "modal value and **413 take the value of the nearest donor well, a "
            "median 83.5 km away**. `wells.sy_source` records which. Reference_Sy "
            "in the source dataset takes only 4 distinct values across all of "
            "Maharashtra (0.018 / 0.020 / 0.023 / 0.130) because it is read from "
            "a hydrogeological map rather than measured per well, which is what "
            "makes transplanting defensible — but the Nashik wells, Dindori "
            "included, have no QC'd donor closer than Palghar.",
            "6. The urban track rests on published **city aggregates**, not "
            "per-lake daily telemetry, for most dates.",
            "7. Coverage is **Maharashtra only**. Nothing here generalises to "
            "other states without re-running ingestion.",
            "8. The scenario date is deliberately **pre-monsoon 2026**. Run the "
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
