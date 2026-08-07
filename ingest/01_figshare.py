"""
A1 — figshare download, inspect, filter Maharashtra, RUN THE GATE.
Owner: Dev A.

Source: Sci Data 2025 (IISc) — doi 10.6084/m9.figshare.29293877.v3
32,299 wells -> 2,759 QC'd pan-India, includes specific yield.

Steps:
  1. download + unzip to data/raw/figshare/
  2. inspect: column names, date coverage, state field format
  3. filter state == Maharashtra (see config state_aliases)
  4. COUNT WELLS, COUNT OBSERVATIONS, PRINT MIN/MAX DATE   <-- the gate
  5. write data/interim/mh_wells_raw.parquet

GATE: >=150 green | 50-149 amber | <50 red | 0 stop.
Announce the number to Dev B by Fri 20:15.
"""
