# JALAAKAR — DATA SOURCES

Every dataset behind the ingestion pipeline, what it provided, and its licence.
Compiled from the code and the `source` columns in `jalaakar.db` — not from the
project plan, which differs in places.

**Geography:** Maharashtra only · **Total data cost: ₹0** · **Frozen:** 8 Aug 2026

---

## 1. Groundwater levels and specific yield

The entire rural track rests on this one dataset.

> Kumar, K. Satish; Suryawanshi, Maya; Shakya, Amin; V A, Chethan; Shaw, Balaram;
> S, Vandana; Vishwakarma, Bramha Dutt (2025). *Quality controlled, reliable
> groundwater level data with corresponding specific yield over India.*
> Scientific Data. figshare. https://doi.org/10.6084/m9.figshare.29293877.v3

| | |
|---|---|
| Licence | CC BY 4.0 |
| Paper | [Sci Data (2025)](https://www.nature.com/articles/s41597-025-05899-5) |
| Archive | `Quality_controlled_groundwater_levels_over_India.zip`, 25.5 MB |
| Checksum | md5 `43499153306f16e468c23588d5400c2f` (verified on every run) |
| Underlying data | **Central Ground Water Board (CGWB)** monitoring network |

**Files used**

| File | Role | Result |
|---|---|---|
| `Output/4_India_GWLs_2000_2024_after_3sigma.csv` | spine | 2,033 Maharashtra wells → **940** after re-applying the paper's QC |
| `Output/CGWB_India_filtered_GWLs_ref_sy_2000_2022.csv` | specific-yield donors | 277 Maharashtra wells with `Reference_Sy` |

**Why the spine is not the fully QC'd file.** The 277-well QC'd subset contains
**zero Nashik district wells**, so it cannot support the Dindori demo. The
3-sigma-filtered file covers 34 districts including Nashik, and we re-applied
the paper's remaining criteria ourselves (minimum readings, ≥2 readings/year,
no repeated-value runs).

**Cadence.** CGWB measures **four times a year** — January, May (pre-monsoon),
August (monsoon), November (post-monsoon). Not daily. `May-2020` and `May-2021`
are entirely absent nationally: COVID cancelled both pre-monsoon rounds.

**Yield:** 68,994 observations, 2000-01-15 → 2023-08-15, `source = 'figshare'`.

---

## 2. Weather — 940 wells

> **NASA POWER** (Prediction Of Worldwide Energy Resources), Daily API v2.9.6.
> https://power.larc.nasa.gov/ · Source dataset: **MERRA-2** reanalysis.

| | |
|---|---|
| Licence | Public domain (NASA); no key required |
| Endpoint | `power.larc.nasa.gov/api/temporal/daily/point` |
| Parameters | `PRECTOTCORR`, `T2M_MAX`, `T2M_MIN`, `T2M`, `RH2M` |
| Resolution | ~0.5° × 0.625° (~55 km); coordinates deduped to 0.5° → 114 cells |
| Coverage | 2012-09-03 → 2023-10-14 |
| Yield | **3,815,460 rows** |

**Why not Open-Meteo for the wells.** Open-Meteo was the planned source, but
hourly soil moisture over a 24-year history is ~435,000 values per grid cell,
and its free quota was exhausted after 6 of 817 cells. NASA POWER completed all
114 cells without throttling.

---

## 3. Weather — 14 reservoirs

> **Open-Meteo Historical Weather API** — ERA5 reanalysis.
> https://open-meteo.com/en/docs/historical-weather-api

| | |
|---|---|
| Licence | CC BY 4.0 |
| Resolution | ~0.25°; deduped to 11 grid cells |
| Coverage | 2018-04-03 → 2026-08-07 |
| Yield | 42,686 rows, including soil moisture |

The urban track kept its Open-Meteo series because it was already complete when
the quota failed. **Wells and reservoirs therefore use different reanalyses** —
recorded here rather than glossed over.

---

## 4. Reservoir storage — urban track

Nine hand-entered anchors, each traceable to a named public report. Values are
Mumbai and Pune **city aggregates**, which is how BMC and WRD publish them.

| Source | Used for |
|---|---|
| [mumbailakewaterlevel.in](https://www.mumbailakewaterlevel.in/) (Maharashtra WRD / Pravah) | 7 Aug 2026 readings, Mumbai and Pune |
| **BMC Hydraulic Engineer's Department** | Mumbai reservoir series, June–August 2026 |
| RMSI climate blog (Jul 2026) · Mumbai Live | May–June 2026 restriction timeline |

Registry covers all 12 water bodies — Mumbai: Upper Vaitarna, Modak Sagar,
Tansa, Middle Vaitarna, Bhatsa, Vehar, Tulsi · Pune: Khadakwasla, Panshet,
Varasgaon, Temghar, Pavana — plus `MUM_ALL` and `PUN_ALL` aggregates. Only the
aggregates carry storage values.

**Yield:** 86 rows — 9 `manual` anchors, 77 `interpolated` between them.

> ⚠️ **Open item.** Three anchors (6.93%, 53.38%, 90.06%) currently cite the
> Jalaakar poster, which itself cites BMC. That is a circular chain of custody.
> Trace them to a primary BMC or WRD page before the demo.

---

## Derived, not fetched

| Quantity | How | Why |
|---|---|---|
| **ET0** (`et0_mm`) | FAO-56 **Hargreaves** from T2M_MAX / T2M_MIN / T2M and latitude | NASA POWER does not serve reference evapotranspiration; Hargreaves is the standard FAO-56 fallback when radiation data is unavailable |
| **Specific yield** for 669 of 940 wells | 256 district-modal, 413 nearest-donor (median **83.5 km**) | `Reference_Sy` takes only 4 distinct values across Maharashtra (0.018 / 0.020 / 0.023 / 0.130) because the source reads it from a hydrogeological map, not per-well measurement. `wells.sy_source` records the provenance of every value. |
| **Daily groundwater levels** | Seasonal climatology + linearly interpolated anomaly | Observations are quarterly; the model needs daily. Validated at **1.32 m MAE** on 1,088 held-out readings. `gw_daily.is_observed` marks the 0.88% that are real. |

---

## Evaluated and not used

| Source | Why not |
|---|---|
| [GSDA / MRSAC State WRIS](http://mrsac.maharashtra.gov.in/nhpgis/) | The plan's optional telemetry probe. Dropped once the well count came back green at 277 — a fragile state portal was not worth the time. |
| [India-WRIS](https://indiawris.gov.in/) | Investigated to close the 2023→2026 gap. CGWB's quarterly cadence and publication lag mean no source can place a reading on the scenario date. |
| `datagovindia` | Contingency if figshare returned nothing. Never needed. |

---

## On the poster but not in this data

Stated for honesty, because the methodology diagram implies otherwise:

- **NASA GRACE-FO** satellite water-mass anomalies — out of scope for the prototype
- **Bhujal App** community-reporting layer — not implemented
- **GSDA 5-year borewell records** — not used; the CGWB/figshare dataset is the groundwater source

---

## Citation

Please cite the underlying datasets, not this repository:

```
Kumar et al. (2025). Quality controlled, reliable groundwater level data with
corresponding specific yield over India. figshare.
https://doi.org/10.6084/m9.figshare.29293877.v3  (CC BY 4.0)

NASA POWER Project (2026). Daily point data, MERRA-2.
https://power.larc.nasa.gov/  (public domain)

Open-Meteo (2026). Historical Weather API, ERA5.
https://open-meteo.com/  (CC BY 4.0)

BMC Hydraulic Engineer's Department & Maharashtra Water Resources Department
(2026). Reservoir storage bulletins.
```
