# JALAAKAR — जलाकार

**Predicting when water runs out, 30 days early, from data India already publishes.**

India measures its groundwater. The Central Ground Water Board reads thousands
of wells, BMC publishes lake levels every morning, IMD publishes rainfall. What
none of it does is say **what happens next** — and by the time a borewell
fails, the crop is already in the ground.

Jalaakar is a prediction layer over that public data. It forecasts where the
water will be, turns the forecast into a **0–100 water stress score**, and
sends a WhatsApp warning in **Marathi, Hindi or English** before the water runs
out. No sensors, no hardware, no app to install.

Built for **vivo Ignite 2026** (Tech for Good) by **Dheyay Shah**, Grade IX,
RMG Maheshwari English School, Surat. Targets SDG 6, 2 and 13.

---

## Run it

```bash
git clone https://github.com/orgkushal/Jalakaar.git && cd Jalakaar
make setup
make run
```

Open **http://localhost:8000**. That is the whole thing — the API and the
website are served together on one port. Setup takes about a minute and needs
no network beyond the clone.

Want accounts to play with? `make demo-user` creates five (password
`jalaakar-demo`). Full detail in **[QUICKSTART.md](QUICKSTART.md)**.

---

## What is actually running

| | |
|---|---|
| **940 wells** | 68,994 quality-controlled CGWB readings, 34 districts, 2000–2023 |
| **12 reservoirs** | BMC + Pune Irrigation Department daily storage, current to yesterday |
| **3.86 M rows** | NASA POWER daily weather per well |
| **247 talukas** | every one scorable, live, in the browser |
| **26 API endpoints** | scoring, alerts, community reports, auth, control room |
| **99 tests** | plus a frontend audit, both in `make test` |

### Measured results

Everything below is measured on **2,584 held-out CGWB readings** the model
never saw. Reproduce with `make test` then the `ml/` scripts.

| | |
|---|---|
| Forecast error | **1.39 m** at 7 days, **1.41 m** at 30 days (MAE) |
| Against a seasonal baseline | **24% better** (1.845 m) |
| 80% of forecasts land within | **2.15 m** of the real reading |
| The tail worth naming | p95 = **4.34 m** |
| Real crises caught | **44.7%** of 510 at the shipped cutoff — see below |
| Daily reconstruction | **1.32 m** MAE on 1,088 held-out readings |

**Not** claimed: the ~90/85/80% accuracy ladder on the original poster. That
was borrowed from published literature and has been replaced by the numbers
above, which came from this repository.

#### The alert threshold, and the recall it costs

This is the one number in the project that was made worse on purpose, so it
gets its own section rather than a footnote.

`ml/04_operating_point.py` fits the ACT NOW cutoff on validation and lands on
**54**. Jalaakar ships **70**. All three points measured on the same 7,752
held-out rows, against 510 real crises:

| ACT NOW cutoff | alerts fired | crises caught | misses | false alarms | recall | precision |
|---|---|---|---|---|---|---|
| 54 — fitted on val | 1,552 | 395 | 115 | 1,157 | **77.5%** | 25.5% |
| **70 — shipped** | 440 | 228 | 282 | 212 | **44.7%** | **51.8%** |
| 71 — the poster's | 411 | 217 | 293 | 194 | 42.5% | 52.8% |

`ml/04_operating_point.py` reads the shipped cutoff straight out of
`api/model.py`, so that middle row is measured rather than interpolated and
cannot go stale when the constant changes.

Why give up 33 points of recall: at 54, three of every four alerts are wrong.
That was survivable when a score was something you looked up. It is not
survivable now that `web/admin.html` lets an official warn the whole state in
one click, because a channel that cries wolf three times in four gets muted —
and a muted channel has a real-world recall of zero whatever the table says.
70 also makes a rural 68 and an urban 68 mean the same thing, which they have
to when the control room sorts both into one list.

Both cutoffs are real and neither is free. `reports/operating_point.json`
holds the full validation curve at every value from 30 to 90, so this is a
decision anyone can re-derive and argue with, not a constant somebody picked.

### What is *not* built

GRACE-FO satellite downscaling, the Bhujal App community layer, GSDA telemetry
and Aqua Credits are **Stage 2**. They are on the roadmap, not in the system,
and nothing in the site or the docs claims otherwise. Taluka-level downscaling
of GRACE-FO in particular is an open research problem, not an afternoon's work.

---

## Three findings that shaped the build

**1. The obvious feature table leaked the target.**
`gw_daily` interpolates *between* real observations, so the reconstructed level
at time *t* was built partly from the observation at *t+30* — the value being
predicted. Persistence off `gw_daily` scored 0.22 m MAE at +7 days against
2.54 m for last-real-reading persistence. That gap is leakage, not skill.
`ml/01_baseline.py` measures it and fails loudly; `ingest/06b_features_causal.py`
rebuilds every feature so it is computable at origin time, and
`api/verify_features.py` proves the serving path reproduces the training path
exactly.

**2. Staleness dominates, not forecast horizon.**
Error is flat from 7 to 30 days (1.391 → 1.413 m). The median CGWB reading is
**77 days old** when the forecast is made, so an extra three weeks barely
matters. That is the measured case for community reporting: one fresh reading
moves this number more than any model change.

**3. A sequence model does not help here.**
The poster named an LSTM. `ml/07_sequence.py` tests an autoregressive model on
the same splits: **1.709 m, 0.30 m worse** than tabular XGBoost, with a 92-day
median gap between consecutive readings. Reported as a measurement rather than
shipping an untested LSTM to match a diagram.

---

## Layout

```
ingest/     data pipeline, numbered in run order
ml/         baselines, training, evaluation, intervals
api/        FastAPI backend — scoring, alerts, auth, community reports
web/        the site: landing, demo, control room, signup, login (no build step)
tools/      bootstrap, audits, admin scripts
reports/    every metric this README quotes, as JSON
```

### Pipeline

| Script | Produces |
|---|---|
| `ingest/00_schema.sql` | schema — the frozen contract |
| `ingest/01_figshare.py` → `ingest/02_wells.py` | `wells`, `gw_observations` |
| `ingest/03b_nasapower.py` | `weather_daily` |
| `ingest/04_reservoirs.py` | `reservoirs`, `reservoir_daily` |
| `ingest/05_interpolate.py` | `gw_daily` — daily reconstruction |
| `ingest/06b_features_causal.py` | `features_causal` — the forecasting table |
| `ingest/07_stress.py` | `urban_stress` — rule-based urban score |

### Model

```bash
python ml/01_baseline.py          # the bar, and the leakage detector
python ml/02_xgboost.py           # train
python ml/03_band_accuracy.py     # does it make the right CALL?
python ml/04_operating_point.py   # choose the alert threshold deliberately
python ml/06_intervals.py         # empirical prediction intervals
python ml/07_sequence.py          # is a sequence model worth it? (no)
python api/verify_model.py        # serving path == published MAE
```

`api/verify_model.py` is the one that matters. It replays held-out rows through the
live serving code and compares against the accuracy this README advertises. It
currently agrees to **+0.000 m** across all 7,752 test rows. If it ever prints
`DIVERGED`, the numbers here are not the numbers the demo delivers.

---

## Four rules enforced in code

1. **`is_observed` is sacred.** 1 only on genuine measurement dates. Without
   it you cannot report honest accuracy — 99.12% of `gw_daily` is interpolated.
2. **Splits are chronological**, checked per track. `tools/validate.py` fails the
   build on any overlap or empty split.
3. **`level_mbgl` is metres *below* ground.** Bigger = deeper = worse. If this
   sign inverts, every stress score inverts with it.
4. **Never score against interpolated targets.** Every metric in this README is
   computed only where the target date is a real CGWB reading. Scoring against
   the reconstruction measures how well the model reproduces
   `ingest/05_interpolate.py`, which looks excellent and means nothing.

## Provenance

Nothing here is unsourced, and where something *is* unsourced the page says so.

- `gw_observations.source` — `figshare` (peer-reviewed IISc dataset, CC BY 4.0)
- `gw_daily.is_observed` — real reading vs interpolated
- `reservoir_daily.source` — `wrd_pravah` | `manual` | `interpolated`
- `ingest/reservoir_seeds.csv` — every anchor carries a URL and a confidence grade
- `urban_stress.inputs_source` — worst provenance behind each score
- `GET /api/figures` — the landing page renders whatever this returns, so a
  correction in the data cannot leave a stale number on the site
- Figures with no primary source are visibly tagged **unsourced**

See **[SOURCES.md](SOURCES.md)** and **[DATA_CARD.md](DATA_CARD.md)** — the
data card is generated from the database, never hand-written.

## Honest limitations

- **The rural record ends 2023-08-15.** CGWB's publication lag means there is
  no 2026 groundwater reading. Ask the API for one and it refuses with a
  reason rather than extrapolating. The urban track *is* current.
- **Soil moisture is null for every well** — the hourly request was ~95% of the
  API budget and was dropped. Two of the four inputs the poster names for
  XGBoost are therefore unavailable on the rural track.
- **Sign-in has no rate limiting and no account recovery.** Passwords are
  hashed (PBKDF2-HMAC-SHA256, 240k iterations, per-user salt), but a production
  deployment needs both of those.
- **WhatsApp runs on the Twilio sandbox.** The Business API needs company
  verification. Without credentials, alerts are *rendered and logged, never
  faked as delivered* — the UI says which.
- **The Marathi and Hindi strings have not been checked by a native reader.**
  `docs/translation-review.md` exists for exactly that review.

## What NOT to say

> ~~"We trained on 5 years of daily GSDA data."~~

Say instead:

> "We anchor on quality-controlled seasonal observations from a peer-reviewed
> IISc dataset and interpolate daily using rainfall-conditioned recession
> curves scaled by each well's specific yield, validated against held-out
> readings at 1.32 m MAE."

## Contributing

```bash
make test      # 99 API checks + frontend audit
make audit     # frontend only: dead links, class collisions, stale cache stamps
```

Run `tools/stamp_assets.py` after editing anything in `web/` — asset URLs carry
a content hash so a cached stylesheet can never disagree with fresh HTML.

## Licence and citation

Cite the underlying datasets, not this repository:

```
Kumar et al. (2025). Quality controlled, reliable groundwater level data with
corresponding specific yield over India. figshare.
https://doi.org/10.6084/m9.figshare.29293877.v3  (CC BY 4.0)

NASA POWER Project (2026). Daily point data, MERRA-2. (public domain)
BMC Hydraulic Engineer's Department (2026). Daily lake level bulletin.
Pune Irrigation Department (2026). Khadakwasla dam chain daily storage.
```

Total data cost: **₹0**. Every source is public.
