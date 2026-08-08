# JALAAKAR — INGESTION WORK SPLIT (2 DEVS)

**Window:** Fri 7 Aug 19:00 → Sat 8 Aug 20:00 (FROZEN)
**Load:** ~4.5 focused hours each
**Repo:** `jalaakar` · branches `ingest/a-wells` and `ingest/b-weather`

---

## THE PROBLEM WITH SPLITTING THIS

The pipeline is mostly a chain — figshare → wells → weather → interpolation →
features. A naive "you do stages 1–3, I do 4–6" leaves Dev B idle all Friday night
waiting on Dev A.

**The unblock:** Dev B writes the **schema + DB layer first** (20–30 min), and builds
the Open-Meteo client against **3 hardcoded Nashik coordinates** instead of waiting
for the real well list. When Dev A's wells land, B swaps the stub list for the real
one — a one-line change. Reservoirs are fully independent and need nothing from A.

Result: both people are productive from minute one.

```
     Dev A  ──  figshare → wells → INTERPOLATION → ...
                    │        │           ▲
                    │        └── wells.csv ──┐
                    ▼                        │
     Dev B  ──  schema → openmeteo(stub→real) ┘ → features
                    └── reservoirs (independent) ──────┘
```

---

## DEV A — "RURAL / WELLS TRACK"

**Owns:** the critical path and the keystone algorithm.
**Branch:** `ingest/a-wells`
**Files owned (nobody else touches these):**
`ingest/01_figshare.py` · `ingest/02_wells.py` · `ingest/05_interpolate.py`

| # | Task | Time | Output |
|---|---|---|---|
| A0 | Create repo, push skeleton + `.gitignore` + `config.yaml`, invite B | 20 m | `main` exists |
| A1 | Download figshare, inspect schema, filter Maharashtra, **RUN THE GATE** | 45 m | 🚦 well count → announce to B |
| A2 | Normalise district/taluka names, derive season, set `is_last_5y`, confirm mbgl sign, check Dindori has a well | 45 m | **`data/interim/mh_wells.csv`** ← B's unblock |
| A3 | Load `wells` + `gw_observations` into SQLite | 20 m | 2 tables populated |
| A4 | **Daily interpolation** — recession fit, rainfall-driven recharge scaled by specific yield, reconcile to next real obs, confidence decay | 150 m | `gw_daily` table |
| A5 | Hold out every 4th observation, measure interpolation MAE, plot a Dindori well | 30 m | **MAE number** for the demo script |

**Total ≈ 5h 10m**

**A's non-negotiables:**
- `is_observed` must be TRUE only on genuine measurement dates. Never fudge this.
- Write the held-out MAE down. It's your answer to "how accurate is the interpolation?"
- If the gate comes back Red (<50 wells), **tell B immediately** — B pivots to the GSDA probe.

---

## DEV B — "WEATHER / URBAN / QUALITY TRACK"

**Owns:** the schema contract, all external APIs, and validation.
**Branch:** `ingest/b-weather`
**Files owned:**
`ingest/00_schema.sql` · `ingest/db.py` · `ingest/03_openmeteo.py` ·
`ingest/04_reservoirs.py` · `ingest/06_features.py` · `notebooks/validate.ipynb`

| # | Task | Time | Output |
|---|---|---|---|
| B0 | Write `schema.sql` (all 7 tables) + `db.py` connect/upsert helpers. **Push within 30 min — A needs it.** | 30 m | 🔑 the contract |
| B1 | Open-Meteo client **against 3 hardcoded Nashik coords**. Cache via `requests-cache`, 0.5 s sleep, coord dedupe to 0.1° | 60 m | working client, no dependency on A |
| B2 | Swap stub for A's `mh_wells.csv`, run full pull, load `weather_daily` | 30 m | dense daily weather |
| B3 | **Reservoirs** — 12 water bodies, June 2026 + current values, last-year column | 45 m | `reservoirs`, `reservoir_daily` |
| B4 | Feature engineering — lags 7/15/30/60/90d, rolling rainfall, days_since_rain, cum_monsoon, calendar, target t+30, chronological splits | 60 m | `features` table |
| B5 | Validation notebook + `DATA_CARD.md` — null checks, dupe checks, monsoon spike plot, observed-vs-interpolated ratio | 45 m | QA sign-off |

**Total ≈ 4h 30m**

**B's non-negotiables:**
- **Push `schema.sql` first, before anything else.** A is blocked on it.
- Splits are **chronological, never random.** Random splits leak the future and will
  silently inflate your accuracy.
- Verify the monsoon spike is visibly Jun–Sep in the rainfall plot. If not, dates or
  units are wrong — catch it Friday, not Monday.

---

## HANDOFF CONTRACTS

These four artifacts are the only coupling between the two of you. Everything else is
independent.

| # | From → To | Artifact | Due | Blocks |
|---|---|---|---|---|
| H1 | **B → A** | `ingest/00_schema.sql` + `db.py` | **Fri 19:30** | A3 onward |
| H2 | **A → B** | `data/interim/mh_wells.csv`<br>`well_id, lat, lon, district, taluka, specific_yield` | **Fri 20:15** | B2 |
| H3 | **A → B** | `gw_daily` populated (or the script to regenerate) | **Sat 13:00** | B4 |
| H4 | **B → A** | `weather_daily` populated | **Fri 23:00** | A4 |

**If a handoff is late, the waiting person does NOT sit idle** — they pick up the next
item on their own list and pull the handoff when it lands.

---

## GIT WORKFLOW

### Branches
```
main                  ← always working, merge at checkpoints only
├── ingest/a-wells    ← Dev A
└── ingest/b-weather  ← Dev B
```

### File ownership prevents 95% of conflicts
| Path | Owner |
|---|---|
| `ingest/01_,02_,05_*.py` | **A only** |
| `ingest/00_schema.sql, db.py, 03_,04_,06_*.py` | **B only** |
| `config.yaml`, `README.md` | ⚠️ **shared — agree upfront, then avoid** |

**Rule: never edit a file you don't own.** If you need a change in the other person's
file, message them. This one rule is worth more than any branching strategy.

### `.gitignore`
```gitignore
data/raw/
data/interim/*.parquet
data/*.db
.cache/
__pycache__/
*.pyc
.venv/
.ipynb_checkpoints/

# committed exceptions — small, text, diffable
!data/interim/mh_wells.csv
!data/interim/reservoirs.csv
```

**Do not commit the SQLite DB or weather parquet.** Binary files produce unresolvable
merge conflicts and will cost you an hour you don't have. The scripts are
deterministic and Open-Meteo is free — anyone can regenerate the heavy data in ~20
minutes. Git holds **code + small reference CSVs**; everything else regenerates.

### Commits
```
feat(ingest): add open-meteo client with coord dedupe
fix(wells): correct mbgl sign convention
data(gate): maharashtra well count = 187
```
Push **at least every 2 hours**, even mid-task. `git pull --rebase origin main` before
every push.

### Merges to `main`
Only at the five checkpoints below. Fast review — read the diff, confirm it runs, merge.
No blocking PR ceremony; you have four days.

---

## SYNC POINTS (5-minute calls, camera off)

| Time | Agenda | Fail action |
|---|---|---|
| **Fri 19:30** | Schema agreed. B has pushed it. A confirms it works. | — |
| **Fri 20:15** | 🚦 **Gate result.** A announces MH well count. Confirm Dindori has a well. | <50 wells → B drops B1 and runs the GSDA probe (Appendix A) instead |
| **Fri 23:00** | Merge both branches to `main`. Weather + wells both loaded. | Either missing → finish it before sleeping |
| **Sat 12:00** | Interpolation curve reviewed by B. Does it look hydrologically real? | Looks fake → A falls back to linear + rainfall bump, ships it, moves on |
| **Sat 16:00** | `features` populated. Merge to `main`. | Not ready → **cut the urban track**, ship rural only |
| **Sat 20:00** | 🔒 **FREEZE.** Tag `v1-data-frozen`. Write DATA_CARD. | Ship whatever exists. **Do not extend.** |

---

## IF SOMEONE FINISHES EARLY

Do **not** start a new data source. In priority order:

1. Help the other person — interpolation (A4) is the hardest task; a second pair of eyes is worth more than a new feature.
2. Run the **GSDA probe** (Appendix A) — pure upside, zero risk, fully optional.
3. Start the **stress-score module** (0–100, three bands, days-to-crisis). It reads from `features` and is the next thing needed anyway.
4. Write the demo script and the "how did you get daily data from seasonal readings?" answer.

---

## THE TWO SENTENCES BOTH OF YOU MUST BE ABLE TO SAY

> **On the data:** "We anchor on quality-controlled seasonal observations from a
> peer-reviewed IISc dataset and interpolate daily using rainfall-conditioned
> recession curves scaled by each well's specific yield, validated against held-out
> readings at X.XX m MAE."

> **On the demo date:** "The scenario is 30 June 2026, pre-monsoon. Run it on today's
> data and the model correctly returns SAFE — the reservoirs are full."

Neither of you should ever say *"we trained on 5 years of daily GSDA data."*
