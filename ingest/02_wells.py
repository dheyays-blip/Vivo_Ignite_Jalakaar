"""
A2 — well registry + observations for Maharashtra.
Owner: Dev A.

DECISIONS LOCKED (Fri 7 Aug, after the A1 gate came back GREEN at 277):
  spine  = 4_India_GWLs_2000_2024_after_3sigma.csv  (2,033 MH wells, 34 districts,
           coverage to Aug-2023, includes Dindori). NOT the 277-well QC'd file,
           which contains zero Nashik wells.
  Sy     = carried exactly for the 277 wells that have it; transplanted by zone
           for the rest. Reference_Sy is a hydrogeological-map lookup, not a
           per-well measurement — only 4 distinct values across all 277 wells
           (0.018 / 0.020 / 0.023 / 0.130), so transplanting is legitimate.
           Every row carries `sy_source` so this is auditable.
  QC     = we re-apply the paper's own criteria, since file 4 is only 3-sigma
           filtered: min readings, >=2 readings/year, no repeated-value runs.

OUTPUTS
  data/interim/mh_wells.csv          <- H2 HANDOFF TO DEV B (due Fri 20:15)
  data/interim/mh_observations.parquet

Usage:  python ingest/02_wells.py
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # so `import ingest.db` works when run directly
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
INTERIM = ROOT / CFG["paths"]["interim"]
ZIP_PATH = ROOT / CFG["paths"]["raw"] / "figshare" / \
    "Quality_controlled_groundwater_levels_over_India.zip"

BASE = "Quality_controlled_groundwater_levels_over_India/Output/"
SPINE = BASE + "4_India_GWLs_2000_2024_after_3sigma.csv"          # 2,033 MH wells
SY_SRC = BASE + "CGWB_India_filtered_GWLs_ref_sy_2000_2022.csv"   # 277 with Sy

QCOL = re.compile(r"^(Jan|May|Aug|Nov)-(\d{2})$")
MONTH_NUM = {"Jan": 1, "May": 5, "Aug": 8, "Nov": 11}
MONTH_SEASON = {1: "rabi", 5: "pre_monsoon", 8: "monsoon", 11: "post_monsoon"}

# QC thresholds — see report at the end of the run for their effect
MIN_READINGS = 40          # of a possible 96 quarterly slots (2000-2023)
MIN_YEAR_COVERAGE = 0.60   # fraction of spanned years with >=2 readings
MAX_REPEAT_RUN = 4         # consecutive identical levels -> data artefact
MAX_PLAUSIBLE_MBGL = 100.0

pd.set_option("display.width", 200)


# --------------------------------------------------------------------------- io
def read(member: str) -> pd.DataFrame:
    with zipfile.ZipFile(ZIP_PATH) as zf, zf.open(member) as fh:
        return pd.read_csv(fh, low_memory=False)


def well_id(df: pd.DataFrame) -> pd.Series:
    """Station Code is corrupt (scientific notation). Hash coords + name instead."""
    key = (df["Latitude"].round(4).astype(str) + "|"
           + df["Longitude"].round(4).astype(str) + "|"
           + df["Station Name"].astype(str).str.strip().str.lower())
    return "MH" + key.map(lambda s: hashlib.md5(s.encode()).hexdigest()[:10])


def only_mh(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["State"].astype(str).str.strip().str.lower() == "maharashtra"].copy()


def clean_name(s: pd.Series) -> pd.Series:
    return (s.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
            .str.title().replace({"Nan": None, "-": None, "": None}))


# --------------------------------------------------------------------- reshape
def to_long(wide: pd.DataFrame) -> pd.DataFrame:
    qcols = [c for c in wide.columns if QCOL.match(c)]
    long = wide.melt(id_vars=["well_id"], value_vars=qcols,
                     var_name="period", value_name="level_mbgl")
    long = long.dropna(subset=["level_mbgl"])
    p = long["period"].str.extract(QCOL)
    month = p[0].map(MONTH_NUM)
    long["obs_date"] = pd.to_datetime(
        dict(year=2000 + p[1].astype(int), month=month, day=15))
    long["season"] = month.map(MONTH_SEASON)
    long["source"] = "figshare"
    long["is_last_5y"] = long["obs_date"] >= pd.Timestamp(CFG["dates"]["last5_start"])
    return long.drop(columns=["period"]).sort_values(["well_id", "obs_date"])


# -------------------------------------------------------------------------- qc
def max_repeat_run(x: np.ndarray) -> int:
    if len(x) == 0:
        return 0
    changed = np.concatenate(([True], x[1:] != x[:-1]))
    return int(np.diff(np.concatenate((np.flatnonzero(changed), [len(x)]))).max())


def run_qc(long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Re-apply the paper's consistency checks. Returns (kept, report)."""
    rows = []
    for wid, g in long.groupby("well_id", sort=False):
        g = g.sort_values("obs_date")
        yrs = g["obs_date"].dt.year
        span = yrs.max() - yrs.min() + 1
        per_year = yrs.value_counts()
        rows.append({
            "well_id": wid,
            "n_obs": len(g),
            "yrs_span": span,
            "yr_cov": (per_year >= 2).sum() / span if span else 0.0,
            "max_run": max_repeat_run(g["level_mbgl"].to_numpy()),
            "min_lvl": g["level_mbgl"].min(),
            "max_lvl": g["level_mbgl"].max(),
        })
    rep = pd.DataFrame(rows)
    rep["fail_readings"] = rep["n_obs"] < MIN_READINGS
    rep["fail_yr_cov"] = rep["yr_cov"] < MIN_YEAR_COVERAGE
    rep["fail_repeat"] = rep["max_run"] >= MAX_REPEAT_RUN
    rep["fail_range"] = (rep["min_lvl"] <= 0) | (rep["max_lvl"] > MAX_PLAUSIBLE_MBGL)
    rep["keep"] = ~(rep.fail_readings | rep.fail_yr_cov
                    | rep.fail_repeat | rep.fail_range)
    return rep[rep["keep"]], rep


# -------------------------------------------------------------------------- sy
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def attach_sy(reg: pd.DataFrame, donors: pd.DataFrame) -> pd.DataFrame:
    """measured -> district_modal -> nearest_well, in that order of preference."""
    reg = reg.merge(
        donors[["well_id", "Reference_Sy"]].rename(
            columns={"Reference_Sy": "specific_yield"}),
        on="well_id", how="left")
    reg["sy_source"] = np.where(reg["specific_yield"].notna(), "measured", None)
    reg["sy_donor_km"] = np.where(reg["specific_yield"].notna(), 0.0, np.nan)

    # district modal, where the district has any donor wells
    dmode = (donors.groupby("district")["Reference_Sy"]
             .agg(lambda s: s.mode().iloc[0]).to_dict())
    need = reg["specific_yield"].isna()
    hit = need & reg["district"].isin(dmode)
    reg.loc[hit, "specific_yield"] = reg.loc[hit, "district"].map(dmode)
    reg.loc[hit, "sy_source"] = "district_modal"

    # nearest donor well for anything still missing (e.g. all of Nashik)
    need = reg["specific_yield"].isna()
    if need.any():
        dl, dn, dsy = (donors["lat"].to_numpy(), donors["lon"].to_numpy(),
                       donors["Reference_Sy"].to_numpy())
        for i in reg.index[need]:
            d = haversine_km(reg.at[i, "lat"], reg.at[i, "lon"], dl, dn)
            j = int(np.argmin(d))
            reg.at[i, "specific_yield"] = dsy[j]
            reg.at[i, "sy_source"] = "nearest_well"
            reg.at[i, "sy_donor_km"] = round(float(d[j]), 1)
    return reg


# -------------------------------------------------------------------- A3 load
def safe_upsert_wells(con, df: pd.DataFrame) -> int:
    """Write `wells` WITHOUT triggering the ON DELETE CASCADE.

    ⚠️  Do not replace this with db.upsert(mode='replace') until B has patched it.
    SQLite's INSERT OR REPLACE is DELETE-then-INSERT. With foreign_keys=ON and
    ON DELETE CASCADE on gw_observations/gw_daily, re-upserting an IDENTICAL
    wells row silently destroys every child row for that well — verified:
    13 observations + 1 daily row went to 0 and 0, with no error raised.

    That would mean any re-run of this script after A4 wipes the entire
    interpolation output. ON CONFLICT DO UPDATE mutates in place instead.

    Remove this once ingest/db.py exposes mode='update'.
    """
    from ingest.db import table_columns, _normalise

    cols = [c for c in table_columns(con, "wells") if c in df.columns]
    setters = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "well_id")
    sql = (f"INSERT INTO wells ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' * len(cols))}) "
           f"ON CONFLICT(well_id) DO UPDATE SET {setters}")
    rows = list(_normalise(df[cols].copy()).itertuples(index=False, name=None))
    con.executemany(sql, rows)
    return len(rows)


def load_sqlite(reg: pd.DataFrame, long: pd.DataFrame) -> None:
    """A3 — load wells + gw_observations. Order matters: FK requires wells first."""
    from ingest.db import connect, upsert, summary, log_run, cfg

    obs = long.rename(columns={"obs_date": "obs_date"}).copy()
    obs["is_last_5y"] = obs["is_last_5y"].astype(int)

    with log_run("02_wells.py", rows_in=len(reg)) as run:
        with connect() as con:
            n_w = safe_upsert_wells(con, reg)
            n_o = upsert(con, "gw_observations", obs)
            run.rows_out = n_w + n_o
            print(f"\n[db] wells            {n_w:,}")
            print(f"[db] gw_observations  {n_o:,}")
            print()
            print(summary(con).to_string(index=False))

            # prove the FK actually resolves — an orphan here means the join is broken
            orphans = con.execute(
                "SELECT COUNT(*) FROM gw_observations o "
                "LEFT JOIN wells w ON w.well_id=o.well_id WHERE w.well_id IS NULL"
            ).fetchone()[0]
            print(f"\n  orphan observations (must be 0): {orphans}")
            if orphans:
                raise SystemExit("[FAIL] observations reference missing wells")

            d = con.execute(
                "SELECT COUNT(*) FROM wells WHERE taluka=?",
                (cfg.demo_taluka,)).fetchone()[0]
            print(f"  {cfg.demo_taluka} wells in DB: {d}")
    print(f"\n[db] {cfg.db_path}")


# ------------------------------------------------------------------------ main
def main() -> None:
    INTERIM.mkdir(parents=True, exist_ok=True)

    wide = only_mh(read(SPINE))
    wide["well_id"] = well_id(wide)
    print(f"[load] {len(wide)} Maharashtra wells from spine")

    long = to_long(wide)
    print(f"[melt] {len(long):,} raw observations")

    kept, rep = run_qc(long)
    print("\n" + "=" * 78)
    print("QC — re-applying the paper's consistency criteria")
    print("=" * 78)
    print(f"  wells in                 {len(rep)}")
    print(f"  fail: < {MIN_READINGS} readings        {rep.fail_readings.sum()}")
    print(f"  fail: year coverage <{MIN_YEAR_COVERAGE:.0%}   {rep.fail_yr_cov.sum()}")
    print(f"  fail: repeat run >= {MAX_REPEAT_RUN}      {rep.fail_repeat.sum()}")
    print(f"  fail: implausible level   {rep.fail_range.sum()}")
    print(f"  --> wells kept            {len(kept)}  "
          f"({len(kept)/len(rep)*100:.1f}%)")

    long = long[long["well_id"].isin(kept["well_id"])].copy()
    print(f"  --> observations kept     {len(long):,} "
          f"({len(long)/len(kept):.1f} per well)")

    # ---- registry
    reg = (wide[wide["well_id"].isin(kept["well_id"])]
           .rename(columns={"Latitude": "lat", "Longitude": "lon",
                            "Station Name": "station_name",
                            "Aquifer Type": "aquifer_type",
                            "Type of Well": "well_type",
                            "Well Depth": "well_depth"})
           .loc[:, ["well_id", "station_name", "lat", "lon", "District", "Tehsil",
                    "Village", "well_type", "aquifer_type", "well_depth"]])
    reg["district"] = clean_name(reg["District"])
    reg["taluka"] = clean_name(reg["Tehsil"])
    reg["village"] = clean_name(reg["Village"])
    reg = reg.drop(columns=["District", "Tehsil", "Village"])
    reg["well_depth"] = pd.to_numeric(reg["well_depth"], errors="coerce")

    donors = only_mh(read(SY_SRC))
    donors["well_id"] = well_id(donors)
    donors = donors.rename(columns={"Latitude": "lat", "Longitude": "lon"})
    donors["district"] = clean_name(donors["District"])
    reg = attach_sy(reg, donors[["well_id", "lat", "lon", "district", "Reference_Sy"]])

    stats = (long.groupby("well_id")
             .agg(n_observations=("obs_date", "size"),
                  first_obs=("obs_date", "min"),
                  last_obs=("obs_date", "max")).reset_index())
    reg = reg.merge(stats, on="well_id", how="left")

    print("\n  specific yield provenance:")
    print(reg.groupby("sy_source")
          .agg(wells=("well_id", "size"),
               median_donor_km=("sy_donor_km", "median")).to_string())

    # ---- sign-convention check: pre-monsoon (May) must be DEEPER than monsoon (Aug)
    print("\n" + "=" * 78)
    print("SIGN CONVENTION — level_mbgl must be metres BELOW ground (bigger = worse)")
    print("=" * 78)
    ms = long.groupby("season")["level_mbgl"].mean()
    print(ms.to_string())
    if "pre_monsoon" in ms and "monsoon" in ms:
        ok = ms["pre_monsoon"] > ms["monsoon"]
        print(f"\n  pre_monsoon ({ms['pre_monsoon']:.2f}) > monsoon "
              f"({ms['monsoon']:.2f})?  {'YES — mbgl confirmed' if ok else 'NO'}")
        if not ok:
            raise SystemExit("[FAIL] sign convention inverted. STOP — fix before A4.")

    # ---- demo taluka
    demo = CFG["scenario"]["demo_taluka"]
    d = reg[reg["taluka"] == demo]
    print(f"\n{demo}: {len(d)} wells after QC")
    if len(d):
        print(d[["station_name", "village", "lat", "lon", "well_type",
                 "specific_yield", "sy_source", "sy_donor_km",
                 "n_observations", "last_obs"]].to_string(index=False))
    else:
        print("  *** ZERO after QC — pick a new demo taluka ***")
        print(reg[reg["district"] == CFG["scenario"]["demo_district"]]
              .groupby("taluka").size().sort_values(ascending=False).head(10).to_string())

    # ---- write
    hand = reg[["well_id", "lat", "lon", "district", "taluka", "specific_yield",
                "sy_source", "village", "aquifer_type", "well_depth",
                "n_observations", "first_obs", "last_obs"]]
    out_csv = INTERIM / "mh_wells.csv"
    hand.to_csv(out_csv, index=False)
    out_pq = INTERIM / "mh_observations.parquet"
    long.to_parquet(out_pq, index=False)

    print("\n" + "=" * 78)
    print(f"[write] {out_csv.relative_to(ROOT)}   {len(hand)} wells   <-- H2 for Dev B")
    print(f"[write] {out_pq.relative_to(ROOT)}   {len(long):,} observations")
    print(f"        date range {long.obs_date.min().date()} -> {long.obs_date.max().date()}")
    print(f"        last-5y observations: {int(long.is_last_5y.sum()):,}")
    print("=" * 78)

    load_sqlite(reg, long)          # A3


if __name__ == "__main__":
    main()
