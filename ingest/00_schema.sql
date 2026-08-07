-- =====================================================================
-- JALAAKAR — DATA INGESTION SCHEMA  (the contract)
-- Owner: Dev B. Frozen Fri 7 Aug 19:30. DO NOT CHANGE without telling A.
--
-- Everything downstream (ML track, alerting track) reads from these
-- tables only. Nobody touches raw sources directly.
--
-- Conventions:
--   * level_mbgl = metres BELOW ground level. BIGGER = DEEPER = WORSE.
--   * All dates stored as TEXT 'YYYY-MM-DD' (SQLite date functions work).
--   * All booleans stored as INTEGER 0/1.
--   * season ∈ pre_monsoon | monsoon | post_monsoon | rabi
-- =====================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------
-- 1. wells — rural registry (one row per well)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wells (
    well_id         TEXT    PRIMARY KEY,
    lat             REAL    NOT NULL,
    lon             REAL    NOT NULL,
    district        TEXT,
    taluka          TEXT,
    village         TEXT,
    specific_yield  REAL,               -- from figshare; level -> volume
    aquifer_type    TEXT,
    n_observations  INTEGER,
    first_obs       TEXT,               -- DATE
    last_obs        TEXT,               -- DATE
    CHECK (lat BETWEEN  6.0 AND 38.0),
    CHECK (lon BETWEEN 68.0 AND 98.0)
);
CREATE INDEX IF NOT EXISTS idx_wells_taluka   ON wells(taluka);
CREATE INDEX IF NOT EXISTS idx_wells_district ON wells(district);

-- ---------------------------------------------------------------------
-- 2. gw_observations — REAL measured points (sparse, seasonal)
--    Never contains an interpolated value. Ever.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gw_observations (
    well_id      TEXT NOT NULL REFERENCES wells(well_id) ON DELETE CASCADE,
    obs_date     TEXT NOT NULL,          -- DATE
    level_mbgl   REAL NOT NULL,
    season       TEXT,
    source       TEXT NOT NULL,          -- 'figshare' | 'gsda'
    is_last_5y   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (well_id, obs_date, source),
    CHECK (season IN ('pre_monsoon','monsoon','post_monsoon','rabi')),
    CHECK (source IN ('figshare','gsda','synthetic')),
    CHECK (is_last_5y IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_obs_date ON gw_observations(obs_date);
CREATE INDEX IF NOT EXISTS idx_obs_well ON gw_observations(well_id);

-- ---------------------------------------------------------------------
-- 3. weather_daily — dense daily, from Open-Meteo (ERA5 archive)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_daily (
    well_id         TEXT NOT NULL,       -- well_id OR reservoir_id
    date            TEXT NOT NULL,       -- DATE
    precip_mm       REAL,
    et0_mm          REAL,
    soil_moist_0_7  REAL,
    soil_moist_7_28 REAL,
    temp_max        REAL,
    rh_mean         REAL,
    PRIMARY KEY (well_id, date)
);
CREATE INDEX IF NOT EXISTS idx_weather_date ON weather_daily(date);

-- ---------------------------------------------------------------------
-- 4. gw_daily — INTERPOLATED daily levels (the keystone). Dev A owns.
--    is_observed = 1 ONLY on genuine measurement dates. Non-negotiable.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gw_daily (
    well_id      TEXT NOT NULL REFERENCES wells(well_id) ON DELETE CASCADE,
    date         TEXT NOT NULL,          -- DATE
    level_mbgl   REAL NOT NULL,
    is_observed  INTEGER NOT NULL DEFAULT 0,
    confidence   REAL,                   -- 0..1, decays from nearest real obs
    PRIMARY KEY (well_id, date),
    CHECK (is_observed IN (0,1)),
    CHECK (confidence IS NULL OR confidence BETWEEN 0.0 AND 1.0)
);
CREATE INDEX IF NOT EXISTS idx_gwd_date     ON gw_daily(date);
CREATE INDEX IF NOT EXISTS idx_gwd_observed ON gw_daily(is_observed);

-- ---------------------------------------------------------------------
-- 5. reservoirs — urban registry (12 rows)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reservoirs (
    reservoir_id  TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,         -- 'Mumbai' | 'Pune'
    lat           REAL,
    lon           REAL,
    capacity_mcm  REAL
);

-- ---------------------------------------------------------------------
-- 6. reservoir_daily
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reservoir_daily (
    reservoir_id         TEXT NOT NULL REFERENCES reservoirs(reservoir_id) ON DELETE CASCADE,
    date                 TEXT NOT NULL,  -- DATE
    live_storage_pct     REAL,
    storage_mcm          REAL,
    pct_same_day_last_yr REAL,
    source               TEXT,           -- provenance: 'wrd_pravah' | 'manual'
    PRIMARY KEY (reservoir_id, date)
);
CREATE INDEX IF NOT EXISTS idx_resd_date ON reservoir_daily(date);

-- ---------------------------------------------------------------------
-- 7. features — FINAL joined training table. The ONLY table the ML
--    track reads. Wide by design; nulls are not acceptable in the
--    required columns (see notebooks/validate.ipynb).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS features (
    entity_id             TEXT NOT NULL,
    entity_type           TEXT NOT NULL,      -- 'well' | 'reservoir'
    date                  TEXT NOT NULL,

    -- state
    level                 REAL,               -- mbgl (well) or storage_pct (reservoir)
    is_observed           INTEGER,
    confidence            REAL,

    -- weather (same day)
    precip_mm             REAL,
    et0_mm                REAL,
    soil_moist_0_7        REAL,
    soil_moist_7_28       REAL,
    temp_max              REAL,
    rh_mean               REAL,

    -- level lags
    level_lag_7           REAL,
    level_lag_15          REAL,
    level_lag_30          REAL,
    level_lag_60          REAL,
    level_lag_90          REAL,

    -- rolling rainfall
    rain_7d               REAL,
    rain_30d              REAL,
    rain_90d              REAL,
    days_since_last_rain  INTEGER,
    cum_monsoon_rainfall  REAL,               -- resets 1 June each year

    -- dynamics
    level_change_7d       REAL,
    level_change_30d      REAL,
    et0_30d               REAL,

    -- calendar
    month                 INTEGER,
    doy                   INTEGER,
    season                TEXT,

    -- target + bookkeeping
    target_level_t30      REAL,               -- level at t+30 days
    is_last_5y            INTEGER,
    split                 TEXT,               -- 'train' | 'val' | 'test'

    PRIMARY KEY (entity_id, date),
    CHECK (entity_type IN ('well','reservoir')),
    CHECK (split IN ('train','val','test'))
);
CREATE INDEX IF NOT EXISTS idx_feat_split  ON features(split);
CREATE INDEX IF NOT EXISTS idx_feat_date   ON features(date);
CREATE INDEX IF NOT EXISTS idx_feat_entity ON features(entity_type, entity_id);

-- ---------------------------------------------------------------------
-- 8. ingest_log — provenance. Every script writes one row per run.
--    This is what DATA_CARD.md is generated from.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_log (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    script     TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    rows_in    INTEGER,
    rows_out   INTEGER,
    status     TEXT,                    -- 'ok' | 'failed'
    notes      TEXT
);

-- ---------------------------------------------------------------------
-- Convenience views
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_observed_ratio AS
SELECT
    COUNT(*)                                              AS n_daily_rows,
    SUM(is_observed)                                      AS n_observed,
    ROUND(100.0 * SUM(is_observed) / NULLIF(COUNT(*),0), 2) AS pct_observed
FROM gw_daily;

CREATE VIEW IF NOT EXISTS v_well_coverage AS
SELECT w.well_id, w.district, w.taluka,
       w.n_observations,
       MIN(g.date) AS daily_start,
       MAX(g.date) AS daily_end,
       COUNT(g.date) AS n_daily
FROM wells w LEFT JOIN gw_daily g ON g.well_id = w.well_id
GROUP BY w.well_id;
