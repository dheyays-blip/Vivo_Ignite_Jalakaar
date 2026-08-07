#!/usr/bin/env python3
"""
JALAAKAR — SYNTHETIC TEST FIXTURES. NOT DATA.
Owner: Dev B.

Fabricates plausible wells / observations / gw_daily so Dev B's pipeline
(03 → 04 → 06 → validate) can be proven end-to-end BEFORE Dev A's real
handoff lands. Nothing produced here is real. It writes to a scratch DB and
refuses to touch data/jalaakar.db.

    python tools/make_fixtures.py                    # -> data/test_jalaakar.db
    JALAAKAR_DB=data/test_jalaakar.db python ingest/06_features.py

Delete data/test_jalaakar.db before the freeze. It must never be shipped.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TEST_DB = ROOT / "data" / "test_jalaakar.db"
os.environ["JALAAKAR_DB"] = str(TEST_DB)

sys.path.insert(0, str(ROOT))
from ingest.db import (  # noqa: E402
    cfg, connect, read, season_series, summary, upsert,
)

N_WELLS = 12
SEED = 20260807
MARKER = "_SYNTHETIC_DO_NOT_SHIP"


def fabricate_parquet(pts: pd.DataFrame, label: str,
                      start="2014-09-03", end="2026-08-07"):
    """TEST ONLY. Writes plausible ERA5-shaped parquet cells so the offline
    path of 03_openmeteo.py can be exercised without internet. Real runs
    overwrite these with genuine Open-Meteo responses."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "om", ROOT / "ingest" / "03_openmeteo.py")
    om = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(om)
    om.RAW_DIR.mkdir(parents=True, exist_ok=True)

    prec = cfg.coord_precision
    cells = {(round(round(r.lat / prec) * prec, 4),
              round(round(r.lon / prec) * prec, 4))
             for r in pts.itertuples()}

    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(SEED)
    made = 0
    for lat, lon in cells:
        p = om.cell_path(lat, lon)
        if p.exists():
            continue
        doy = dates.dayofyear
        monsoon = np.exp(-((doy - 210) / 45.0) ** 2)
        precip = rng.gamma(0.4, 1.0, len(dates)) * (0.6 + 40 * monsoon)
        pd.DataFrame({
            "date": dates, "precip_mm": precip.round(2),
            "et0_mm": (5.5 - 2.2 * monsoon + rng.normal(0, .3, len(dates))).round(2),
            "soil_moist_0_7": (0.08 + 0.22 * monsoon).round(3),
            "soil_moist_7_28": (0.11 + 0.17 * monsoon).round(3),
            "temp_max": (36 - 8 * monsoon + rng.normal(0, 1, len(dates))).round(1),
            "rh_mean": (40 + 45 * monsoon).round(1),
        }).to_parquet(p, index=False)
        made += 1
        # leave a tripwire: every downstream script refuses to trust this dir
        with open(om.RAW_DIR / MARKER, "a") as fh:
            fh.write(p.name + "\n")
    print(f"[fixtures] fabricated {made} synthetic weather cells from {label}")
    if made:
        print(f"[fixtures] wrote tripwire {om.RAW_DIR / MARKER} — "
              f"03_openmeteo.py and validate.py will now refuse to treat this "
              f"cache as real. Delete the .parquet files it lists, and the "
              f"marker, before any real run.")


def clean():
    """Remove every synthetic artifact. Run before any real ingest."""
    raw = ROOT / "data" / "raw" / "openmeteo"
    marker = raw / MARKER
    removed = 0
    if marker.exists():
        for name in marker.read_text().split():
            f = raw / name
            if f.exists():
                f.unlink()
                removed += 1
        marker.unlink()
    for db in (ROOT / "data").glob("test_*.db*"):
        db.unlink()
        removed += 1
    print(f"[clean] removed {removed} synthetic artifacts")
    print("[clean] the parquet cache and scratch DBs are now safe for a real run")


def main():
    if "--clean" in sys.argv:
        clean()
        return
    if "--fabricate-weather" in sys.argv:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "om", ROOT / "ingest" / "03_openmeteo.py")
        om = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(om)

        fabricate_parquet(om.STUB_WELLS[["lat", "lon"]], "stub Nashik coords")
        for name in ("reservoirs.csv", "mh_wells.csv"):
            csv = ROOT / "data" / "interim" / name
            if csv.exists():
                fabricate_parquet(pd.read_csv(csv)[["lat", "lon"]], name)
            else:
                print(f"[fixtures] {name} not present — skipping")
        return
    if TEST_DB.name == "jalaakar.db":
        sys.exit("refusing to write to the real DB")
    rng = np.random.default_rng(SEED)

    with connect() as con:
        # ---- weather must already exist (run 03_openmeteo.py first) --------
        wx = read(con, "SELECT * FROM weather_daily ORDER BY well_id, date")
        if wx.empty:
            sys.exit("weather_daily is empty — run ingest/03_openmeteo.py first "
                     f"with JALAAKAR_DB={TEST_DB}")
        wx["date"] = pd.to_datetime(wx["date"])
        stub_ids = sorted(wx.well_id.unique())
        print(f"[fixtures] borrowing real weather from {len(stub_ids)} grid points")

        dates = pd.date_range(wx.date.min(), wx.date.max(), freq="D")

        wells, obs, daily = [], [], []
        for i in range(N_WELLS):
            wid = f"SYN{i:03d}"
            src = stub_ids[i % len(stub_ids)]
            w = wx[wx.well_id == src].set_index("date").reindex(dates)
            rain = w["precip_mm"].fillna(0).to_numpy()
            et0 = w["et0_mm"].fillna(4.0).to_numpy()

            sy = float(rng.uniform(0.02, 0.14))          # specific yield
            base = float(rng.uniform(4.0, 16.0))         # mean depth, mbgl
            level = np.empty(len(dates))
            level[0] = base
            for t in range(1, len(dates)):
                recharge = rain[t] * sy * 0.06           # rain lifts water up
                recession = et0[t] * 0.004               # dry days push it down
                pull = 0.0012 * (base - level[t - 1])    # return to equilibrium
                level[t] = level[t - 1] - recharge + recession + pull
            level = np.clip(level + rng.normal(0, 0.01, len(dates)), 0.4, 60)

            # sparse seasonal observations: 4 per year, Jan/May/Aug/Nov
            mask = pd.Series(dates).dt.month.isin([1, 5, 8, 11]).to_numpy() & \
                (pd.Series(dates).dt.day == 15).to_numpy()
            odates = dates[mask]
            olevels = level[mask] + rng.normal(0, 0.05, mask.sum())

            wells.append({
                "well_id": wid,
                "lat": round(float(19.9 + rng.uniform(0, 0.5)), 4),
                "lon": round(float(73.7 + rng.uniform(0, 0.5)), 4),
                "district": "Nashik",
                "taluka": rng.choice(["Dindori", "Niphad", "Nashik"]),
                "village": f"SynVillage{i}",
                "specific_yield": round(sy, 4),
                "aquifer_type": "basalt",
                "n_observations": int(mask.sum()),
                "first_obs": odates.min().strftime("%Y-%m-%d"),
                "last_obs": odates.max().strftime("%Y-%m-%d"),
            })
            obs.append(pd.DataFrame({
                "well_id": wid, "obs_date": odates,
                "level_mbgl": olevels.round(3),
                "season": season_series(pd.Series(odates)).to_numpy(),
                "source": "synthetic",
                "is_last_5y": (odates >= pd.Timestamp(cfg.last5_start)).astype(int),
            }))
            dist = np.full(len(dates), 999.0)
            oi = np.flatnonzero(mask)
            for j in range(len(dates)):
                dist[j] = np.min(np.abs(oi - j)) if len(oi) else 999
            daily.append(pd.DataFrame({
                "well_id": wid, "date": dates,
                "level_mbgl": level.round(3),
                "is_observed": mask.astype(int),
                "confidence": np.clip(1.0 - dist / 180.0, 0.15, 1.0).round(3),
            }))

        # fan the stub weather out onto each synthetic well_id, exactly as
        # 03_openmeteo.py does for real wells
        wxf = []
        for i in range(N_WELLS):
            src = stub_ids[i % len(stub_ids)]
            f = wx[wx.well_id == src].copy()
            f["well_id"] = f"SYN{i:03d}"
            wxf.append(f)
        nw = upsert(con, "weather_daily", pd.concat(wxf, ignore_index=True))
        print(f"[fixtures] weather_daily fan-out: {nw:,} rows")

        n1 = upsert(con, "wells", pd.DataFrame(wells))
        n2 = upsert(con, "gw_observations", pd.concat(obs, ignore_index=True))
        n3 = upsert(con, "gw_daily", pd.concat(daily, ignore_index=True))
        print(f"[fixtures] wells={n1}  gw_observations={n2:,}  gw_daily={n3:,}")
        print(summary(con).to_string(index=False))
        print(f"\nScratch DB: {TEST_DB}")
        print("SYNTHETIC — delete before the freeze.")


if __name__ == "__main__":
    main()
