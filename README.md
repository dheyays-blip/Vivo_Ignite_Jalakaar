# Jalaakar — data ingestion

Ingestion pipeline for the Jalaakar water-stress forecasting prototype.
Maharashtra only. Demo taluka: Dindori, Nashik. Scenario date: 30 June 2026.

**Freeze: Sat 8 Aug 2026, 20:00 IST.** After that, no new data sources.

## Setup
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Pipeline order
| Script | Owner | Produces |
|---|---|---|
| `ingest/00_schema.sql`, `ingest/db.py` | **B** | SQLite schema + helpers |
| `ingest/01_figshare.py` | **A** | `data/interim/mh_wells_raw.parquet` |
| `ingest/02_wells.py` | **A** | `data/interim/mh_wells.csv`, `wells`, `gw_observations` |
| `ingest/03_openmeteo.py` | **B** | `weather_daily` |
| `ingest/04_reservoirs.py` | **B** | `reservoirs`, `reservoir_daily` |
| `ingest/05_interpolate.py` | **A** | `gw_daily` |
| `ingest/06_features.py` | **B** | `features` |

## File ownership
**Never edit a file you don't own.** Need a change in the other person's file? Message them.
`config.yaml` and `README.md` are shared — agree upfront, then avoid.

## Do not commit
The SQLite DB and weather parquet. They regenerate in ~20 min and binary merge
conflicts will cost an hour nobody has. Git holds code + small reference CSVs.
