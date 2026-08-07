#!/usr/bin/env python3
"""
JALAAKAR — QA sign-off.
Owner: Dev B. This is the gate before the Sat 20:00 freeze.

Runs every check that could embarrass you in front of a judge, prints a
PASS/FAIL per check, and writes three plots to reports/.

    python tools/validate.py
    python tools/validate.py --well SYN000        # plot a specific well
    JALAAKAR_DB=data/test_jalaakar.db python tools/validate.py

Exit code 0 = safe to freeze. Non-zero = do not freeze.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.db import cfg, connect, read, summary, table_count  # noqa: E402

REPORTS = ROOT / "reports"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def warn(name: str, detail: str = ""):
    RESULTS.append((name, True, "WARN: " + detail))
    print(f"  WARN  {name}" + (f"  — {detail}" if detail else ""))


def head(t: str):
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


def q_scenario(con, d: str) -> int:
    return con.execute("SELECT COUNT(*) FROM features WHERE date=? AND "
                       "entity_type='well'", (d,)).fetchone()[0]


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--well", default=None)
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    print(f"DB: {cfg.db_path}")

    marker = ROOT / "data" / "raw" / "openmeteo" / "_SYNTHETIC_DO_NOT_SHIP"
    head("PRE-FLIGHT")
    check("no synthetic weather in the parquet cache", not marker.exists(),
          "" if not marker.exists() else
          f"{marker} exists — fabricated cells from tools/make_fixtures.py are "
          f"in data/raw/openmeteo/. Delete them and the marker; this DB cannot "
          f"be shipped.")
    syn = None
    with connect(readonly=True) as con:
        if table_count(con, "gw_observations"):
            syn = con.execute("SELECT COUNT(*) FROM gw_observations "
                              "WHERE source='synthetic'").fetchone()[0]
        check("no synthetic groundwater observations", not syn,
              "" if not syn else
              f"{syn:,} rows with source='synthetic' — this is a fixture DB, "
              f"not real data")

    with connect(readonly=True) as con:
        head("0. TABLE COUNTS")
        print(summary(con).to_string(index=False))

        # ------------------------------------------------------------------
        head("1. WELLS")
        n_wells = table_count(con, "wells")
        check("wells is populated", n_wells > 0, f"{n_wells} wells")
        if n_wells:
            w = read(con, "SELECT * FROM wells")
            bb = cfg.bbox
            inside = w.lat.between(bb["lat_min"], bb["lat_max"]) & \
                w.lon.between(bb["lon_min"], bb["lon_max"])
            check("all wells inside the Maharashtra bbox", bool(inside.all()),
                  f"{int((~inside).sum())} outside")

            dem = cfg.demo_taluka
            n_demo = int((w.taluka.astype(str).str.lower() == dem.lower()).sum())
            check(f"demo taluka '{dem}' has at least one well", n_demo > 0,
                  f"{n_demo} wells")
            if n_demo == 0:
                print("       >> switch demo_taluka in config.yaml AND tell the "
                      "poster owner — the sample card names it")

            sy = w.specific_yield.dropna()
            if len(sy):
                ok = bool(sy.between(0.001, 0.35).all())
                check("specific_yield physically plausible (0.001–0.35)", ok,
                      f"range {sy.min():.4f}–{sy.max():.4f}")
            else:
                warn("specific_yield missing", "interpolation recharge scaling "
                     "will fall back to a constant")

            print(f"  districts: {w.district.nunique()} | "
                  f"talukas: {w.taluka.nunique()}")

        # ------------------------------------------------------------------
        head("2. GROUNDWATER OBSERVATIONS (real readings)")
        n_obs = table_count(con, "gw_observations")
        check("gw_observations is populated", n_obs > 0, f"{n_obs:,} readings")
        if n_obs:
            o = read(con, "SELECT * FROM gw_observations")
            o["obs_date"] = pd.to_datetime(o["obs_date"])
            print(f"  date range: {o.obs_date.min().date()} → {o.obs_date.max().date()}")

            # The groundwater data ends well before the demo scenario date.
            # We do not pretend otherwise: the rural model is validated on a
            # pre-monsoon round inside the test split, which is the same
            # SEASON as the scenario, not the same date. These checks make
            # sure that story stays true.
            last = o.obs_date.max()
            declared = pd.Timestamp(cfg.gw_end)
            check("last real reading matches dates.gw_end in config",
                  abs((last - declared).days) <= 31,
                  f"data ends {last.date()}, config says {declared.date()}"
                  if abs((last - declared).days) > 31 else f"{last.date()}")

            stale = (pd.Timestamp(cfg.scenario_date) - last).days
            if stale > 400:
                warn("scenario date is far past the last real reading",
                     f"scenario is {cfg.scenario_date}, last reading "
                     f"{last.date()} ({stale} days earlier). This is expected "
                     f"and handled by season-matching, NOT by extrapolation — "
                     f"the test split holds a real pre-monsoon round. Say that "
                     f"before a judge asks.")
            per = o.groupby("well_id").size()
            print(f"  per well: min {per.min()} | median {int(per.median())} | "
                  f"max {per.max()}")
            check("every well has >= 8 real readings", bool((per >= 8).all()),
                  f"{int((per < 8).sum())} wells below 8")
            print("  by source: " + ", ".join(
                f"{k}={v}" for k, v in o.source.value_counts().items()))
            print("  by season: " + ", ".join(
                f"{k}={v}" for k, v in o.season.value_counts().items()))
            share5 = o.is_last_5y.mean()
            print(f"  share flagged last-5-years: {share5:.1%}")
            check("is_last_5y flag is not all-or-nothing",
                  0.0 < share5 < 1.0,
                  f"{share5:.1%} — check last5_start" if not (0 < share5 < 1) else "")

            lv = o.level_mbgl
            check("levels physically plausible (0–100 m bgl)",
                  bool(lv.between(0, 100).all()),
                  f"range {lv.min():.2f}–{lv.max():.2f}")
            if lv.min() < 0:
                print("       >> NEGATIVE mbgl. The sign convention is inverted. "
                      "This silently flips your entire stress score.")

        # ------------------------------------------------------------------
        head("3. DAILY INTERPOLATION (the keystone)")
        n_daily = table_count(con, "gw_daily")
        check("gw_daily is populated", n_daily > 0, f"{n_daily:,} rows")
        if n_daily:
            r = con.execute("SELECT * FROM v_observed_ratio").fetchone()
            print(f"  {r['n_observed']:,} of {r['n_daily_rows']:,} daily rows are "
                  f"REAL readings ({r['pct_observed']}%)")
            check("is_observed is actually being set", (r["n_observed"] or 0) > 0,
                  "" if (r["n_observed"] or 0) > 0 else
                  "zero real readings flagged — A is not setting is_observed, "
                  "so you cannot report honest accuracy")
            check("is_observed is not set on everything",
                  (r["pct_observed"] or 0) < 50,
                  "" if (r["pct_observed"] or 0) < 50 else
                  f"{r['pct_observed']}% flagged real — implausibly high, "
                  f"interpolated rows are being marked as measurements")

            g = read(con, "SELECT well_id, date, level_mbgl, is_observed, "
                          "confidence FROM gw_daily")
            g["date"] = pd.to_datetime(g["date"])
            gaps = (g.sort_values(["well_id", "date"])
                      .groupby("well_id")["date"].diff().dt.days)
            worst = gaps.max()
            check("no calendar gaps inside a well's daily series",
                  bool(pd.isna(worst) or worst <= 1),
                  f"largest gap {worst} days")

            conf = g.confidence.dropna()
            if len(conf):
                check("confidence within [0,1]", bool(conf.between(0, 1).all()),
                      f"range {conf.min():.2f}–{conf.max():.2f}")
                obs_conf = g.loc[g.is_observed == 1, "confidence"].mean()
                int_conf = g.loc[g.is_observed == 0, "confidence"].mean()
                check("confidence is higher on real readings than interpolated",
                      bool(pd.isna(obs_conf) or obs_conf >= int_conf),
                      f"observed {obs_conf:.2f} vs interpolated {int_conf:.2f}")
            else:
                warn("confidence column empty", "decay not implemented yet")

        # ------------------------------------------------------------------
        head("4. WEATHER")
        n_wx = table_count(con, "weather_daily")
        check("weather_daily is populated", n_wx > 0, f"{n_wx:,} rows")
        if n_wx:
            m = read(con, "SELECT CAST(strftime('%m', date) AS INTEGER) month, "
                          "AVG(precip_mm) mean_precip FROM weather_daily "
                          "GROUP BY month ORDER BY month")
            peak = int(m.loc[m.mean_precip.idxmax(), "month"])
            check("monsoon peak falls in Jun–Sep", peak in (6, 7, 8, 9),
                  f"peak month = {peak}")
            if peak not in (6, 7, 8, 9):
                print("       >> your dates or units are wrong. Fix before sleeping.")

            ann = read(con, "SELECT CAST(strftime('%Y', date) AS INTEGER) y, "
                            "well_id, SUM(precip_mm) mm FROM weather_daily "
                            "GROUP BY y, well_id")
            full = ann[ann.y.between(2015, 2025)]
            if len(full):
                med = full.mm.median()
                check("median annual rainfall plausible for Maharashtra "
                      "(400–3000 mm)", 400 <= med <= 3000, f"{med:.0f} mm/yr")

            nulls = con.execute("SELECT COUNT(*) FROM weather_daily "
                                "WHERE precip_mm IS NULL").fetchone()[0]
            check("no null precipitation", nulls == 0, f"{nulls:,} nulls")

            if n_daily:
                orphan = con.execute("""
                    SELECT COUNT(*) FROM gw_daily g
                    LEFT JOIN weather_daily w
                      ON w.well_id = g.well_id AND w.date = g.date
                    WHERE w.well_id IS NULL""").fetchone()[0]
                check("every well-day has weather", orphan == 0,
                      f"{orphan:,} well-days with no weather row")

        # ------------------------------------------------------------------
        head("5. RESERVOIRS (urban track)")
        n_res = table_count(con, "reservoir_daily")
        if n_res == 0:
            warn("reservoir_daily empty", "urban track cut — acceptable per the "
                 "Sat 16:00 fallback")
        else:
            prov = read(con, "SELECT source, COUNT(*) n FROM reservoir_daily "
                             "GROUP BY source")
            print("  provenance: " + ", ".join(
                f"{r.source}={r.n}" for r in prov.itertuples()))
            check("provenance is recorded on every row",
                  bool(prov.source.notna().all()),
                  "rows with NULL source cannot be defended")

            sd = str(cfg.scenario_date)
            row = con.execute("SELECT live_storage_pct, source FROM reservoir_daily "
                              "WHERE reservoir_id='MUM_ALL' AND date=?",
                              (sd,)).fetchone()
            check(f"Mumbai aggregate exists for the scenario date {sd}",
                  row is not None,
                  f"{row['live_storage_pct']}% ({row['source']})" if row else "MISSING")
            if row:
                check("scenario value matches the poster's 6.93%",
                      abs(row["live_storage_pct"] - 6.93) < 0.5,
                      f"{row['live_storage_pct']}%")

            today = str(cfg.end_date)
            hi = con.execute("SELECT reservoir_id, live_storage_pct FROM "
                             "reservoir_daily WHERE date=? AND reservoir_id "
                             "IN ('MUM_ALL','PUN_ALL')", (today,)).fetchall()
            for h in hi:
                check(f"{h['reservoir_id']} is high today (the 'correctly says "
                      f"SAFE' contrast)", h["live_storage_pct"] > 70,
                      f"{h['live_storage_pct']}%")

        # ------------------------------------------------------------------
        head("6. FEATURES — LEAKAGE AND INTEGRITY")
        n_f = table_count(con, "features")
        check("features is populated", n_f > 0, f"{n_f:,} rows")
        if n_f:
            dupes = con.execute(
                "SELECT COUNT(*) FROM (SELECT entity_id, date FROM features "
                "GROUP BY entity_id, date HAVING COUNT(*)>1)").fetchone()[0]
            check("no duplicate (entity_id, date)", dupes == 0, f"{dupes} dupes")

            for c in ["level", "precip_mm", "rain_30d", "level_lag_30",
                      "target_level_t30", "split"]:
                k = con.execute(f"SELECT COUNT(*) FROM features "
                                f"WHERE {c} IS NULL").fetchone()[0]
                check(f"no nulls in {c}", k == 0, f"{k:,} nulls")

            # leakage is checked PER TRACK — the two tracks have different
            # coverage and therefore different split boundaries
            for etype in ("well", "reservoir"):
                sp = read(con, "SELECT split, MIN(date) a, MAX(date) b, "
                               "COUNT(*) n FROM features WHERE entity_type=? "
                               "GROUP BY split", (etype,))
                if sp.empty:
                    continue
                sp = sp.set_index("split")
                print(f"\n  {etype}:")
                print("    " + sp.to_string().replace("\n", "\n    "))
                order = [s for s in ("train", "val", "test") if s in sp.index]
                leak = any(sp.loc[order[i], "b"] >= sp.loc[order[i + 1], "a"]
                           for i in range(len(order) - 1))
                check(f"[{etype}] splits chronological, non-overlapping "
                      f"(NO LEAKAGE)", not leak,
                      "" if not leak else
                      "a random split would look like this and would inflate "
                      "your reported accuracy")

                if etype == "well":
                    check("[well] val and test splits are non-empty",
                          {"val", "test"} <= set(sp.index),
                          "" if {"val", "test"} <= set(sp.index) else
                          "nothing to validate on — the split boundaries are "
                          "outside the data's coverage")
                    if {"train", "test"} <= set(sp.index):
                        ratio = sp.loc["test", "n"] / max(sp.loc["train", "n"], 1)
                        if ratio > 0.6:
                            warn("test split is large relative to train",
                                 f"test/train = {ratio:.2f}")

            # The demo claim is "same season as the scenario", so the test
            # split MUST contain a real pre-monsoon round backed by actual
            # measurements. If it doesn't, the season-matching story is empty.
            pm = con.execute(
                "SELECT COUNT(*) FROM features WHERE split='test' "
                "AND entity_type='well' AND season='pre_monsoon' "
                "AND is_observed=1").fetchone()[0]
            check("test split contains REAL pre-monsoon observations "
                  "(the season-match the demo rests on)", pm > 0,
                  f"{pm:,} observed pre-monsoon rows" if pm else
                  "no measured pre-monsoon row in test — the 'same season as "
                  "30 Jun' claim has nothing behind it. Check splits.test_end "
                  "covers a May round.")

            pm_dates = read(con, "SELECT DISTINCT date FROM features "
                                 "WHERE split='test' AND entity_type='well' "
                                 "AND season='pre_monsoon' AND is_observed=1 "
                                 "ORDER BY date")
            if len(pm_dates):
                print(f"  pre-monsoon rounds in test: "
                      f"{', '.join(pm_dates['date'].head(6))}")

    # ----------------------------------------------------------------------
    if not args.no_plots:
        head("7. PLOTS")
        try:
            make_plots(args.well)
        except Exception as e:
            warn("plots", f"{type(e).__name__}: {e}")

    # ----------------------------------------------------------------------
    head("SUMMARY")
    fails = [r for r in RESULTS if not r[1]]
    warns = [r for r in RESULTS if r[1] and r[2].startswith("WARN")]
    print(f"  {len(RESULTS) - len(fails)} passed, {len(fails)} failed, "
          f"{len(warns)} warnings")
    if fails:
        print("\n  FAILED CHECKS — do not freeze until these are green:")
        for n, _, d in fails:
            print(f"    - {n}" + (f" ({d})" if d else ""))
        return 1
    print("\n  QA SIGN-OFF: OK to freeze.")
    return 0


# --------------------------------------------------------------------------
def make_plots(well: str | None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with connect(readonly=True) as con:
        # 1. monsoon signal
        m = read(con, "SELECT CAST(strftime('%m', date) AS INTEGER) month, "
                      "AVG(precip_mm) mm FROM weather_daily GROUP BY month")
        if len(m):
            fig, ax = plt.subplots(figsize=(7, 3.2))
            ax.bar(m.month, m.mm, color=["#9aa7b1"] * 5 + ["#2b7fd4"] * 4 +
                   ["#9aa7b1"] * 3)
            ax.set_title("Mean daily rainfall by month — spike MUST be Jun–Sep")
            ax.set_xlabel("month"); ax.set_ylabel("mm/day")
            ax.set_xticks(range(1, 13))
            fig.tight_layout(); fig.savefig(REPORTS / "monsoon_check.png", dpi=130)
            plt.close(fig)
            print(f"  wrote {REPORTS / 'monsoon_check.png'}")

        # 2. one well: interpolated curve + real readings
        if table_count(con, "gw_daily"):
            if not well:
                well = con.execute(
                    "SELECT well_id FROM gw_daily GROUP BY well_id "
                    "ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
            g = read(con, "SELECT date, level_mbgl, is_observed, confidence "
                          "FROM gw_daily WHERE well_id=? ORDER BY date", (well,))
            g["date"] = pd.to_datetime(g["date"])
            fig, ax = plt.subplots(figsize=(11, 4))
            ax.plot(g.date, g.level_mbgl, lw=0.9, color="#2b7fd4",
                    label="interpolated daily")
            o = g[g.is_observed == 1]
            ax.scatter(o.date, o.level_mbgl, s=26, color="#d94b2b", zorder=5,
                       label=f"real readings (n={len(o)})")
            ax.invert_yaxis()
            ax.set_title(f"{well} — water level (m below ground; down = wetter)")
            ax.set_ylabel("m bgl"); ax.legend(loc="best", fontsize=8)
            fig.tight_layout(); fig.savefig(REPORTS / "well_curve.png", dpi=130)
            plt.close(fig)
            print(f"  wrote {REPORTS / 'well_curve.png'}  (well {well})")

        # 3. Mumbai 2026 storage with provenance
        if table_count(con, "reservoir_daily"):
            r = read(con, "SELECT date, live_storage_pct, source FROM "
                          "reservoir_daily WHERE reservoir_id='MUM_ALL' "
                          "ORDER BY date")
            if len(r):
                r["date"] = pd.to_datetime(r["date"])
                fig, ax = plt.subplots(figsize=(9, 3.6))
                ax.plot(r.date, r.live_storage_pct, lw=1.2, color="#9aa7b1",
                        label="interpolated")
                real = r[r.source.isin(["manual", "wrd_pravah"])]
                ax.scatter(real.date, real.live_storage_pct, s=34,
                           color="#d94b2b", zorder=5,
                           label=f"published readings (n={len(real)})")
                ax.axhline(6.93, ls="--", lw=0.8, color="#444")
                ax.set_title("Mumbai lakes 2026 — 6.93% on 30 Jun → ~90% by Aug")
                ax.set_ylabel("% live storage"); ax.legend(fontsize=8)
                fig.tight_layout()
                fig.savefig(REPORTS / "mumbai_2026.png", dpi=130)
                plt.close(fig)
                print(f"  wrote {REPORTS / 'mumbai_2026.png'}")


if __name__ == "__main__":
    sys.exit(main())
