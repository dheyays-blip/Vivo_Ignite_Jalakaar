# Jalaakar — quickstart

```bash
git clone https://github.com/orgkushal/Jalakaar.git && cd Jalakaar
make setup
make run
```

Then open **http://localhost:8000**.

That is the whole thing: the API and the website are served together on one
port. `make setup` takes about a minute and needs no network beyond the clone
itself.

Optional, if you want accounts to play with:

```bash
make demo-user      # 5 accounts, password: jalaakar-demo
```

---

## What `make setup` actually does

1. creates `.venv` and installs `requirements.txt` + `requirements-api.txt`
2. runs `tools/bootstrap.py`, which builds `data/jalaakar.db` from the Parquet
   files in `data/bootstrap/`

Step 2 exists because the working database is **1.9 GB** and cannot live in
git. What the repository ships instead is the irreducible part — the well
registry, the 68,994 real CGWB readings, and the weather series — and
everything derived from them is rebuilt on your machine:

| Table | Where it comes from |
|---|---|
| `wells`, `gw_observations`, `weather_daily` | shipped as Parquet (Git LFS) |
| `reservoirs`, `reservoir_daily` | rebuilt from `ingest/reservoir_seeds.csv` |
| `urban_stress` | computed by `ingest/07_stress.py` |

**Measurements are shipped; outputs are rebuilt.** That way nobody inherits a
stale copy of a number they cannot trace back to a source.

The whole download is about **29 MB** of Git LFS. If the Parquet files are
missing after cloning, LFS did not run:

```bash
git lfs install && git lfs pull
```

### Verifying a clone from scratch

```bash
cd /tmp && rm -rf jal-check
git clone https://github.com/orgkushal/Jalakaar.git jal-check && cd jal-check
make setup && make test
```

Expect `data/jalaakar.db built — 490 MB`, then `98/98 passed` and
`5 pages, 0 problem(s)`. If the database comes out much smaller than that,
`weather_daily` did not load and scores will not match the published MAE.

## Commands

| | |
|---|---|
| `make setup` | venv, dependencies, database |
| `make run` | serve on :8000 (`PORT=9000 make run` to change) |
| `make test` | 98 API checks plus the frontend audit |
| `make audit` | frontend only — links, classes, cache stamps |
| `make demo-user` | create demo accounts |
| `make users` | who registered, and when (phones masked) |
| `make delete-user PHONE=9…` | remove one account, keep its alert history |
| `make whatsapp-check` | will a send really deliver? contacts nothing |
| `make reset` | clear signups and alerts |
| `make clean` | remove `.venv` and the built database |

No `make`? The three underlying commands are:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-api.txt
.venv/bin/python tools/bootstrap.py
.venv/bin/uvicorn api.main:app --port 8000
```

## Optional: real WhatsApp delivery

Without credentials, alerts are **rendered and logged, never faked as
delivered** — the UI says so explicitly. To send for real, join the free
[Twilio WhatsApp sandbox](https://www.twilio.com/docs/whatsapp/sandbox), then:

```bash
cp .env.example .env      # then paste in your SID and auth token
make whatsapp-check       # confirms the send path will deliver
```

`.env` is gitignored and loaded automatically by both the server and the CLI —
an `export` in one terminal does not survive `--reload` respawning the worker,
which is the usual reason a send that worked once quietly stops delivering.

Then the first real end-to-end send:

```bash
.venv/bin/python tools/send_test_alert.py --phone 9YOURNUMBER --place Baglan --lang mr
```

The recipient's phone must WhatsApp the join phrase to **+1 415 523 8886**
first, and that session expires 3 days after joining. Errors 63015 / 63016 mean
exactly that — rejoin and re-send.

## Retraining

`models/xgb_causal.json` is committed, so the API forecasts out of the box.
To rebuild it from scratch:

```bash
.venv/bin/python ingest/06b_features_causal.py    # causal feature table
.venv/bin/python ml/01_baseline.py                # the bar to beat
.venv/bin/python ml/02_xgboost.py                 # train
.venv/bin/python api/verify_model.py              # serving == published MAE
```

`verify_model.py` is the one that matters: it replays held-out rows through the
live serving path and checks the result against the accuracy the site
advertises. If it prints `DIVERGED`, do not quote the numbers.

## What to look at first

- **http://localhost:8000/demo.html** — score any of 247 talukas, or Mumbai and
  Pune reservoirs. Try **Nashik → Baglan** (78, act now) against
  **Nashik → Dindori** (31, safe), then the Urban tab with Mumbai at
  29 Jun 2026 (90, act now) versus today (0, safe).
- **http://localhost:8000/admin.html** — the control room: every taluka and
  reservoir at once, worst first, and one button that warns everyone in a
  severity bucket. Run `make demo-user` first, then sign in as
  **9800000001 / jalaakar-demo** (the government account, already verified).
  Click **Preview messages** before **Send now** — the preview renders the real
  bodies and writes nothing.
- **http://localhost:8000/docs** — every endpoint, interactive.
- `DATA_CARD.md` and `SOURCES.md` — every figure and where it came from.
