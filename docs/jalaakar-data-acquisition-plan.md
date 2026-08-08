# JALAAKAR — Data Acquisition Plan (FINAL, MAHARASHTRA-ONLY)

**Decided:** Fri 7 Aug 2026 · **Prototype due:** Tue 11 Aug 2026
**Scope:** Maharashtra only — 6 revenue divisions, 36 districts, **~358 talukas**
**Demo target:** Dindori taluka, Nashik district (matches the poster sample card)
**Rule:** every source below is free and openly licensed. The ₹0 claim holds.

---

## 🚨 READ THIS FIRST — THE SEASONALITY TRAP

**Today, 7 Aug 2026, Pune's dams are 96.60% full.** Khadakwasla, Panshet, Varasgaon
and Temghar are all at **100%**; Pavana at 98.31%. Mumbai's lakes will be similarly
high — it is peak monsoon.

Your poster's headline numbers (6.93% Mumbai lakes, ₹3,000 tankers) are **June 2026,
pre-monsoon**. That is the correct and honest framing, but it creates a demo hazard:

> If you demo "live" water stress on Tuesday, every reservoir in Maharashtra is full
> and your CRITICAL / RED alert will look obviously wrong to anyone who checks.

**The fix — decide this now, not Monday night:**

- Anchor the entire demo to a **stated scenario date of 30 June 2026** (which is
  exactly what the poster's sample card already says: *"CRITICAL · DINDORI TALUKA,
  NASHIK · JUNE 30, 2026"*). Label it visibly in the UI: *"Scenario date: 30 June
  2026 (pre-monsoon)."*
- Better still, show **both**: run the model on today's August data too, and let it
  correctly output **SAFE / GREEN**. A system that says "all clear" when reservoirs
  are full is *more* convincing than one that only ever screams red. It proves the
  model responds to real conditions rather than replaying a hardcoded demo.

This single decision is worth more than any extra feature. Judges check live numbers.

---

## THE DECISION IN ONE LINE

> Download the peer-reviewed figshare dataset and **filter to Maharashtra**, pull
> weather from Open-Meteo's free archive API, interpolate to daily. GSDA scraping is
> now a *stronger* optional upgrade because it is Maharashtra-native — but still a
> 90-minute timebox, never a dependency.

---

## SOURCE 1 — Groundwater levels (PRIMARY, do this first) ⭐

**Where:** https://doi.org/10.6084/m9.figshare.29293877.v3
**Paper:** [Sci Data 2025, IISc Interdisciplinary Centre for Water Research](https://www.nature.com/articles/s41597-025-05899-5) · [PMC mirror](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12489037/)

| Property | Value |
|---|---|
| Wells (raw, pan-India) | 32,299 |
| Wells after QC (pan-India) | **2,759 reliable** |
| **Maharashtra subset** | **⚠️ unknown — COUNT THIS FIRST** |
| Cleaning already done | nulls + negatives removed, three-sigma outlier rejection, ≥2 readings/yr, no value repeating >2× consecutively |
| Bonus | **specific yield (Sy) per well** — converts water *level* → water *volume* |
| Cost / effort | ₹0, one download, ~30 min |

**⚠️ FIRST ACTION, BEFORE ANYTHING ELSE:** download, filter `state == Maharashtra`,
and **count the wells**. This number decides your architecture:

| Maharashtra wells | Verdict | Action |
|---|---|---|
| **150+** | Comfortable | Proceed as planned. Train per-region models. |
| **50–150** | Workable | Pool wells into a single global model with well-ID embedding. Don't train per-well. |
| **< 50** | Thin | Source 1 becomes *calibration only*. Escalate GSDA (Source 5) from optional to required, and lean harder on synthetic. |

Maharashtra is roughly 9% of India's area, so a naive estimate is ~250 wells — but
groundwater monitoring density varies enormously and the QC filter is aggressive.
**Do not plan around the estimate. Count it, then plan.** This is a 20-minute task
and it is the single highest-information action available to you right now.

Then plot 5–10 Nashik wells to see the real recession/recharge shape.

---

## SOURCE 2 — Weather, rainfall, ET, soil moisture (PRIMARY) ⭐

**Where:** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) — `https://archive-api.open-meteo.com/v1/archive`

| Property | Value |
|---|---|
| API key | **none**, no signup, no card |
| Free tier | 10,000 calls/day (non-commercial) |
| Coverage | ERA5 from 1940, **ERA5-Land from 1950** |
| Formats | JSON / CSV / XLSX |
| Licence | **CC BY 4.0** |

**Maharashtra scope makes this trivially easy.** A few hundred well coordinates = a
few hundred calls, against a 10,000/day limit. No batching, no rate-limit engineering,
no caching complexity. Pull 10 years of daily data per well in one pass if you want.

**Variables:** `precipitation_sum`, `et0_fao_evapotranspiration`,
`soil_moisture_0_to_7cm`, `soil_moisture_7_to_28cm`, `temperature_2m_max`,
`relative_humidity_2m_mean`.

**Honesty note:** this is ERA5 reanalysis, not a live IMD feed. Say *"IMD-equivalent
reanalysis (ERA5-Land) for the prototype; IMD gridded rainfall in production."*
Don't claim a live IMD integration you don't have — ERA5 is a stronger scientific
answer anyway.

---

## SOURCE 3 — Reservoirs for the urban track (CHEAP, 45 min) ⭐

**One site covers both Maharashtra cities you need:**
[mumbailakewaterlevel.in](https://www.mumbailakewaterlevel.in/pune-dam-water-levels/)
— daily live storage with **same-day-last-year comparison**, sourced from Maharashtra
WRD and Pravah.

| City | Bodies | Names |
|---|---|---|
| **Mumbai** | 7 lakes | Upper Vaitarna, Modak Sagar, Tansa, Middle Vaitarna, Bhatsa, Vehar, Tulsi |
| **Pune** | 5 dams | Khadakwasla, Panshet, Varasgaon, Temghar, Pavana |

Twelve water bodies total. This is a tiny table — a 20-line scraper or hand-entered
CSV. **Do not over-engineer this.** The year-over-year column is a gift: it gives you
a free seasonal baseline for the urban stress score.

Also grab the June 2026 values so the scenario demo has real pre-monsoon numbers
behind it, not just the poster's headline figure.

---

## SOURCE 4 — Daily interpolation layer (BUILD THIS, it's the keystone)

Source 1 gives real but seasonal (~4/yr) levels. Source 2 gives dense daily weather.
Bridge them:

1. Fit a **recession curve** per well on the real seasonal observations.
2. **Condition daily interpolation on rainfall** from Source 2 — drawdown during dry
   spells, recharge pulses after monsoon rain, scaled by that well's specific yield.
3. Result: a daily series *anchored to real observations* at every measurement point.

**This is a legitimate hydrological technique, not a fudge** — and it's your answer
when a judge asks how you get daily resolution from quarterly data. Rehearse it.

**Never say:** "we trained on 5 years of daily GSDA data."
**Say:** "we anchor on quality-controlled wells and interpolate daily using
rainfall-conditioned recession curves, validated against held-out seasonal readings."

---

## SOURCE 5 — GSDA telemetry (OPTIONAL UPGRADE, 90-min hard cap) ⏱

**Now more attractive** — GSDA *is* Maharashtra, so it covers 100% of your scope
rather than a fraction. But still not a dependency.

**Where:** [MRSAC State WRIS Dashboard](http://mrsac.maharashtra.gov.in/nhpgis/) ·
[GSDA NHP](https://gsda.maharashtra.gov.in/en-national-hydrology-project-2/)

**What's there:** **464 observation wells + 66 piezometers**, 6-hourly telemetry,
District→Taluka→Village dropdowns, Weekly/Yearly time step, **Download to Excel**,
Query Module.

**Do this, in this order:**
1. Chrome → DevTools → Network tab.
2. Select **one** district + **one** year on the *Telemetry* sub-layer.
3. Click "Download to Excel." **Capture the exact request** (URL, method, payload).
4. Is the response a per-well time series, or one aggregate per district?

**Then decide:**
- Per-well weekly series → worth scaling. ~464 wells × 260 weeks ≈ **120k rows** of
  genuine high-frequency Maharashtra data. Big upgrade. Proceed.
- District aggregate only → **stop immediately.**

**If you scrape:** 1–2 req/sec, real user-agent, cache every response to disk. Public
government data so you're legally fine, but state servers are fragile — don't hammer.

**Hard rule: not working at 90 minutes → abandon.** Sources 1+2+4 are a complete
prototype on their own.

---

## SOURCE 6 — data.gov.in (BACKUP ONLY)

[`datagovindia`](https://pypi.org/project/datagovindia/) wrapper · free key ·
[Ground Water Survey Maharashtra catalog](https://www.data.gov.in/catalog/ground-water-survey-maharashtra).
Only if Sources 1 and 5 both disappoint.

---

## ⛔ DO NOT USE / DO NOT BUILD

| Item | Why not |
|---|---|
| **Raw CGWB national series** | 4 readings/year. 20 points per well over 5 years. Source 1 is the QC'd, Sy-enriched version of this same data and is strictly better. |
| **Raw NASA GRACE-FO** | Coarse NetCDF, Earthdata login, mascon processing, and the taluka downscaling your own poster calls *"the key unsolved challenge for Stage 2."* Show the slot in the diagram, label it Stage 2, move on. Do not spend Saturday on this. |
| **Gujarat / pan-India data** | Out of scope now. The Gujarat paragraph and the 43,228-well figure stay in the deck as *future scope narrative* — no code, no data. |

---

## EXECUTION ORDER

| When | Task | Budget | Blocking? |
|---|---|---|---|
| **Fri night** | Download figshare, filter Maharashtra, **COUNT WELLS** | 30 min | ✅ decides architecture |
| **Fri night** | Plot Nashik/Dindori wells, eyeball seasonality | 30 min | ✅ |
| **Fri night** | Open-Meteo pull for Maharashtra well coords | 1 hr | ✅ blocks ML |
| **Sat AM** | Daily interpolation layer (S4) | 2–3 hr | ✅ blocks ML |
| **Sat AM** | *Parallel:* GSDA devtools probe | **90 min hard cap** | ❌ optional |
| **Sat PM** | Mumbai + Pune reservoirs (12 bodies) | 45 min | ❌ urban track |
| **Sat PM** | Lock the **June 2026 scenario date** into the demo design | 15 min | ✅ demo safety |
| **Sat PM** | Freeze unified feature table → hand to ML track | — | ✅ |

**By Saturday evening the data question must be closed.** Sunday and Monday are for
the model, the WhatsApp pipeline, and the demo — not for hunting datasets.

---

## COST CHECK ✅

| Source | Cost |
|---|---|
| figshare dataset | ₹0 |
| Open-Meteo | ₹0 (no key) |
| Mumbai/Pune reservoir levels | ₹0 |
| GSDA dashboard | ₹0 |
| Twilio WhatsApp sandbox | ₹0 (trial credit) |
| **Total** | **₹0 — claim holds** |

---

## CITATIONS FOR THE POSTER

A peer-reviewed data citation materially strengthens the "Scientific Approach" panel:

- Quality controlled, reliable groundwater level data with corresponding specific
  yield over India. *Scientific Data* (2025). DOI: 10.1038/s41597-025-05899-5.
  Dataset: DOI 10.6084/m9.figshare.29293877.v3
- Open-Meteo Historical Weather API (ERA5-Land reanalysis), CC BY 4.0.
- GSDA Maharashtra, State WRIS / National Hydrology Project.
- Maharashtra WRD / Pravah — Mumbai lake and Pune dam live storage.
- BMC Hydraulic Engineer's Dept., Mumbai Reservoir Storage Data (June 2026).
