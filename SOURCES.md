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

**Re-sourced 8 Aug 2026.** Eighteen hand-entered anchors, every one carrying a
URL in `ingest/reservoir_seeds.csv`. Values are **city aggregates**, which is
how BMC and the Pune Irrigation Department publish them.

Each anchor carries a `confidence` grade, and the loader prints the breakdown
on every run:

| Grade | Meaning | Count |
|---|---|---|
| `primary` | published by BMC / WRD and read off that page | 2 |
| `reported` | a named outlet quoting BMC / WRD, page read, date confirmed | 9 |
| `secondhand` | quoted inside another article, original not read | 7 |

**Mumbai — all 7 lakes** (`MUM_ALL`, 14,47,363 ML). Twelve anchors,
15 May → 7 Aug 2026. The load-bearing ones:

| Date | Storage | Source |
|---|---|---|
| 29 Jun | **6.93%** (~1 lakh ML) | [FPJ, 30 Jun](https://www.freepressjournal.in/mumbai/mumbai-water-crisis-usable-lake-storage-drops-to-693-per-cent-delayed-projects-raise-long-term-supply-concerns) — season low, supply projected to 20 Aug |
| 30 Jun | **6.75%** (97,666 ML) | [Mid-Day via Inshorts](https://inshorts.com/en/news/water-levels-in-mumbai-s-7-lakes-drop-to-6-75--despite-rain-1782830556356) |
| 21 Jul | 57.75% (8,35,919 ML) | [FPJ, 21 Jul](https://www.freepressjournal.in/mumbai/mumbais-water-stock-jumps-to-5775-after-heavy-rain-lake-levels-rise-by-370-in-24-hours) |
| 24 Jul | 77.62% (11,23,443 ML) | [FPJ, 24 Jul](https://www.freepressjournal.in/mumbai/mumbai-rains-citys-water-stock-climbs-to-7762-after-heavy-showers-lake-levels-rise-nearly-8-in-24-hours) |
| 3 Aug | **90.06%** (13,03,500 ML) | [FPJ, 3 Aug](https://www.freepressjournal.in/mumbai/mumbais-water-stock-crosses-90-mark-lake-levels-at-9006-amid-incessant-rains) — season peak |
| 7 Aug | 88.50% (12,80,931 ML) | [mumbailakewaterlevel.in](https://www.mumbailakewaterlevel.in/) |

**Pune — Khadakwasla chain** (`PUN_KHW`, 29.15 TMC = 8,25,660 ML). New entity,
added 8 Aug. Five anchors, 5 Jul → 8 Aug, sourced to the Pune Irrigation
Department via [Punekar News](https://www.punekarnews.in/pune-dams-water-storage-update-reservoirs-at-17-47-capacity-despite-steady-rainfall/),
[The Bridge Chronicle](https://www.thebridgechronicle.com/pune/pune-khadakwasla-dam-chain-nears-88-percent-capacity-controlled-water-release-agn97)
and [FPJ](https://www.freepressjournal.in/pune/record-july-rain-fills-pune-dams-to-the-brim-khadakwasla-system-hits-100-storage-pawana-almost-full).
Storage went 17.47% (5 Jul) → 87.77% (27 Jul) → 100% (8 Aug) on a record July.

Registry covers all 12 water bodies plus three aggregates: `MUM_ALL`,
`PUN_KHW`, `PUN_ALL`. Only aggregates carry storage values.

**Yield:** 121 rows — 18 `manual` anchors, 103 `interpolated` between them.

### What the re-sourcing found

Three things, none of which were visible before the URLs went in:

**1. The circular citation is closed.** 6.93% and 90.06% now trace to FPJ
reports of the BMC Hydraulic Engineer's 06:00 bulletin, with the underlying
volumes (≈1 lakh ML, 13,03,500 ML) confirming the percentages independently.

**2. 53.38% on 25 July was wrong and has been deleted.** It cited only the
poster, and the record contradicts it: BMC reported **77.62% on 24 July** and
**88.40% on 27 July**. A 53% reading cannot sit between them. The value most
likely belongs to ~19 July — 54.05% is confirmed for 20 July — but no source
was found, so it was dropped rather than guessed.

**3. 6.93% is 29 June, not 30 June.** FPJ's table is captioned *"Water Stock
As On June 29"*; the article ran on the 30th. The 30 June reading is 6.75%,
separately confirmed by Mid-Day. Both dates are now anchored.

> ⚠️ **Decision needed before the demo.** `config.yaml` sets
> `scenario.date: 2026-06-30`, which now resolves to **6.75%**, while the
> poster prints **6.93%**. Either move the scenario to 29 June or change the
> poster. Do not leave both.

> ⚠️ **Still open.** The three May/June rows from the RMSI blog (23.00%,
> 10.35%, 8.68%) remain `secondhand`. They fit the curve and the BMC
> restriction timeline, but none has been read off a BMC or WRD page.

### A registry bug found on the way

`PUN_ALL` was declared at 1,099,980 ML while its five members sum to
**1,066,930 ML** — so every Pune `storage_mcm` was ~3% low, silently. Worse,
every published Pune percentage describes the **four-dam Khadakwasla chain**,
not the five-dam total, so those figures were being divided by a denominator
23% too large. Both are fixed, and `04_reservoirs.py::_check_aggregates` now
refuses to load if any aggregate stops equalling the sum of its members.

---

## Derived, not fetched

| Quantity | How | Why |
|---|---|---|
| **ET0** (`et0_mm`) | FAO-56 **Hargreaves** from T2M_MAX / T2M_MIN / T2M and latitude | NASA POWER does not serve reference evapotranspiration; Hargreaves is the standard FAO-56 fallback when radiation data is unavailable |
| **Specific yield** for 669 of 940 wells | 256 district-modal, 413 nearest-donor (median **83.5 km**) | `Reference_Sy` takes only 4 distinct values across Maharashtra (0.018 / 0.020 / 0.023 / 0.130) because the source reads it from a hydrogeological map, not per-well measurement. `wells.sy_source` records the provenance of every value. |
| **Daily groundwater levels** | Seasonal climatology + linearly interpolated anomaly | Observations are quarterly; the model needs daily. Validated at **1.32 m MAE** on 1,088 held-out readings. `gw_daily.is_observed` marks the 0.88% that are real. |
| **Urban Water Stress Score** | Rule-based, `ingest/07_stress.py`, `urban-stress-1.0` | 18 published aggregate readings over one season is not a training set. The score is an explicit formula — depletion (0–60) + rate of decline (0–25) + days of supply (0–15) — with every component stored beside the total, so *"why 87?"* has an arithmetic answer. Breakpoints were chosen to agree with what BMC actually did in 2026, not to draw a nice curve. |

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

BMC Hydraulic Engineer's Department (2026). Daily lake level bulletin,
Bhandup Complex. Reported by The Free Press Journal, Mid-Day and
mumbailakewaterlevel.in.

Pune Irrigation Department (2026). Khadakwasla dam chain daily storage.
Reported by Punekar News and The Bridge Chronicle.

Maharashtra Water Resources Department (2026). Daily dam storage reports.
```

Per-anchor URLs live in `ingest/reservoir_seeds.csv`, one per row. That file
is the citation of record for the urban track — this section summarises it.
