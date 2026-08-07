"""
A2/A3 — well registry + observations.
Owner: Dev A.

  - normalise district/taluka to Maharashtra's official list
  - reverse-geocode wells missing a taluka from lat/lon
  - derive season from month (see config)
  - is_last_5y = obs_date >= config.dates.last5_start
  - CONFIRM SIGN CONVENTION: level_mbgl is metres BELOW ground level.
    bigger = deeper = worse. Verify before it silently inverts the stress score.
  - write `wells` + `gw_observations` via B's db.py

Done when: SELECT COUNT(*) FROM wells WHERE taluka='Dindori' returns >= 1.
If zero, pick a different demo taluka NOW and tell the poster owner.

Handoff H2 -> B by Fri 20:15: data/interim/mh_wells.csv
  columns: well_id, lat, lon, district, taluka, specific_yield
"""
