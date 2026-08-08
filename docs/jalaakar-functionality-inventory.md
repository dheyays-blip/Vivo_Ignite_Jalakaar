# JALAAKAR — Complete Functionality Inventory

**Source:** vivo Ignite 2026 poster (Dheyay Shah, RMG Maheshwari English School, Surat)
**Prototype deadline:** Tuesday, 11 Aug 2026
**Priority key:** `[M]` Must have for Tuesday · `[S]` Should have · `[C]` Could have · `[F]` Future / out of scope

---

## 1. DATA INGESTION — 3-Layer Sensing Architecture

### 1.1 Layer 1 — Satellite
| # | Functionality | Pri |
|---|---|---|
| 1.1.1 | Ingest NASA GRACE-FO monthly underground water-mass anomaly data | M |
| 1.1.2 | ML downscaling of GRACE-FO from coarse grid → **taluka-level** resolution | S |
| 1.1.3 | Downscaling feature stack: Random Forest + NDVI + IMD rainfall | S |
| 1.1.4 | Handle GRACE-FO latency/gaps (monthly cadence, ~2 month lag) | C |

> **Stated limitation:** GRACE-FO's coarse resolution is the "key unsolved challenge for Stage 2." For Tuesday, a mocked/interpolated downscale is acceptable.

### 1.2 Layer 2 — Community (crowdsourced)
| # | Functionality | Pri |
|---|---|---|
| 1.2.1 | Bhujal App integration for borewell depth reporting | F |
| 1.2.2 | WhatsApp "Jal Mitra" reporting channel | M |
| 1.2.3 | Borewell depth submission flow completable in **under 1 minute** | M |
| 1.2.4 | Bayesian filter validates *each* community report (outlier/fraud rejection) | S |
| 1.2.5 | Reporter identity + geotag capture (well ID / village / lat-long) | M |
| 1.2.6 | Report history per well | S |

### 1.3 Layer 3 — Government Data
| # | Functionality | Pri |
|---|---|---|
| 1.3.1 | GSDA borewell records — 5-year historical ingest (training backbone) | M |
| 1.3.2 | BMC reservoir storage feed (Mumbai lakes, % live storage) | M |
| 1.3.3 | PMC reservoir feed (Pune) | S |
| 1.3.4 | IMD rainfall / weather feed | M |
| 1.3.5 | CGWB well registry (43,228 wells) for national scale-out | C |
| 1.3.6 | Maharashtra Water 7/12 dataset link | S |

### 1.4 Fusion
| # | Functionality | Pri |
|---|---|---|
| 1.4.1 | All three layers feed the model **simultaneously** (unified feature store) | M |
| 1.4.2 | Graceful degradation when a layer is missing/stale | S |

---

## 2. THE 6-STEP AI PIPELINE

| Step | Name | What it does | Pri |
|---|---|---|---|
| 1 | **Measure** | Capture reading via Bhujal or WhatsApp | M |
| 2 | **Validate** | Bayesian filter cross-checks the reading | S |
| 3 | **Predict** | XGBoost + LSTM forecast water level | M |
| 4 | **Score** | Convert forecast → 0–100 Water Stress Score | M |
| 5 | **Alert** | Push WhatsApp alert in 3 languages | M |
| 6 | **Log** | Write action to Aqua Credits ledger + Water 7/12 | S |

---

## 3. PREDICTION / ML ENGINE

| # | Functionality | Pri |
|---|---|---|
| 3.1 | **LSTM neural network** — learns groundwater trends from historical borewell time series | M |
| 3.2 | **XGBoost model** — integrates rainfall, evapotranspiration, soil moisture, weather variables | M |
| 3.3 | Ensemble / hand-off logic between LSTM and XGBoost | S |
| 3.4 | **Bayesian validation** — cross-checks AI predictions against satellite obs + historical records to reduce uncertainty | S |
| 3.5 | **Satellite downscaling model** — Random Forest on GRACE-FO + NDVI + IMD | S |
| 3.6 | **30-day forecast horizon** (rolling daily) | M |
| 3.7 | Multi-horizon accuracy targets: ~90% @ 7d · ~85% @ 15d · ~80% @ 30d | S |
| 3.8 | Accuracy/validation reporting on live GSDA data | F |
| 3.9 | Risk analysis output (confidence band / uncertainty) | C |
| 3.10 | Retraining pipeline as new community + govt data arrives | F |

---

## 4. WATER STRESS SCORE (the core output object)

| # | Functionality | Pri |
|---|---|---|
| 4.1 | Composite **0–100 Water Stress Score** | M |
| 4.2 | Three-band classification: **0–40 Safe/Normal** · **41–70 Monitor/Reduce Usage** · **71–100 Critical/Act Now** | M |
| 4.3 | **Days-to-crisis** counter (e.g. "30") | M |
| 4.4 | **Alert level** colour code (GREEN / AMBER / RED) | M |
| 4.5 | Language tag on the score card (e.g. MARATHI) | M |
| 4.6 | Geo + date stamp — taluka + district + date (e.g. *Dindori Taluka, Nashik — June 30, 2026*) | M |
| 4.7 | Separate scoring logic for **rural borewell** vs **urban reservoir/society** | M |
| 4.8 | Score history / trend over time | C |

---

## 5. ALERTING & NOTIFICATION

| # | Functionality | Pri |
|---|---|---|
| 5.1 | **WhatsApp** as primary delivery channel | M |
| 5.2 | **Trilingual output: Marathi, Hindi, English** (user-selectable) | M |
| 5.3 | Alert fires **30 days before** predicted crisis | M |
| 5.4 | Escalation ladder — alerts at 30d / 15d / 7d as band worsens | S |
| 5.5 | Alerts are **actionable**, not informational only (differentiator vs existing systems) | M |
| 5.6 | Embedded **conservation guidance** in each alert | M |
| 5.7 | **Workshop booking CTA inside the alert** | S |
| 5.8 | Workshop catalogue: rainwater harvesting · groundwater recharge · leak detection · household water conservation | S |
| 5.9 | Role-specific alert copy (farmer vs society vs official) | S |
| 5.10 | Subscription / opt-in + language preference management | M |
| 5.11 | Delivery log & failure retry | C |

---

## 6. USER SEGMENTS & THEIR FEATURES

### 6.1 Rural farmers + gram panchayats `[M]`
- Predict **borewell failure** 30 days out
- **Irrigation plan** improvement / crop-switch recommendation
- Outcome: 30 days to switch irrigation, avoiding total crop loss

### 6.2 Urban housing societies `[M]`
- Early **water-shortage alerts** for the society
- **Tanker booking planning** — order early, avoid ₹3,000 emergency rate
- Society-level (not individual) subscription entity

### 6.3 Government officials `[S]`
- **Smart resource allocation** view
- Dashboard converting existing fragmented datasets into **predictive insights**
- District / taluka roll-up view

### 6.4 Citizens & communities `[S]`
- Multilingual alerts
- Water-saving guidance library
- **Workshop access / booking**

---

## 7. AQUA CREDITS — INCENTIVE SYSTEM

| # | Functionality | Pri |
|---|---|---|
| 7.1 | Credits earned per **verified** water-saving action | S |
| 7.2 | Action verification mechanism (photo / meter / community attest) | C |
| 7.3 | Credit ledger per user/household/society | S |
| 7.4 | Redemption against **municipal water-tax rebates** | F |
| 7.5 | Redemption against **partner workshop fees** | F |
| 7.6 | Log credits back into **Water 7/12** | F |
| 7.7 | Leaderboard / gamification for villages & societies | C |

---

## 8. INTEGRATIONS

| # | System | Direction | Pri |
|---|---|---|---|
| 8.1 | **Maharashtra Water 7/12** (announced 25 May 2026) | read + write-back | S |
| 8.2 | **Bhujal App** | read (community readings) | F |
| 8.3 | **WhatsApp Business API** | write (alerts) + read (Jal Mitra reports) | M |
| 8.4 | NASA GRACE-FO | read | S |
| 8.5 | GSDA | read | M |
| 8.6 | IMD | read | M |
| 8.7 | BMC / PMC | read | M |
| 8.8 | CGWB | read | C |

---

## 9. NON-FUNCTIONAL REQUIREMENTS (these are pitch claims — must hold true)

| # | Requirement | Pri |
|---|---|---|
| 9.1 | **₹0 prototype cost** — open data only, no paid APIs | M |
| 9.2 | **Zero hardware** required at the user end | M |
| 9.3 | Hardware (IoT smart meter) is strictly **optional** | F |
| 9.4 | State-agnostic architecture — works for any water-stressed state (Gujarat proof point) | S |
| 9.5 | Scales to **43,228 CGWB wells** with no extra cost | C |
| 9.6 | Sub-minute community reporting UX | M |
| 9.7 | Works on low-end phones / low bandwidth (WhatsApp-first, no app install) | M |

---

## 10. FUTURE SCOPE (explicitly Stage-2+, do NOT build by Tuesday)

- GSDA live-data validation of accuracy claims
- Field pilots in Nashik
- IoT smart-meter integration
- Pan-India scale-out via Aqua Credits + workshops
- Solving true taluka-level GRACE-FO downscaling

---

# PROGRESS TRACKING CHECKLIST

Tick these as you go. Anything marked `[M]` must be green by Monday night.

## Phase 0 — Setup
- [ ] 0.1 Repo + folder structure created
- [ ] 0.2 Tech stack locked (backend / ML / DB / WhatsApp provider)
- [ ] 0.3 Env + secrets file
- [ ] 0.4 This functionality list frozen and signed off

## Phase 1 — Data
- [ ] 1.1 GSDA borewell historical CSV sourced (or synthetic stand-in generated)
- [ ] 1.2 IMD rainfall data sourced
- [ ] 1.3 BMC reservoir % sourced
- [ ] 1.4 GRACE-FO sample downloaded
- [ ] 1.5 Unified feature table built (well_id, date, depth, rainfall, ET, soil moisture, reservoir%)
- [ ] 1.6 Data cleaning + gap-fill done
- [ ] 1.7 Train/test split created

## Phase 2 — Model
- [ ] 2.1 Baseline (linear/persistence) benchmark recorded
- [ ] 2.2 LSTM trained, 30-day horizon
- [ ] 2.3 XGBoost trained on weather features
- [ ] 2.4 Ensemble combined
- [ ] 2.5 Bayesian validation layer wired
- [ ] 2.6 Accuracy measured @7d / @15d / @30d and written down
- [ ] 2.7 Model serialised + loadable

## Phase 3 — Scoring
- [ ] 3.1 0–100 stress score formula implemented
- [ ] 3.2 Band thresholds (0-40/41-70/71-100) applied
- [ ] 3.3 Days-to-crisis calculation
- [ ] 3.4 Rural variant working
- [ ] 3.5 Urban/society variant working
- [ ] 3.6 Score card JSON matches the poster sample (87 / 30 days / RED / Marathi / Dindori)

## Phase 4 — Community Input
- [ ] 4.1 WhatsApp inbound webhook receiving messages
- [ ] 4.2 Borewell-depth report flow (<1 min, ≤4 questions)
- [ ] 4.3 Report stored with geotag + timestamp
- [ ] 4.4 Bayesian outlier filter rejecting bad reports

## Phase 5 — Alerts
- [ ] 5.1 WhatsApp outbound send working
- [ ] 5.2 Marathi template
- [ ] 5.3 Hindi template
- [ ] 5.4 English template
- [ ] 5.5 Language preference stored per user
- [ ] 5.6 Farmer alert copy + conservation tip
- [ ] 5.7 Society alert copy + tanker-planning tip
- [ ] 5.8 Workshop booking reply option
- [ ] 5.9 Trigger logic: alert fires when days-to-crisis ≤ 30

## Phase 6 — Dashboard / Demo Surface
- [ ] 6.1 Map or list of talukas with colour-coded scores
- [ ] 6.2 Single-well detail view with 30-day forecast chart
- [ ] 6.3 Government roll-up view
- [ ] 6.4 Aqua Credits balance display

## Phase 7 — Aqua Credits
- [ ] 7.1 Credit ledger table
- [ ] 7.2 Award credits on verified action
- [ ] 7.3 Balance visible to user via WhatsApp

## Phase 8 — Verification (Monday)
- [ ] 8.1 End-to-end run: raw data → score → WhatsApp alert received on a real phone
- [ ] 8.2 All three languages verified by a native reader
- [ ] 8.3 Accuracy numbers on the poster match what the model actually produces (or poster corrected)
- [ ] 8.4 ₹0 cost claim verified — no paid service in the stack
- [ ] 8.5 Demo script written + 3 dry runs
- [ ] 8.6 Fallback recorded video in case live demo fails
- [ ] 8.7 Known-limitations slide honest about GRACE-FO downscaling

---

## OPEN QUESTIONS (block the roadmap until answered)

1. **Tech stack** — Python/FastAPI + Streamlit? Node? What's the team comfortable with?
2. **WhatsApp** — real Business API (needs approval, may not land by Tue) vs. Twilio sandbox vs. simulated chat UI in the demo?
3. **Data reality** — do we actually have GSDA borewell CSVs, or do we generate a realistic synthetic dataset for the prototype?
4. **Team size** — how many people, and who does ML vs. backend vs. frontend vs. deck?
5. **Demo format** — live web dashboard, WhatsApp on a real phone, or a recorded walkthrough?
6. **Scope call** — is a real trained LSTM required for Tuesday, or is a working pipeline with a simpler model acceptable for the prototype stage?
