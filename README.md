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
| `tools/validate.py` | **B** | QA gate — exit 0 means safe to freeze |
| `tools/data_card.py` | **B** | `DATA_CARD.md`, generated from the DB |
| `tools/freeze.py` | **B** | `data/FROZEN_<stamp>.db` + tag |

Run it:

```bash
python ingest/01_figshare.py                  # download + the GO/NO-GO gate
python ingest/02_wells.py                     # -> data/interim/mh_wells.csv

python ingest/03_openmeteo.py --source csv --csv data/interim/mh_wells.csv
python ingest/04_reservoirs.py --all
python ingest/03_openmeteo.py --source csv --csv data/interim/reservoirs.csv

python ingest/05_interpolate.py               # the keystone
python ingest/06_features.py

python tools/validate.py                      # exit 0 = safe to freeze
python tools/freeze.py --mae <A's number>
```

940 wells is 817 Open-Meteo calls. Everything caches to `.cache/http` and to
parquet under `data/raw/openmeteo/`, so a re-run costs nothing and never
re-hits the API. Interrupt whenever you like.

Useful flags:

```bash
python ingest/03_openmeteo.py --source stub          # 3 Nashik coords, no dependency on A
python ingest/03_openmeteo.py ... --dry-run          # show the plan, spend zero calls
python ingest/03_openmeteo.py ... --offline          # rebuild from parquet, no network
python ingest/04_reservoirs.py --seed --interpolate  # offline: anchors + fill
python ingest/06_features.py --rural-only            # the Sat 16:00 fallback
JALAAKAR_DB=data/scratch.db python ingest/06_features.py   # any script, throwaway DB
```

## Three rules enforced in code

1. **`is_observed` is sacred.** 1 only on genuine measurement dates.
   `validate.py` fails if it is 0% or implausibly high — without it you cannot
   report honest accuracy.
2. **Splits are chronological**, checked per track. `validate.py` fails the
   build on any overlap or empty split. That check exists because the original
   boundaries silently produced empty val and test sets.
3. **`level_mbgl` is metres *below* ground.** Bigger = deeper = worse. If this
   sign inverts, every stress score inverts with it.

## The scenario date, honestly

The scenario is **30 June 2026**. Groundwater data ends **2023-08-15**.

The rural model is validated on a real **pre-monsoon round inside the test
split** — the same *season* as the scenario, not the same date. `validate.py`
fails if that round is missing, so the claim can't quietly become untrue.

We do **not** claim the model has seen 2026 groundwater data. The urban track
is different: BMC / WRD reporting is current, so 2026 reservoir figures are
directly observed.

## Provenance

Nothing here is unsourced.

- `gw_observations.source` — `figshare` | `gsda` | `synthetic`
- `gw_daily.is_observed` — real reading vs interpolated
- `reservoir_daily.source` — `wrd_pravah` | `manual` | `interpolated`
- `ingest/reservoir_seeds.csv` — every hand-entered anchor cites its source
- `ingest_log` — one row per script run; `DATA_CARD.md` is generated from it

## Testing before real data lands

```bash
JALAAKAR_DB=data/test.db python tools/make_fixtures.py --fabricate-weather
JALAAKAR_DB=data/test.db python ingest/03_openmeteo.py --source stub --offline
JALAAKAR_DB=data/test.db python tools/make_fixtures.py
JALAAKAR_DB=data/test.db python ingest/06_features.py
python tools/make_fixtures.py --clean         # ALWAYS, before any real run
```

Everything `make_fixtures.py` produces is **fake**. It drops a tripwire file in
`data/raw/openmeteo/`, and both `03_openmeteo.py` and `validate.py` refuse to
treat that cache as real while it exists.

## What NOT to say

> ~~"We trained on 5 years of daily GSDA data."~~

Say instead:

> "We anchor on quality-controlled seasonal observations from a peer-reviewed
> IISc dataset and interpolate daily using rainfall-conditioned recession
> curves scaled by each well's specific yield, validated against held-out
> readings at X.XX m MAE."

## File ownership
**Never edit a file you don't own.** Need a change in the other person's file? Message them.
`config.yaml` and `README.md` are shared — agree upfront, then avoid.

## Do not commit
The SQLite DB and weather parquet. They regenerate in ~20 min and binary merge
conflicts will cost an hour nobody has. Git holds code + small reference CSVs.
