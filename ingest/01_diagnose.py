"""
A1 diagnostic — can we transplant specific yield onto the extend_2023 wells?
Owner: Dev A. Read-only, writes nothing.

Two questions:
  1. Is Reference_Sy a per-well measurement or a hydrogeological-zone lookup?
     If few distinct values shared across many wells -> zone lookup -> transplantable.
  2. Are the 277 spine wells a subset of the 2,033 extend wells?
     If yes, the join is exact and we can carry Sy across directly.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
ZIP_PATH = ROOT / CFG["paths"]["raw"] / "figshare" / \
    "Quality_controlled_groundwater_levels_over_India.zip"

BASE = "Quality_controlled_groundwater_levels_over_India/Output/"
SPINE = BASE + "CGWB_India_filtered_GWLs_ref_sy_2000_2022.csv"
EXTEND = BASE + "4_India_GWLs_2000_2024_after_3sigma.csv"


def read(member: str) -> pd.DataFrame:
    with zipfile.ZipFile(ZIP_PATH) as zf, zf.open(member) as fh:
        return pd.read_csv(fh, low_memory=False)


def well_id(df: pd.DataFrame) -> pd.Series:
    key = (df["Latitude"].round(4).astype(str) + "|"
           + df["Longitude"].round(4).astype(str) + "|"
           + df["Station Name"].astype(str).str.strip().str.lower())
    return "MH" + key.map(lambda s: hashlib.md5(s.encode()).hexdigest()[:10])


def mh(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["State"].astype(str).str.strip().str.lower() == "maharashtra"].copy()


spine = mh(read(SPINE))
extend = mh(read(EXTEND))
spine["well_id"] = well_id(spine)
extend["well_id"] = well_id(extend)

print("=" * 78)
print("Q1 — IS Reference_Sy A ZONE LOOKUP?")
print("=" * 78)
sy = spine["Reference_Sy"]
print(f"  {len(spine)} Maharashtra wells, {sy.nunique()} distinct Sy values")
print("\n  value counts:")
print(sy.value_counts().head(15).to_string())

print("\n  Sy by district (nunique per district — 1 means constant within district):")
g = spine.groupby("District")["Reference_Sy"].agg(["nunique", "size", "first"])
print(g.sort_values("size", ascending=False).head(20).to_string())

print("\n  Sy by aquifer type:")
print(spine.groupby("Aquifer Type")["Reference_Sy"]
      .agg(["nunique", "size", "min", "max"]).to_string())

print("\n" + "=" * 78)
print("Q2 — DO SPINE WELLS APPEAR IN EXTEND?")
print("=" * 78)
overlap = set(spine["well_id"]) & set(extend["well_id"])
print(f"  spine wells      : {len(spine)}")
print(f"  extend wells     : {len(extend)}")
print(f"  exact ID overlap : {len(overlap)}  "
      f"({len(overlap)/max(len(spine),1)*100:.1f}% of spine)")

print("\n  spine districts NOT in extend:",
      sorted(set(spine['District']) - set(extend['District'])) or "none")
print("  extend districts NOT in spine:",
      len(set(extend['District']) - set(spine['District'])), "districts")

print("\n" + "=" * 78)
print("Q3 — WHAT DOES DINDORI ACTUALLY LOOK LIKE IN EXTEND?")
print("=" * 78)
d = extend[extend["Tehsil"].astype(str).str.strip().str.lower() == "dindori"]
if d.empty:
    print("  none found")
else:
    cols = ["Station Name", "District", "Village", "Latitude", "Longitude",
            "Type of Well", "Aquifer Type", "Well Depth",
            "Data Available From", "Latest  Data Available"]
    print(d[[c for c in cols if c in d.columns]].to_string(index=False))

    qcols = [c for c in extend.columns
             if c[:3] in ("Jan", "May", "Aug", "Nov") and "-" in c]
    filled = d[qcols].notna().sum(axis=1)
    print(f"\n  readings per Dindori well: min {filled.min()}, "
          f"median {int(filled.median())}, max {filled.max()}")

    recent = [c for c in qcols if c.endswith(("-21", "-22", "-23"))]
    print(f"  readings 2021-2023      : {d[recent].notna().sum(axis=1).tolist()}")

    print("\n  nearest QC'd spine wells (for Sy transplant):")
    if not spine.empty:
        import numpy as np
        for _, row in d.iterrows():
            dist = np.hypot(spine["Latitude"] - row["Latitude"],
                            spine["Longitude"] - row["Longitude"])
            j = dist.idxmin()
            print(f"    {row['Station Name']:<22} -> {spine.at[j,'Station Name']:<22} "
                  f"{spine.at[j,'District']:<14} {dist.min()*111:6.1f} km  "
                  f"Sy={spine.at[j,'Reference_Sy']}")
