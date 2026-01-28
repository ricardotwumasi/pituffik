-- Pituffik database schema
-- SQLite with WAL mode for concurrent reads (dashboard).

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Canonical grant opportunity records
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id          TEXT PRIMARY KEY,              -- SHA-256(canonical_url)[:16]
    url_canonical           TEXT NOT NULL UNIQUE,
    url_source              TEXT NOT NULL,
    source_id               TEXT NOT NULL,                 -- e.g. "ukri", "nih_rss"
    title                   TEXT,
    funder_name             TEXT,
    scheme_name             TEXT,
    country_or_region       TEXT,
    language                TEXT DEFAULT 'en',
    deadline_date           TEXT,                          -- ISO 8601 date
    deadline_type           TEXT DEFAULT 'unknown',        -- fixed, rolling, none, unknown
    open_date               TEXT,                          -- ISO 8601 date
    status                  TEXT DEFAULT 'unverified',     -- open, closed, unverified
    summary_en              TEXT,                          -- English synopsis
    topics                  TEXT,                          -- JSON array of strings
    eligibility             TEXT,                          -- short structured text
    career_stage            TEXT,                          -- e.g. "early career", "mid-career"
    amount_min              REAL,
    amount_max              REAL,
    amount_currency         TEXT,                          -- ISO 4217 code
    amount_gbp_min          REAL,                          -- converted via ECB rates
    amount_gbp_max          REAL,
    amount_confidence       TEXT DEFAULT 'unknown',        -- high, medium, low, unknown
    duration_months         INTEGER,
    host_institution_required INTEGER,                     -- boolean
    grant_type_bucket       TEXT,                          -- fellowship, project, programme, etc.
    grant_type_source       TEXT DEFAULT 'regex',          -- regex or gemini
    relevance_score         REAL,                          -- 0.0 to 1.0
    health_research_match   INTEGER DEFAULT 0,             -- boolean
    relevance_rationale     TEXT,                          -- one-sentence Gemini justification
    first_seen_at           TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at            TEXT NOT NULL DEFAULT (datetime('now')),
    last_verified_at        TEXT,
    emailed_at              TEXT,                          -- when included in a digest
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_opp_source ON opportunities(source_id);
CREATE INDEX IF NOT EXISTS idx_opp_deadline ON opportunities(deadline_date);
CREATE INDEX IF NOT EXISTS idx_opp_relevance ON opportunities(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_opp_grant_type ON opportunities(grant_type_bucket);
CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opp_first_seen ON opportunities(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_opp_funder ON opportunities(funder_name);
CREATE INDEX IF NOT EXISTS idx_opp_amount_gbp ON opportunities(amount_gbp_min);

-- Raw HTML/text snapshots per crawl (for change detection)
CREATE TABLE IF NOT EXISTS opportunity_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id          TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    http_status             INTEGER,
    content_type            TEXT,
    content_text            TEXT,
    content_html            TEXT,
    content_hash            TEXT NOT NULL,                 -- SHA-256 of content_text
    extractor_version       TEXT DEFAULT 'v1',
    notes                   TEXT,
    captured_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snap_opp ON opportunity_snapshots(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_snap_hash ON opportunity_snapshots(content_hash);

-- Gemini enrichment outputs (cached by input hash)
CREATE TABLE IF NOT EXISTS enrichments (
    enrichment_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id          TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    task_type               TEXT NOT NULL,                 -- relevance, extraction, synopsis, grant_type_fallback
    prompt_version          TEXT NOT NULL,
    model_id                TEXT NOT NULL,
    input_hash              TEXT NOT NULL,                 -- SHA-256(prompt_version + text)
    output_json             TEXT NOT NULL,                 -- raw Gemini JSON response
    tokens_used             INTEGER,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(opportunity_id, task_type, input_hash)
);

CREATE INDEX IF NOT EXISTS idx_enrich_opp ON enrichments(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_enrich_cache ON enrichments(input_hash, task_type);

-- Pipeline run audit log
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at              TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at             TEXT,
    status                  TEXT DEFAULT 'running',        -- running, completed, failed
    opportunities_found     INTEGER DEFAULT 0,
    opportunities_new       INTEGER DEFAULT 0,
    opportunities_updated   INTEGER DEFAULT 0,
    enrichments_made        INTEGER DEFAULT 0,
    emails_sent             INTEGER DEFAULT 0,
    errors                  TEXT,                          -- JSON array of error strings
    run_metadata            TEXT                           -- JSON object with additional info
);

-- ECB exchange rates cached by date and currency
CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date               TEXT NOT NULL,                 -- ISO 8601 date
    currency                TEXT NOT NULL,                 -- ISO 4217 code
    rate_to_eur             REAL NOT NULL,                 -- 1 EUR = X units of currency
    rate_to_gbp             REAL,                          -- 1 unit of currency = X GBP
    fetched_at              TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (rate_date, currency)
);

-- User actions (future: saved/hidden/notes)
CREATE TABLE IF NOT EXISTS user_actions (
    action_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id          TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    action_type             TEXT NOT NULL,                 -- saved, hidden, note
    action_data             TEXT,                          -- optional JSON payload
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_user_act_opp ON user_actions(opportunity_id);
