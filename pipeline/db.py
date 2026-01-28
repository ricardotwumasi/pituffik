"""Database access layer for Pituffik.

Provides functions for all SQLite operations: schema initialisation,
opportunity CRUD, snapshot storage, enrichment caching, FX rates, and
pipeline run logging.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from pipeline.models import (
    Enrichment,
    FxRate,
    Opportunity,
    OpportunitySnapshot,
    PipelineRun,
)

logger = logging.getLogger(__name__)

# Path to the schema DDL file
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_schema.sql"
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "grants.sqlite"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection to the SQLite database, creating it if needed."""
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialise_schema(conn: sqlite3.Connection) -> None:
    """Run the seed schema DDL to create tables if they don't exist."""
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    logger.info("Database schema initialised")


# -- Opportunities --

def upsert_opportunity(conn: sqlite3.Connection, opp: Opportunity) -> bool:
    """Insert or update an opportunity. Returns True if a new row was created."""
    now = datetime.utcnow().isoformat()
    existing = conn.execute(
        "SELECT opportunity_id FROM opportunities WHERE opportunity_id = ?",
        (opp.opportunity_id,),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE opportunities SET
                url_source = ?,
                title = COALESCE(?, title),
                funder_name = COALESCE(?, funder_name),
                scheme_name = COALESCE(?, scheme_name),
                country_or_region = COALESCE(?, country_or_region),
                language = COALESCE(?, language),
                deadline_date = COALESCE(?, deadline_date),
                deadline_type = COALESCE(?, deadline_type),
                open_date = COALESCE(?, open_date),
                status = COALESCE(?, status),
                summary_en = COALESCE(?, summary_en),
                topics = COALESCE(?, topics),
                eligibility = COALESCE(?, eligibility),
                career_stage = COALESCE(?, career_stage),
                amount_min = COALESCE(?, amount_min),
                amount_max = COALESCE(?, amount_max),
                amount_currency = COALESCE(?, amount_currency),
                amount_usd_min = COALESCE(?, amount_usd_min),
                amount_usd_max = COALESCE(?, amount_usd_max),
                amount_confidence = COALESCE(?, amount_confidence),
                duration_months = COALESCE(?, duration_months),
                host_institution_required = COALESCE(?, host_institution_required),
                grant_type_bucket = COALESCE(?, grant_type_bucket),
                grant_type_source = COALESCE(?, grant_type_source),
                relevance_score = COALESCE(?, relevance_score),
                health_research_match = COALESCE(?, health_research_match),
                relevance_rationale = COALESCE(?, relevance_rationale),
                last_seen_at = ?,
                updated_at = ?
            WHERE opportunity_id = ?""",
            (
                opp.url_source,
                opp.title,
                opp.funder_name,
                opp.scheme_name,
                opp.country_or_region,
                opp.language,
                opp.deadline_date,
                opp.deadline_type,
                opp.open_date,
                opp.status,
                opp.summary_en,
                opp.topics,
                opp.eligibility,
                opp.career_stage,
                opp.amount_min,
                opp.amount_max,
                opp.amount_currency,
                opp.amount_usd_min,
                opp.amount_usd_max,
                opp.amount_confidence,
                opp.duration_months,
                int(opp.host_institution_required) if opp.host_institution_required is not None else None,
                opp.grant_type_bucket,
                opp.grant_type_source,
                opp.relevance_score,
                int(opp.health_research_match),
                opp.relevance_rationale,
                now,
                now,
                opp.opportunity_id,
            ),
        )
        conn.commit()
        return False
    else:
        conn.execute(
            """INSERT INTO opportunities (
                opportunity_id, url_canonical, url_source, source_id,
                title, funder_name, scheme_name, country_or_region,
                language, deadline_date, deadline_type, open_date,
                status, summary_en, topics, eligibility, career_stage,
                amount_min, amount_max, amount_currency,
                amount_usd_min, amount_usd_max, amount_confidence,
                duration_months, host_institution_required,
                grant_type_bucket, grant_type_source,
                relevance_score, health_research_match, relevance_rationale,
                first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )""",
            (
                opp.opportunity_id,
                opp.url_canonical,
                opp.url_source,
                opp.source_id,
                opp.title,
                opp.funder_name,
                opp.scheme_name,
                opp.country_or_region,
                opp.language,
                opp.deadline_date,
                opp.deadline_type,
                opp.open_date,
                opp.status,
                opp.summary_en,
                opp.topics,
                opp.eligibility,
                opp.career_stage,
                opp.amount_min,
                opp.amount_max,
                opp.amount_currency,
                opp.amount_usd_min,
                opp.amount_usd_max,
                opp.amount_confidence,
                opp.duration_months,
                int(opp.host_institution_required) if opp.host_institution_required is not None else None,
                opp.grant_type_bucket,
                opp.grant_type_source,
                opp.relevance_score,
                int(opp.health_research_match),
                opp.relevance_rationale,
                now,
                now,
                now,
                now,
            ),
        )
        conn.commit()
        return True


def get_opportunity(conn: sqlite3.Connection, opportunity_id: str) -> Optional[Opportunity]:
    """Fetch a single opportunity by ID."""
    row = conn.execute(
        "SELECT * FROM opportunities WHERE opportunity_id = ?", (opportunity_id,)
    ).fetchone()
    if row:
        return Opportunity(**dict(row))
    return None


def get_all_opportunity_ids(conn: sqlite3.Connection) -> set[str]:
    """Return the set of all opportunity IDs in the database."""
    rows = conn.execute("SELECT opportunity_id FROM opportunities").fetchall()
    return {row["opportunity_id"] for row in rows}


def get_opportunities_needing_enrichment(
    conn: sqlite3.Connection, task_type: str, limit: int = 200
) -> list[Opportunity]:
    """Return opportunities that have not been enriched for the given task type."""
    rows = conn.execute(
        """SELECT o.* FROM opportunities o
        WHERE o.opportunity_id NOT IN (
            SELECT e.opportunity_id FROM enrichments e WHERE e.task_type = ?
        )
        ORDER BY o.first_seen_at DESC
        LIMIT ?""",
        (task_type, limit),
    ).fetchall()
    return [Opportunity(**dict(row)) for row in rows]


def get_opportunities_for_digest(
    conn: sqlite3.Connection,
    min_relevance: float = 0.65,
    limit: int = 50,
) -> list[Opportunity]:
    """Return opportunities not yet emailed, ordered by relevance score descending."""
    rows = conn.execute(
        """SELECT * FROM opportunities
        WHERE emailed_at IS NULL
          AND status IN ('open', 'unverified')
          AND relevance_score IS NOT NULL
          AND relevance_score >= ?
        ORDER BY relevance_score DESC
        LIMIT ?""",
        (min_relevance, limit),
    ).fetchall()
    return [Opportunity(**dict(row)) for row in rows]


def mark_opportunities_emailed(conn: sqlite3.Connection, opportunity_ids: list[str]) -> None:
    """Mark opportunities as having been included in an email digest."""
    now = datetime.utcnow().isoformat()
    for oid in opportunity_ids:
        conn.execute(
            "UPDATE opportunities SET emailed_at = ? WHERE opportunity_id = ?",
            (now, oid),
        )
    conn.commit()


def update_opportunity_fields(
    conn: sqlite3.Connection,
    opportunity_id: str,
    **fields,
) -> None:
    """Update specific fields on an opportunity after enrichment or verification."""
    if not fields:
        return
    set_clauses = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [opportunity_id]
    conn.execute(
        f"UPDATE opportunities SET {set_clauses}, updated_at = datetime('now') WHERE opportunity_id = ?",
        values,
    )
    conn.commit()


# -- Snapshots --

def insert_snapshot(conn: sqlite3.Connection, snapshot: OpportunitySnapshot) -> int:
    """Insert a content snapshot. Returns the snapshot_id."""
    cursor = conn.execute(
        """INSERT INTO opportunity_snapshots
        (opportunity_id, http_status, content_type, content_text, content_html,
         content_hash, extractor_version, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot.opportunity_id,
            snapshot.http_status,
            snapshot.content_type,
            snapshot.content_text,
            snapshot.content_html,
            snapshot.content_hash,
            snapshot.extractor_version,
            snapshot.notes,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_latest_snapshot_hash(conn: sqlite3.Connection, opportunity_id: str) -> Optional[str]:
    """Return the content hash of the most recent snapshot for an opportunity."""
    row = conn.execute(
        """SELECT content_hash FROM opportunity_snapshots
        WHERE opportunity_id = ?
        ORDER BY captured_at DESC LIMIT 1""",
        (opportunity_id,),
    ).fetchone()
    return row["content_hash"] if row else None


# -- Enrichments --

def get_cached_enrichment(
    conn: sqlite3.Connection, input_hash: str, task_type: str
) -> Optional[Enrichment]:
    """Look up a cached enrichment by input hash and task type."""
    row = conn.execute(
        """SELECT * FROM enrichments
        WHERE input_hash = ? AND task_type = ?
        ORDER BY created_at DESC LIMIT 1""",
        (input_hash, task_type),
    ).fetchone()
    if row:
        return Enrichment(**dict(row))
    return None


def insert_enrichment(conn: sqlite3.Connection, enrichment: Enrichment) -> int:
    """Insert an enrichment result. Returns the enrichment_id."""
    cursor = conn.execute(
        """INSERT OR REPLACE INTO enrichments
        (opportunity_id, task_type, prompt_version, model_id, input_hash, output_json, tokens_used)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            enrichment.opportunity_id,
            enrichment.task_type,
            enrichment.prompt_version,
            enrichment.model_id,
            enrichment.input_hash,
            enrichment.output_json,
            enrichment.tokens_used,
        ),
    )
    conn.commit()
    return cursor.lastrowid


# -- FX Rates --

def upsert_fx_rate(conn: sqlite3.Connection, rate: FxRate) -> None:
    """Insert or update an FX rate."""
    conn.execute(
        """INSERT OR REPLACE INTO fx_rates (rate_date, currency, rate_to_eur, rate_to_usd)
        VALUES (?, ?, ?, ?)""",
        (rate.rate_date, rate.currency, rate.rate_to_eur, rate.rate_to_usd),
    )
    conn.commit()


def get_fx_rate(
    conn: sqlite3.Connection, currency: str, rate_date: Optional[str] = None
) -> Optional[FxRate]:
    """Fetch the FX rate for a currency, optionally for a specific date.

    If no date is provided, returns the most recent rate.
    """
    if rate_date:
        row = conn.execute(
            "SELECT * FROM fx_rates WHERE currency = ? AND rate_date = ?",
            (currency, rate_date),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM fx_rates WHERE currency = ? ORDER BY rate_date DESC LIMIT 1",
            (currency,),
        ).fetchone()
    if row:
        return FxRate(**dict(row))
    return None


# -- Pipeline runs --

def start_pipeline_run(conn: sqlite3.Connection) -> int:
    """Create a new pipeline run record. Returns the run_id."""
    cursor = conn.execute(
        "INSERT INTO pipeline_runs (status) VALUES ('running')"
    )
    conn.commit()
    return cursor.lastrowid


def finish_pipeline_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str = "completed",
    opportunities_found: int = 0,
    opportunities_new: int = 0,
    opportunities_updated: int = 0,
    enrichments_made: int = 0,
    emails_sent: int = 0,
    errors: Optional[list[str]] = None,
    run_metadata: Optional[dict] = None,
) -> None:
    """Update a pipeline run record with final statistics."""
    conn.execute(
        """UPDATE pipeline_runs SET
            finished_at = datetime('now'),
            status = ?,
            opportunities_found = ?,
            opportunities_new = ?,
            opportunities_updated = ?,
            enrichments_made = ?,
            emails_sent = ?,
            errors = ?,
            run_metadata = ?
        WHERE run_id = ?""",
        (
            status,
            opportunities_found,
            opportunities_new,
            opportunities_updated,
            enrichments_made,
            emails_sent,
            json.dumps(errors) if errors else None,
            json.dumps(run_metadata) if run_metadata else None,
            run_id,
        ),
    )
    conn.commit()


def get_latest_pipeline_run(conn: sqlite3.Connection) -> Optional[PipelineRun]:
    """Return the most recent pipeline run record."""
    row = conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row:
        return PipelineRun(**dict(row))
    return None


def get_last_email_sent_at(conn: sqlite3.Connection) -> Optional[str]:
    """Return the timestamp of the most recently emailed opportunity."""
    row = conn.execute(
        "SELECT MAX(emailed_at) as last_emailed FROM opportunities WHERE emailed_at IS NOT NULL"
    ).fetchone()
    return row["last_emailed"] if row and row["last_emailed"] else None
