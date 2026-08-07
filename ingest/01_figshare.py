"""
A1 — figshare download, inspect, filter Maharashtra, RUN THE GATE.
Owner: Dev A.

Source: Kumar et al. (2025), Sci Data. CC BY 4.0.
DOI 10.6084/m9.figshare.29293877.v3

VERIFIED STRUCTURE (from phase-1 inspection, not assumed):
  Wide format. One row per well. Quarterly columns Jan-00 ... Nov-24.
  CGWB measures 4x/year: Jan, May (pre-monsoon), Aug (monsoon), Nov (post-monsoon).

  Output/CGWB_India_filtered_GWLs_ref_sy_2000_2022.csv       <- SPINE (has Reference_Sy)
  Output/CGWB_India_filtered_Dug_wells_GWLs_ref_sy_2000_2022.csv  <- dug wells only
  Output/4_India_GWLs_2000_2024_after_3sigma.csv             <- EXTEND (adds 2023)

⚠️  'Station Code' IS BROKEN AS AN ID.
    Written to CSV in scientific notation (1.42115E+14), so 15-digit codes were
    truncated. Distinct wells collide: 'Alampur' and 'Amarapuram-pz' both read as
    1.410000e+14. We derive well_id from a hash of rounded lat/lon + station name
    instead — stable across files, so the spine/extend join still works.

⚠️  May-20 and May-21 are 100% NULL. COVID. No pre-monsoon anchor in those years.
⚠️  Nov-23 / May-24 / Aug-24 / Nov-24 are ~empty. Real coverage ends Aug-23.

Usage:
    python ingest/01_figshare.py            # download + filter + gate
    python ingest/01_figshare.py --inspect  # also dump full schema
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())

FILE_ID = 57554464
URL = f"https://ndownloader.figshare.com/files/{FILE_ID}"
EXPECTED_MD5 = "43499153306f16e468c23588d5400c2f"

RAW = ROOT / CFG["paths"]["raw"] / "figshare"
INTERIM = ROOT / CFG["paths"]["interim"]
ZIP_PATH = RAW / "Quality_controlled_groundwater_levels_over_India.zip"

BASE = "Quality_controlled_groundwater_levels_over_India/Output/"
SPINE_ALL = BASE + "CGWB_India_filtered_GWLs_ref_sy_2000_2022.csv"
SPINE_DUG = BASE + "CGWB_India_filtered_Dug_wells_GWLs_ref_sy_2000_2022.csv"
EXTEND = BASE + "4_India_GWLs_2000_2024_after_3sigma.csv"

QCOL = re.compile(r"^(Jan|May|Aug|Nov)-(\d{2})$")
MONTH_NUM = {"Jan": 1, "May": 5, "Aug": 8, "Nov": 11}
MONTH_SEASON = {1: "rabi", 5: "pre_monsoon", 8: "monsoon", 11: "post_monsoon"}

META = ["Station Name", "State", "District", "Tehsil", "Block", "Village",
        "Latitude", "Longitude", "Type of Well", "Aquifer Type", "Well Depth"]

pd.set_option("display.width", 200)


# --------------------------------------------------------------------------- io
def md5sum(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def download() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists() and md5sum(ZIP_PATH) == EXPECTED_MD5:
        print(f"[skip] {ZIP_PATH.name} present, md5 OK")
        return
    print(f"[get ] {URL}")
    r = requests.get(URL, stream=True, timeout=180)
    r.raise_for_status()
    with ZIP_PATH.open("wb") as fh:
        for c in r.iter_content(1 << 16):
            fh.write(c)
    if md5sum(ZIP_PATH) != EXPECTED_MD5:
        sys.exit("[FAIL] md5 mismatch")
    print("[ok  ] md5 verified")


def read_member(name: str) -> pd.DataFrame:
    with zipfile.ZipFile(ZIP_PATH) as zf:
        with zf.open(name) as fh:
            return pd.read_csv(fh, low_memory=False)


# ------------------------------------------------------------------- transform
def make_well_id(df: pd.DataFrame) -> pd.Series:
    """Stable ID from rounded coords + name. Station Code is unusable (see header)."""
    key = (df["Latitude"].round(4).astype(str) + "|"
           + df["Longitude"].round(4).astype(str) + "|"
           + df["Station Name"].astype(str).str.strip().str.lower())
    return "MH" + key.map(lambda s: hashlib.md5(s.encode()).hexdigest()[:10])


def filter_state(df: pd.DataFrame, state: str = "Maharashtra") -> pd.DataFrame:
    s = df["State"].astype(str).str.strip().str.lower()
    return df[s == state.lower()].copy()


def melt_quarterly(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Wide Jan-00..Nov-24 -> long (well_id, obs_date, level_mbgl, season)."""
    qcols = [c for c in df.columns if QCOL.match(c)]
    keep = [c for c in META if c in df.columns] + ["well_id"]
    if "Reference_Sy" in df.columns:
        keep.append("Reference_Sy")

    long = df.melt(id_vars=keep, value_vars=qcols,
                   var_name="period", value_name="level_mbgl")
    long = long.dropna(subset=["level_mbgl"])

    parts = long["period"].str.extract(QCOL)
    month = parts[0].map(MONTH_NUM)
    year = 2000 + parts[1].astype(int)
    # CGWB reads mid-month; day 15 is a defensible convention
    long["obs_date"] = pd.to_datetime(
        dict(year=year, month=month, day=15), errors="coerce")
    long["season"] = month.map(MONTH_SEASON)
    long["source"] = source
    long["is_last_5y"] = long["obs_date"] >= pd.Timestamp(CFG["dates"]["last5_start"])
    return long.drop(columns=["period"])


# ------------------------------------------------------------------------ gate
def summarise(name: str, wide: pd.DataFrame, long: pd.DataFrame) -> dict:
    demo_t = CFG["scenario"]["demo_taluka"].lower()
    tehsil = wide["Tehsil"].astype(str).str.strip().str.lower()
    return {
        "file": name,
        "wells": len(wide),
        "observations": len(long),
        "obs_per_well": round(len(long) / max(len(wide), 1), 1),
        "first_obs": long["obs_date"].min().date() if len(long) else None,
        "last_obs": long["obs_date"].max().date() if len(long) else None,
        "districts": wide["District"].nunique(),
        "tehsils": wide["Tehsil"].nunique(),
        "has_Sy": "Reference_Sy" in wide.columns,
        f"{demo_t}_wells": int((tehsil == demo_t).sum()),
        "last5y_obs": int(long["is_last_5y"].sum()) if len(long) else 0,
    }


def verdict(n: int) -> str:
    if n >= 150:
        return "GREEN  — proceed as written, per-region models viable"
    if n >= 50:
        return "AMBER  — pool into ONE global model with well-ID embedding"
    if n > 0:
        return "RED    — figshare is calibration only, escalate GSDA + synthetic"
    return "STOP   — no wells, fall back to datagovindia + full synthetic"


def main() -> None:
    download()
    INTERIM.mkdir(parents=True, exist_ok=True)

    rows, store = [], {}
    for label, member in (("spine_all", SPINE_ALL),
                          ("spine_dug", SPINE_DUG),
                          ("extend_2023", EXTEND)):
        try:
            wide = read_member(member)
        except KeyError:
            print(f"[warn] not found in zip: {member}")
            continue
        wide = filter_state(wide, CFG["geography"]["state"])
        if wide.empty:
            print(f"[warn] no Maharashtra rows in {label}")
            continue
        wide["well_id"] = make_well_id(wide)
        long = melt_quarterly(wide, source=label)
        store[label] = (wide, long)
        rows.append(summarise(label, wide, long))

    if not rows:
        sys.exit("[FAIL] no Maharashtra data found in any file")

    print("\n" + "=" * 78)
    print("MAHARASHTRA — CANDIDATE FILES")
    print("=" * 78)
    print(pd.DataFrame(rows).to_string(index=False))

    # duplicate-ID sanity: did the hash actually separate wells?
    for label, (wide, _) in store.items():
        dupes = wide["well_id"].duplicated().sum()
        print(f"  {label:<12} duplicate well_ids: {dupes}"
              + ("  <-- INVESTIGATE" if dupes else "  ok"))

    spine_label = "spine_all" if "spine_all" in store else next(iter(store))
    spine_wide, spine_long = store[spine_label]
    n = len(spine_wide)

    print("\n" + "=" * 78)
    print(f"🚦 GATE — Maharashtra wells in {spine_label}: {n}")
    print(f"   {verdict(n)}")
    print("=" * 78)

    demo_t = CFG["scenario"]["demo_taluka"]
    t = spine_wide["Tehsil"].astype(str).str.strip().str.lower()
    hits = int((t == demo_t.lower()).sum())
    print(f"\n{demo_t} wells: {hits}"
          + ("" if hits else "   <-- ZERO. Pick a new demo taluka NOW."))
    if not hits:
        near = (spine_wide[spine_wide["District"].astype(str).str.strip().str.lower()
                           == CFG["scenario"]["demo_district"].lower()]
                .groupby("Tehsil").size().sort_values(ascending=False))
        print(f"\nAlternatives in {CFG['scenario']['demo_district']} district:")
        print(near.head(10).to_string())

    out = INTERIM / "mh_wells_raw.parquet"
    spine_long.to_parquet(out, index=False)
    print(f"\n[write] {out.relative_to(ROOT)}  ({len(spine_long):,} observations)")
    print("\nPaste this whole block back before we move to A2.")


if __name__ == "__main__":
    if "--inspect" in sys.argv:
        from pprint import pprint
        with zipfile.ZipFile(ZIP_PATH) as zf:
            pprint([m.filename for m in zf.infolist() if not m.is_dir()])
    main()
