# Working agreement — Jalaakar ingestion

Window: **Fri 7 Aug 19:00 → Sat 8 Aug 20:00 IST (FROZEN).** Demo Tue 11 Aug.
Two devs. Speed matters more than ceremony, but three rules are non-negotiable.

## 1. Never edit a file you don't own

| Path | Owner |
|---|---|
| `ingest/01_figshare.py`, `02_wells.py`, `05_interpolate.py` | **A** |
| `ingest/00_schema.sql`, `db.py`, `03_openmeteo.py`, `04_reservoirs.py`, `06_features.py` | **B** |
| `ingest/reservoir_seeds.csv` | **B** |
| `notebooks/`, `tools/` | **B** |
| `config.yaml`, `README.md`, `CONTRIBUTING.md` | ⚠️ shared — message before editing |

Need a change in the other person's file? Message them. This one rule prevents
about 95% of the conflicts you would otherwise hit.

## 2. Branches are long-lived — merge, never squash

```
main                  ← merge at the 5 checkpoints only
├── ingest/a-wells    ← Dev A   (lives the whole sprint)
└── ingest/b-weather  ← Dev B   (lives the whole sprint)
```

**Do not squash-merge.** These branches get merged into `main` repeatedly and then
keep going. A squash rewrites the history so git no longer recognises the shared
commits, and your next merge re-conflicts on everything you already resolved.
Use a normal merge commit every time.

**After every merge to `main`, pull it back into your branch:**
```bash
git checkout ingest/a-wells   # or ingest/b-weather
git merge main
```
Skip this and your branches drift until the Saturday 16:00 merge becomes a nightmare.

## 3. Never commit heavy or generated data

The SQLite DB, weather parquet and the figshare download stay out of git. They
regenerate in ~20 minutes, and binary merge conflicts cost an hour nobody has.
Git holds **code + small reference CSVs** (`mh_wells.csv`, `reservoirs.csv`).

## Pull requests

Open a PR for each checkpoint merge, then **merge it yourself** — do not wait for
the other person. The PR is a record of what changed, not a gate. If the other dev
is asleep, merge anyway.

## Commits

```
feat(ingest): add open-meteo client with coord dedupe
fix(wells): correct mbgl sign convention
data(gate): maharashtra well count = 187
chore(repo): add gitattributes
```
Push at least every 2 hours, even mid-task. `git pull --rebase origin main` before
every push.

## Checkpoints (merge to `main` at these, and only these)

| Time | Gate |
|---|---|
| Fri 19:30 | Schema pushed by B, confirmed working by A |
| Fri 20:15 | 🚦 Maharashtra well count announced |
| Fri 23:00 | Merge both branches. Weather + wells loaded. |
| Sat 12:00 | Interpolation curve reviewed |
| Sat 16:00 | `features` populated. Merge. |
| Sat 20:00 | 🔒 FREEZE — tag `v1-data-frozen`, write `DATA_CARD.md` |
