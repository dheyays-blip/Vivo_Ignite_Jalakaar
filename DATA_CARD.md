# JALAAKAR — DATA CARD

**Generated:** 2026-08-08 01:04 · **Source DB:** `FROZEN_20260808_0103.db`
**Demo taluka:** Dindori, Nashik

**Scenario date:** 2026-06-30 (pre-monsoon)

## Season matching — say this before a judge asks

The scenario date is **2026-06-30**. The groundwater dataset's last real reading is **2023-08-15**. Those are not the same period, and we do not pretend they are.

The rural model is validated on a **real pre-monsoon round inside the test split** — the same *season* as the scenario, not the same date. Seasonal groundwater behaviour is what the model learns; a pre-monsoon low in one year is the same hydrological regime as a pre-monsoon low in another.

What we do NOT claim: that the model has seen 2026 groundwater data, or that a 2026 rural number is a validated forecast. Extrapolating three years past the last measurement and calling it a 30-day forecast is the one move that would turn an honest system into an overclaim.

The urban track is different: BMC / WRD reporting is current, so the 2026 reservoir figures are directly observed, not modelled.

This file is generated from the database by `tools/data_card.py`. Do not edit it by hand — regenerate it.

## What is in here

| Table | Rows | What it is |
|---|---:|---|
| `wells` | 940 | rural well registry |
| `gw_observations` | 68,994 | **real measured** groundwater readings |
| `gw_daily` | 3,250,606 | daily levels, real + interpolated |
| `weather_daily` | 3,858,146 | daily weather per entity (NASA POWER for wells, Open-Meteo for reservoirs) |
| `reservoir_daily` | 86 | urban storage, real + interpolated |
| `features` | 3,194,786 | final joined training table |

## Real vs interpolated — read this first

- **28,717 of 3,250,606 daily groundwater rows (0.88%) are genuine measurements.** The rest are interpolated.
- `gw_daily.is_observed` separates the two. Every accuracy number must be computed against `is_observed = 1` rows only.
- **Interpolation MAE: NOT YET RECORDED.** Dev A owes this (task A5). Re-run with `--mae <value>` before the freeze.
- Urban rows carry `reservoir_daily.source`: `interpolated` 77, `manual` 9.

> The sentence to say out loud: *"We reconstruct daily levels from each well's own seasonal cycle plus a linearly interpolated anomaly. We validated four methods against 1,088 held-out readings and shipped the lowest-error one. Rainfall-driven recession curves scored worse, so we don't use them for reconstruction — rainfall still feeds the forecasting model as a feature."*

**Method selection (measured, not assumed).** Every 4th reading was held out, reconstructed without it, and the error measured at that point:

| Method | MAE |
|---|---:|
| **climatology + anomaly (shipped)** | **1.32 m** |
| seasonal climatology alone | 1.52 m |
| rainfall-driven recession + specific yield | 1.90 m |
| linear between readings | 1.99 m |

The rainfall-physics approach in the original plan came second worst. Adding a rainfall-anomaly correction to the shipped method moved MAE by 0.005 m. The reconstructed curve passes through every real reading exactly by construction (max deviation 0.000000 m).

> Never say: *"we trained on 5 years of daily GSDA data."*

## Coverage

- Groundwater observations span **2000-01-15 → 2023-08-15**.
- Per well: min 40, median 79, max 87 readings.
- Flagged last-5-years (`is_last_5y`, from 2018-08-01): 11,572 readings.
- By source: `figshare` 68,994.
- Districts covered: 34 (Chandrapur (52), Solapur (51), Yavatmal (50), Amravati (47), Nashik (44), Ratnagiri (43)…).
- Wells in the demo taluka **Dindori**: **4**.
- Weather spans **2012-09-03 → 2026-08-07** across 954 entities.

## Splits — chronological, never random

**Rural (wells)**

| Split | Rows | From | To | Entities |
|---|---:|---|---|---:|
| train | 2,501,667 | 2013-01-31 | 2020-11-30 | 930 |
| val | 478,918 | 2020-12-01 | 2022-06-30 | 837 |
| test | 214,176 | 2022-07-01 | 2023-07-16 | 821 |

**Urban (reservoirs)**

| Split | Rows | From | To | Entities |
|---|---:|---|---|---:|
| test | 25 | 2026-06-14 | 2026-07-08 | 1 |

The urban track is labelled entirely `test`: it is never trained on, so it cannot leak into a training set.


Target is level at **t+30 days**. A random split would leak the future into training and inflate reported accuracy; these splits are strictly ordered in time, and `tools/validate.py` fails the build if they ever overlap.

## Urban track

- **Mumbai, scenario date (2026-06-30): 6.93%** (`manual`)
- **Mumbai, today (2026-08-07): 88.5%** (`manual`)
- **Pune, today (2026-08-07): 96.6%** (`manual`)

The urban series covers roughly one season of publicly reported aggregates. It is sufficient for the demo narrative and the stress score; it is **not** enough to claim a trained urban forecast.

## Sources and licences

| Source | Used for | Licence |
|---|---|---|
| [Sci Data 2025 / IISc groundwater dataset](https://doi.org/10.6084/m9.figshare.29293877.v3) | well registry, seasonal levels, specific yield | CC BY 4.0 |
| [NASA POWER (MERRA-2)](https://power.larc.nasa.gov/) | daily rainfall, temperature, humidity for **all 940 wells** | public domain (NASA) |
| [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) | daily weather for the **14 reservoirs only** | CC BY 4.0 |
| [Mumbai lake & Pune dam levels](https://www.mumbailakewaterlevel.in/) (Maharashtra WRD / BMC Hydraulic Engineer's Dept) | urban storage | public reporting |
| [GSDA / MRSAC State WRIS](http://mrsac.maharashtra.gov.in/nhpgis/) | optional telemetry (Appendix A) | public government data |

Total data cost: **₹0**.

## Known limitations

1. Groundwater readings are **seasonal, not daily**. Daily values are modelled. `is_observed` tells you which is which.
2. **Two weather sources, deliberately.** Open-Meteo (ERA5) exhausted its free quota partway through the well pull, so all 940 wells use **NASA POWER / MERRA-2** at a ~0.5° dedupe (~55 km); the 14 reservoirs kept their Open-Meteo/ERA5 series at ~0.25°. Wells within a cell share one weather series. Neither is station data.
3. **ET0 for wells is computed, not observed.** POWER does not serve reference evapotranspiration, so it is derived with the FAO-56 Hargreaves formula from daily max/min/mean temperature and latitude — the standard fallback when radiation data is absent.
4. **Soil moisture is NULL for all wells.** The hourly soil-moisture request was ~95% of Open-Meteo's per-call cost and had to be dropped to complete the pull. Reservoir rows retain it.
5. **Specific yield is transplanted for 44% of wells.** Only 271 of 940 have a value from the source dataset; 256 take their district's modal value and **413 take the value of the nearest donor well, a median 83.5 km away**. `wells.sy_source` records which. Reference_Sy in the source dataset takes only 4 distinct values across all of Maharashtra (0.018 / 0.020 / 0.023 / 0.130) because it is read from a hydrogeological map rather than measured per well, which is what makes transplanting defensible — but the Nashik wells, Dindori included, have no QC'd donor closer than Palghar.
6. The urban track rests on published **city aggregates**, not per-lake daily telemetry, for most dates.
7. Coverage is **Maharashtra only**. Nothing here generalises to other states without re-running ingestion.
8. The scenario date is deliberately **pre-monsoon 2026**. Run the model on today's data and it should return SAFE — the reservoirs are full. That contrast is the point, not a bug.

## Last ingest runs

| Script | Started | Rows in | Rows out | Status |
|---|---|---:|---:|---|
| `06_features.py` | 2026-08-08T00:28:05 |  | 3,194,786 | ok |
| `05_interpolate.py` | 2026-08-08T00:27:36 | 68,994 | 3,250,606 | ok |
| `03b_nasapower.py` | 2026-08-08T00:16:46 | 940 | 3,815,460 | ok |
| `03_openmeteo.py` | 2026-08-08T00:13:55 | 940 | 531,277 | ok |
| `03_openmeteo.py` | 2026-08-08T00:08:56 | 940 |  | ok |
| `03_openmeteo.py` | 2026-08-08T00:07:02 | 4 |  | ok |
| `03_openmeteo.py` | 2026-08-07T23:39:33 | 940 |  | ok |
| `03_openmeteo.py` | 2026-08-07T23:26:35 | 940 |  | ok |
| `03_openmeteo.py` | 2026-08-07T23:20:08 | 940 |  | ok |
| `03_openmeteo.py` | 2026-08-07T23:13:41 | 14 | 42,686 | ok |
| `03_openmeteo.py` | 2026-08-07T23:10:44 | 940 |  | failed |
| `04_reservoirs.py` | 2026-08-07T23:09:56 |  | 86 | ok |
