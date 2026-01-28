"""Read-only SQLite queries for the Pituffik dashboard.

All database access for the Shiny dashboard goes through this module.
The dashboard only reads data -- writes are done by the pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "grants.sqlite"


def get_connection() -> sqlite3.Connection:
    """Open a read-only connection to the grants database."""
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_opportunities(conn: sqlite3.Connection) -> list[dict]:
    """Fetch all open opportunities, ordered by deadline (soonest first).

    Returns:
        A list of opportunity dicts.
    """
    rows = conn.execute(
        """SELECT * FROM opportunities
        WHERE status IN ('open', 'unverified')
        ORDER BY
            CASE WHEN deadline_date IS NOT NULL THEN 0 ELSE 1 END,
            deadline_date ASC,
            relevance_score DESC
        """
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_filtered_opportunities(
    conn: sqlite3.Connection,
    funder: Optional[str] = None,
    grant_type: Optional[str] = None,
    region: Optional[str] = None,
    career_stage: Optional[str] = None,
    status: Optional[str] = None,
    search_text: Optional[str] = None,
    min_relevance: Optional[float] = None,
    min_amount_gbp: Optional[float] = None,
) -> list[dict]:
    """Fetch opportunities with optional filters.

    Args:
        conn: Database connection.
        funder: Funder name filter.
        grant_type: Grant type bucket filter (e.g. "fellowship", "project").
        region: Country or region filter.
        career_stage: Career stage filter.
        status: Status filter ("open", "closed", "unverified").
        search_text: Free-text search across title, funder, scheme, eligibility.
        min_relevance: Minimum relevance score (0-1).
        min_amount_gbp: Minimum GBP amount (uses amount_gbp_max).

    Returns:
        A list of opportunity dicts matching the filters.
    """
    conditions = []
    params = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    else:
        conditions.append("status IN ('open', 'unverified')")

    if funder:
        conditions.append("funder_name = ?")
        params.append(funder)

    if grant_type:
        conditions.append("grant_type_bucket = ?")
        params.append(grant_type)

    if region:
        conditions.append("country_or_region = ?")
        params.append(region)

    if career_stage:
        conditions.append("career_stage = ?")
        params.append(career_stage)

    if search_text:
        conditions.append(
            "(title LIKE ? OR funder_name LIKE ? OR scheme_name LIKE ?"
            " OR eligibility LIKE ? OR summary_en LIKE ?)"
        )
        like_term = f"%{search_text}%"
        params.extend([like_term, like_term, like_term, like_term, like_term])

    if min_relevance is not None:
        conditions.append("relevance_score >= ?")
        params.append(min_relevance)

    if min_amount_gbp is not None:
        conditions.append(
            "(amount_gbp_max >= ? OR amount_gbp_min >= ?)"
        )
        params.extend([min_amount_gbp, min_amount_gbp])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    rows = conn.execute(
        f"""SELECT * FROM opportunities
        WHERE {where_clause}
        ORDER BY
            CASE WHEN deadline_date IS NOT NULL THEN 0 ELSE 1 END,
            deadline_date ASC,
            relevance_score DESC""",
        params,
    ).fetchall()

    return [_row_to_dict(row) for row in rows]


def get_opportunity_detail(
    conn: sqlite3.Connection, opp_id: str
) -> Optional[dict]:
    """Fetch a single opportunity with full details."""
    row = conn.execute(
        "SELECT * FROM opportunities WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    if row:
        return _row_to_dict(row)
    return None


def get_diagnostics(conn: sqlite3.Connection) -> dict:
    """Fetch dashboard diagnostics data.

    Returns:
        A dict with pipeline statistics and summary counts.
    """
    # Total opportunities
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM opportunities"
    ).fetchone()["n"]
    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM opportunities WHERE status = 'open'"
    ).fetchone()["n"]
    closed_count = conn.execute(
        "SELECT COUNT(*) AS n FROM opportunities WHERE status = 'closed'"
    ).fetchone()["n"]
    unverified_count = conn.execute(
        "SELECT COUNT(*) AS n FROM opportunities WHERE status = 'unverified'"
    ).fetchone()["n"]

    # By source
    source_counts = conn.execute(
        """SELECT source_id, COUNT(*) AS n FROM opportunities
        GROUP BY source_id ORDER BY n DESC"""
    ).fetchall()

    # By grant type
    grant_type_counts = conn.execute(
        """SELECT grant_type_bucket, COUNT(*) AS n FROM opportunities
        WHERE grant_type_bucket IS NOT NULL
        GROUP BY grant_type_bucket ORDER BY n DESC"""
    ).fetchall()

    # By funder
    funder_counts = conn.execute(
        """SELECT funder_name, COUNT(*) AS n FROM opportunities
        WHERE funder_name IS NOT NULL
        GROUP BY funder_name ORDER BY n DESC"""
    ).fetchall()

    # By country/region
    country_counts = conn.execute(
        """SELECT country_or_region, COUNT(*) AS n FROM opportunities
        WHERE country_or_region IS NOT NULL
        GROUP BY country_or_region ORDER BY n DESC"""
    ).fetchall()

    # Latest pipeline run
    latest_run = conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    # Enrichment stats
    enrichment_count = conn.execute(
        "SELECT COUNT(*) AS n FROM enrichments"
    ).fetchone()["n"]

    return {
        "total_opportunities": total,
        "open_opportunities": open_count,
        "closed_opportunities": closed_count,
        "unverified_opportunities": unverified_count,
        "sources": [dict(row) for row in source_counts],
        "grant_types": [dict(row) for row in grant_type_counts],
        "funders": [dict(row) for row in funder_counts],
        "countries": [dict(row) for row in country_counts],
        "latest_run": dict(latest_run) if latest_run else None,
        "enrichment_count": enrichment_count,
    }


def get_distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    """Get distinct non-null values for a column (for filter dropdowns).

    Only allows a predefined set of column names to prevent SQL injection.
    """
    allowed_columns = {
        "funder_name",
        "grant_type_bucket",
        "country_or_region",
        "career_stage",
        "language",
        "source_id",
        "status",
    }
    if column not in allowed_columns:
        return []
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM opportunities "
        f"WHERE {column} IS NOT NULL ORDER BY {column}"
    ).fetchall()
    return [row[0] for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a dict, parsing JSON fields."""
    d = dict(row)
    # Parse topics from JSON string to list
    if d.get("topics"):
        try:
            d["topics"] = json.loads(d["topics"])
        except (json.JSONDecodeError, TypeError):
            d["topics"] = []
    else:
        d["topics"] = []
    return d
