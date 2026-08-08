# JALAAKAR — DATA INGESTION ROADMAP

**Drafted:** Fri 7 Aug 2026 · **Ingestion must be frozen:** Sat 8 Aug, 20:00
**Prototype demo:** Tue 11 Aug 2026

---

## LOCKED DECISIONS

| Decision | Value |
|---|---|
| **Geography** | Maharashtra only — 36 districts, ~358 talukas |
| **Demo taluka** | Dindori, Nashik |
| **Scenario date** | **30 June 2026** (pre-monsoon) — see seasonality note |
| **History** | **Pull max available**, flag last 5 years (Jul 2021 – Jun 2026) |
| **Train on** | Full history · **Report/demo on** last 5 years |
| **Storage** | Parquet (raw cache) + SQLite (unified tables) |
| **Stack** | Python 3.11 · pandas · pyarrow · requests · sqlite3 |
| **Tracks** | **Both** rural (wells) and urban (reservoirs) |
| **GSDA** | ❌ Not on critical path. Optional — see Appendix A |
| **GRACE-FO** | ❌ Out of scope for prototype |
| **Cost** | ₹0 |

---

## THE CONTRACT — TARGET SCHEMA

Everything downstream reads from this. **The ML track and the alerting track must not
touch raw sources — only these tables.** Freeze this schema first; it lets all three
tracks work in parallel from Saturday morning.

```
jalaakar.db  (SQLite)
│
├── wells                     -- rural registry
│     well_id            TEXT PK
│     lat, lon           REAL
│     district           TEXT
│     taluka             TEXT
│     village            TEXT
│     specific_yield     REAL      -- from figshare, level → volume
│     aquifer_type       TEXT
│     n_observations     INTEGER
│     first_obs, last_obs DATE
│
├── gw_observations           -- REAL measured points (sparse, seasonal)
│     well_id            TEXT FK
│     obs_date           DATE
│     level_mbgl         REAL      -- metres below ground level
│     season             TEXT      -- pre_monsoon | monsoon | post_monsoon | rabi
│     source             TEXT      -- 'figshare' | 'gsda'
│     is_last_5y         BOOLEAN   -- ← the 5-year flag
│
├── weather_daily             -- dense daily, from Open-Meteo
│     well_id            TEXT FK
│     date                DATE
│     precip_mm           REAL
│     et0_mm              REAL
│     soil_moist_0_7      REAL
│     soil_moist_7_28     REAL
│     temp_max            REAL
│     rh_mean             REAL
│
├── gw_daily                  -- INTERPOLATED daily levels (the keystone)
│     well_id            TEXT FK
│     date                DATE
│     level_mbgl         REAL
│     is_observed         BOOLEAN  -- TRUE = real reading, FALSE = interpolated
│     confidence          REAL     -- decays with distance from nearest real obs
│
├── reservoirs                -- urban registry (12 rows)
│     reservoir_id       TEXT PK
│     name, city         TEXT
│     capacity_mcm       REAL
│
├── reservoir_daily
│     reservoir_id       TEXT FK
│     date                DATE
│     live_storage_pct    REAL
│     storage_mcm         REAL
│     pct_same_day_last_yr REAL
│
└── features                  -- FINAL joined training table
      entity_id, entity_type ('well'|'reservoir'), date,
      level/storage, all weather cols, lags (7/15/30/60/90d),
      rolling rainfall sums, days_since_last_rain, cum_monsoon_rainfall,
      month, doy, season, target_level_t+30, is_last_5y
```

**⚠️ `is_observed` is non-negotiable.** Without it you cannot separate real from
interpolated data, which means you cannot honestly report accuracy — and that is
exactly what a judge will probe.

---

## STAGE 0 — Setup · Fri 19:00 · 30 min

```
jalaakar/
├── data/raw/          # parquet cache, never edited by hand
├── data/interim/
├── data/jalaakar.db
├── ingest/  00_setup.py 01_figshare.py 02_wells.py
│            03_openmeteo.py 04_reservoirs.py
│            05_interpolate.py 06_features.py
├── notebooks/
└── config.yaml        # scenario date, bbox, date ranges, paths
```

`pip install pandas pyarrow requests requests-cache tqdm pyyaml matplotlib`

**`requests-cache` is not optional.** Every API response caches to disk, so re-runs
are free and you never re-hit a source. This saves you an hour on Saturday.

`config.yaml`: `scenario_date: 2026-06-30`, `state: Maharashtra`,
`last5_start: 2021-07-01`, Maharashtra bbox `15.6–22.1 N, 72.6–80.9 E`.

**✅ Done when:** folders exist, imports work, config loads.

---

## STAGE 1 — figshare download + **THE GATE** · Fri 19:30 · 45 min 🚦

Source: https://doi.org/10.6084/m9.figshare.29293877.v3
(Sci Data 2025, IISc — 32,299 wells → 2,759 QC'd pan-India, includes specific yield)

1. Download, unzip to `data/raw/figshare/`.
2. Inspect: column names, date coverage, state field format.
3. Filter `state == Maharashtra` (watch for `MAHARASHTRA` / `Maharastra` variants).
4. **Count wells. Count observations. Print min/max date.**
5. Write `data/interim/mh_wells_raw.parquet`.

### 🚦 GO / NO-GO GATE — the whole roadmap forks here

| MH wells | Verdict | What changes |
|---|---|---|
| **≥ 150** | ✅ Green | Proceed exactly as written. Per-region models viable. |
| **50–149** | ⚠️ Amber | Pool all wells into ONE global model with a well-ID embedding. No per-well models. Stage 5 becomes more important. |
| **< 50** | 🔴 Red | figshare = calibration only. **Escalate Appendix A (GSDA) to required**, run it Saturday 09:00, and expand synthetic well generation to ~200 wells seeded from real curves. |
| **0 wells / bad schema** | 🔴🔴 Stop | Fall back to `datagovindia` (Source 6) + full synthetic. Message the team immediately. |

**Also check:** how far back does the history go? If coverage is 1994–2026, "max
available" is ~120 seasonal points per well — excellent. If it starts 2015, ~44.
Either beats the 20 you'd get from 5 years alone, which is why we're pulling max.

**✅ Done when:** the well count is written down and the team knows which branch you're on.

---

## STAGE 2 — Well registry + observations · Fri 20:15 · 45 min

- Normalise district/taluka names to match Maharashtra's official list (this bites
  later when joining to the map — do it now).
- Reverse-geocode any well missing a taluka from lat/lon.
- Derive `season` from month: pre_monsoon Mar–May · monsoon Jun–Sep ·
  post_monsoon Oct–Nov · rabi Dec–Feb.
- Set `is_last_5y = obs_date >= 2021-07-01`.
- Sanity: levels are **metres below ground level** — bigger = deeper = worse. Confirm
  sign convention before it silently inverts your entire stress score.
- Write `wells` + `gw_observations` to SQLite.

**✅ Done when:** `SELECT COUNT(*) FROM wells WHERE taluka='Dindori'` returns ≥ 1.
If Dindori has zero wells, **pick a different demo taluka now** and tell the poster
owner — the sample card says Dindori and it must match.

---

## STAGE 3 — Open-Meteo weather · Fri 21:00 · 60–90 min

`https://archive-api.open-meteo.com/v1/archive` — no key, 10k calls/day, CC BY 4.0.

Per well coordinate, one call, full history:
```
daily = precipitation_sum, et0_fao_evapotranspiration,
        temperature_2m_max, relative_humidity_2m_mean
hourly→daily mean = soil_moisture_0_to_7cm, soil_moisture_7_to_28cm
start_date = <earliest obs>   end_date = 2026-08-07
```

- A few hundred wells = a few hundred calls. **Comfortably inside the free tier.**
- Dedupe coordinates to ~0.1° before calling — many wells share an ERA5 grid cell, so
  this can cut call volume by half or more.
- 0.5 s sleep between calls. Cache everything.
- Add the 12 reservoir coordinates to the same pull.

**✅ Done when:** `weather_daily` covers every well for every date, zero gaps.
Plot Nashik rainfall by year — the monsoon spike must be visibly June–September. If
it isn't, your dates or units are wrong.

---

## STAGE 4 — Reservoirs (urban track) · Sat 09:00 · 45 min

12 water bodies: **Mumbai** Upper Vaitarna, Modak Sagar, Tansa, Middle Vaitarna,
Bhatsa, Vehar, Tulsi · **Pune** Khadakwasla, Panshet, Varasgaon, Temghar, Pavana.

Source: [mumbailakewaterlevel.in](https://www.mumbailakewaterlevel.in/pune-dam-water-levels/)
(Maharashtra WRD / Pravah) — daily live storage **with same-day-last-year comparison**.

- Small table. Scrape or hand-enter. **Do not over-engineer.**
- Must capture **June 2026** values so the scenario demo rests on real pre-monsoon
  numbers, and current August values for the "correctly says SAFE" contrast.
- The last-year column gives you a free seasonal baseline for the urban stress score.

**✅ Done when:** June 2026 Mumbai aggregate is near the poster's 6.93%, and today's
reading is high (Pune was 96.6% on 7 Aug). Both must be in the table.

---

## STAGE 5 — Daily interpolation · Sat 10:00 · 2–3 hr ⭐ KEYSTONE

Turns sparse seasonal observations into the daily series the 30-day LSTM needs.

1. **Anchor** on every real observation — these are never altered.
2. **Recession** between observations: exponential decline during dry periods, rate
   fitted per well from its own historical dry-season segments.
3. **Recharge** pulses driven by `precip_mm`, scaled by that well's `specific_yield`
   (this is why the figshare Sy column matters).
4. **Reconcile** so the curve lands exactly on the next real observation — distribute
   residual error backwards across the interval.
5. `confidence` decays with days-since-nearest-real-observation.
6. `is_observed = TRUE` only on genuine measurement dates.

**Validation, and it must be real:** hold out every 4th observation, interpolate
without it, measure error at those points. **Write the MAE down.** That number is your
honest answer to "how accurate is your interpolation?"

**The sentence to rehearse:**
> "We anchor on quality-controlled seasonal observations and interpolate daily using
> rainfall-conditioned recession curves scaled by each well's specific yield,
> validated against held-out readings at X.XX m MAE."

**Never say:** "we trained on 5 years of daily GSDA data."

**✅ Done when:** a Dindori well plots as a smooth realistic curve with visible
monsoon recharge and dry-season decline, real points marked, and held-out MAE recorded.

---

## STAGE 6 — Feature table · Sat 14:00 · 60 min

Join wells + gw_daily + weather_daily → `features`. Same for reservoirs.

Engineer: lags 7/15/30/60/90d · rolling rainfall 7/30/90d ·
`days_since_last_rain` · `cum_monsoon_rainfall` · level change rate ·
month, day-of-year, season · **target = level at t+30**.

Splits — **chronological, never random** (random splits leak the future and will
inflate your accuracy):
- Train: start → Jun 2024
- Val: Jul 2024 → Jun 2025
- Test: Jul 2025 → Jun 2026 ← includes the demo scenario date

**✅ Done when:** `features` has no NaNs in required columns, no duplicate
(entity_id, date), and target correlates sensibly with lagged levels.

---

## STAGE 7 — Freeze & handoff · Sat 16:00 · 30 min

- Write `data/FROZEN_<timestamp>.db`, mark read-only.
- One-page `DATA_CARD.md`: well count, date range, observed vs interpolated ratio,
  interpolation MAE, sources + licences, known limitations.
- Post to the team: *"Ingestion frozen. ML and alerting read from
  `features`. Schema will not change."*

**🔒 HARD DEADLINE: Sat 20:00.** After this, no new data sources. Sunday and Monday
are model, WhatsApp, demo, rehearsal. A team still hunting datasets on Sunday will not
ship by Tuesday.

---

## CHECKPOINTS

| Time | Must be true | If not |
|---|---|---|
| Fri 20:15 | MH well count known | Escalate to Appendix A or synthetic |
| Fri 22:30 | Weather pulled, monsoon visible | Debug dates/units before sleeping |
| Sat 12:00 | Interpolation curve looks hydrologically real | Simplify to linear + rainfall bump, move on |
| **Sat 16:00** | `features` populated | **Cut urban track, ship rural only** |
| **Sat 20:00** | 🔒 FROZEN | Ship whatever exists. Do not extend. |

---

## RISK REGISTER

| Risk | P | Impact | Mitigation |
|---|---|---|---|
| MH wells < 50 after QC | Med | High | Appendix A + synthetic expansion. **Known by Fri 20:15.** |
| Dindori has no well | Med | Med | Switch demo taluka Friday night, tell poster owner |
| figshare schema differs from paper | Low | Med | 20 min inspection before writing any code |
| Interpolation looks fake | Med | High | Simple linear + rainfall bump fallback; ugly but honest |
| Open-Meteo rate limit | V.Low | Low | Dedupe coords, cache, 0.5 s sleep |
| **Judge checks live data, sees full dams** | **High** | **High** | **Scenario date labelled in UI + show model correctly returning SAFE for August** |

---

## APPENDIX A — GSDA telemetry (OPTIONAL, manual)

**Not on the critical path.** Only run this if you have spare time, or if Stage 1 came
back Red. Requires a human in Chrome — 90-minute hard cap, then abandon.

**What's there:** [MRSAC State WRIS Dashboard](http://mrsac.maharashtra.gov.in/nhpgis/)
— 464 observation wells + 66 piezometers, 6-hourly telemetry, Weekly/Yearly time step,
Download-to-Excel, Query Module. Maharashtra-native, so it covers 100% of scope.

**Steps:**
1. Open the dashboard in Chrome. **F12 → Network tab → filter XHR → tick "Preserve log".**
2. Left panel: Groundwater Level → **Telemetry** sub-layer.
3. Select **one** district (Nashik) and **one** year. Set Time Step = **Weekly**.
4. Click **Download to Excel**.
5. In Network, find the request that fired. **Right-click → Copy → Copy as cURL.**
6. Open the downloaded file. Answer one question:

| What you see | Verdict |
|---|---|
| **Per-well rows with weekly dates** | ✅ Worth scaling. ~464 wells × 260 wks ≈ 120k rows. Paste the cURL to me and I'll write the loop. |
| **One aggregate value per district/taluka** | ❌ **Stop.** Not worth the request volume. |
| Login wall / error / empty | ❌ Stop. |

**If scaling:** 1–2 req/sec max, real user-agent, cache every response to disk, resume
from cache on restart. Public government data so you're legally fine, but state
servers are fragile — do not hammer it.

**If this yields real telemetry:** insert into `gw_observations` with
`source='gsda'`, set `is_observed=TRUE` in `gw_daily`, re-run Stages 5–6. The schema
already accommodates it — that's why `source` exists.

---

## SOURCES

- [Sci Data 2025 groundwater dataset](https://www.nature.com/articles/s41597-025-05899-5) · dataset DOI 10.6084/m9.figshare.29293877.v3 · [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12489037/)
- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) — CC BY 4.0
- [Mumbai lake + Pune dam levels](https://www.mumbailakewaterlevel.in/pune-dam-water-levels/) — Maharashtra WRD / Pravah
- [GSDA State WRIS Dashboard](http://mrsac.maharashtra.gov.in/nhpgis/) · [GSDA NHP](https://gsda.maharashtra.gov.in/en-national-hydrology-project-2/)
