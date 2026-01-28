"""Pituffik pipeline orchestrator.

Runs the full pipeline: collect > dedup > verify > enrich > fx > notify.
Can be invoked as: python -m pipeline.main
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from pipeline import db
from pipeline.collector import collect_all
from pipeline.enricher import enrich_opportunity, _get_client as get_gemini_client
from pipeline.fx import update_fx_rates, convert_opportunity_amounts
from pipeline.http_client import create_client
from pipeline.models import Opportunity, OpportunitySnapshot
from pipeline.normaliser import (
    canonicalise_url,
    classify_grant_type,
    deduplicate_opportunities,
    generate_opportunity_id,
    is_target_grant_type,
)
from pipeline.notifier import send_digest
from pipeline.rate_limiter import RateLimiter
from pipeline.verifier import verify_opportunity

logger = logging.getLogger(__name__)

# Load settings
_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yml"


def _load_settings() -> dict:
    """Load global settings from YAML."""
    import yaml
    with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_pipeline(dry_run: bool = False) -> dict:
    """Execute the full Pituffik pipeline.

    Steps:
    1. Collect raw opportunities from all enabled sources
    2. Deduplicate against existing database and within batch
    3. Insert/update opportunities in the database
    4. Verify opportunities (fetch authoritative pages, check status)
    5. Enrich opportunities via Gemini (relevance, extraction, synopsis)
    6. Update FX rates and convert amounts to USD
    7. Send weekly email digest of new relevant opportunities

    Args:
        dry_run: If True, skip email sending.

    Returns:
        A summary dict with counts and any errors.
    """
    settings = _load_settings()
    pipeline_cfg = settings.get("pipeline", {})
    gemini_call_cap = pipeline_cfg.get("gemini_call_cap", 200)
    relevance_threshold = pipeline_cfg.get("relevance_threshold", 0.65)

    # Initialise database
    conn = db.get_connection()
    db.initialise_schema(conn)

    # Start pipeline run audit log
    run_id = db.start_pipeline_run(conn)
    errors: list[str] = []
    stats = {
        "opportunities_found": 0,
        "opportunities_new": 0,
        "opportunities_updated": 0,
        "enrichments_made": 0,
        "emails_sent": 0,
    }

    try:
        # -- Step 1: Collect --
        logger.info("=== Step 1: Collecting from sources ===")
        http_client = create_client()
        rate_limiter = RateLimiter()

        raw_opportunities = collect_all(http_client, rate_limiter)
        stats["opportunities_found"] = len(raw_opportunities)
        logger.info("Collected %d raw opportunities", len(raw_opportunities))

        # -- Step 2: Deduplicate --
        logger.info("=== Step 2: Deduplicating ===")
        existing_ids = db.get_all_opportunity_ids(conn)
        unique_opportunities = deduplicate_opportunities(
            raw_opportunities,
            existing_ids,
            fuzzy_threshold=settings.get("deduplication", {}).get("fuzzy_threshold", 85),
        )
        logger.info("After dedup: %d unique opportunities", len(unique_opportunities))

        # -- Step 3: Insert/Update opportunities --
        logger.info("=== Step 3: Storing opportunities ===")
        for raw in unique_opportunities:
            canonical = canonicalise_url(raw.url)
            opportunity_id = generate_opportunity_id(canonical)

            # Classify grant type from title
            grant_type_bucket = "other"
            grant_type_source = "regex"
            if raw.title:
                grant_type_bucket, grant_type_source = classify_grant_type(raw.title)

            opp = Opportunity(
                opportunity_id=opportunity_id,
                url_canonical=canonical,
                url_source=raw.url,
                source_id=raw.source_id,
                title=raw.title,
                funder_name=raw.funder_name,
                scheme_name=raw.scheme_name,
                language=raw.language or "en",
                deadline_date=raw.deadline_date,
                deadline_type=raw.deadline_type,
                grant_type_bucket=grant_type_bucket,
                grant_type_source=grant_type_source,
            )

            is_new = db.upsert_opportunity(conn, opp)
            if is_new:
                stats["opportunities_new"] += 1

                # Store initial snapshot if we have content
                if raw.content_text or raw.content_html:
                    import hashlib
                    content = raw.content_text or ""
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    snapshot = OpportunitySnapshot(
                        opportunity_id=opportunity_id,
                        content_text=raw.content_text,
                        content_html=raw.content_html,
                        content_hash=content_hash,
                    )
                    db.insert_snapshot(conn, snapshot)
            else:
                stats["opportunities_updated"] += 1

        logger.info(
            "Stored: %d new, %d updated",
            stats["opportunities_new"], stats["opportunities_updated"],
        )

        # -- Step 4: Verify opportunities --
        logger.info("=== Step 4: Verifying opportunities ===")
        opps_to_verify = db.get_opportunities_needing_enrichment(conn, "relevance", limit=gemini_call_cap)
        for opp in opps_to_verify:
            try:
                rate_limiter.wait(opp.source_id, min_interval=1.0)
                updates = verify_opportunity(conn, http_client, opp)
                if updates:
                    db.update_opportunity_fields(conn, opp.opportunity_id, **updates)
            except Exception as exc:
                msg = f"Verification failed for {opp.opportunity_id}: {exc}"
                logger.error(msg)
                errors.append(msg)

        # -- Step 5: Enrich via Gemini --
        logger.info("=== Step 5: Enriching via Gemini ===")
        gemini_calls = 0

        # Check if Gemini API key is available
        if os.environ.get("GEMINI_API_KEY"):
            gemini_client = get_gemini_client()
            opps_to_enrich = db.get_opportunities_needing_enrichment(
                conn, "relevance", limit=gemini_call_cap
            )

            for opp in opps_to_enrich:
                if gemini_calls >= gemini_call_cap:
                    logger.warning("Gemini call cap reached (%d)", gemini_call_cap)
                    break

                # Get grant text from latest snapshot
                row = conn.execute(
                    """SELECT content_text FROM opportunity_snapshots
                    WHERE opportunity_id = ?
                    ORDER BY captured_at DESC LIMIT 1""",
                    (opp.opportunity_id,),
                ).fetchone()
                grant_text = row["content_text"] if row else opp.title or ""

                if not grant_text:
                    continue

                try:
                    updates = enrich_opportunity(conn, gemini_client, opp, grant_text)
                    if updates:
                        db.update_opportunity_fields(conn, opp.opportunity_id, **updates)
                        gemini_calls += 1
                        stats["enrichments_made"] += 1
                except Exception as exc:
                    msg = f"Enrichment failed for {opp.opportunity_id}: {exc}"
                    logger.error(msg)
                    errors.append(msg)
        else:
            logger.warning("GEMINI_API_KEY not set -- skipping enrichment")

        # -- Step 6: Update FX rates and convert amounts --
        logger.info("=== Step 6: Updating FX rates ===")
        try:
            fx_rates = update_fx_rates(conn, http_client)
            if fx_rates:
                # Convert amounts for all opportunities with amounts but no USD conversion
                rows = conn.execute(
                    """SELECT opportunity_id FROM opportunities
                    WHERE amount_min IS NOT NULL
                      AND amount_currency IS NOT NULL
                      AND amount_usd_min IS NULL"""
                ).fetchall()
                for row in rows:
                    try:
                        fx_updates = convert_opportunity_amounts(
                            conn, row["opportunity_id"], fx_rates
                        )
                        if fx_updates:
                            db.update_opportunity_fields(
                                conn, row["opportunity_id"], **fx_updates
                            )
                    except Exception as exc:
                        msg = f"FX conversion failed for {row['opportunity_id']}: {exc}"
                        logger.error(msg)
                        errors.append(msg)
        except Exception as exc:
            msg = f"FX rate update failed: {exc}"
            logger.error(msg)
            errors.append(msg)

        # -- Step 7: Notify --
        logger.info("=== Step 7: Sending notifications ===")
        if os.environ.get("RESEND_API_KEY"):
            try:
                emails_sent = send_digest(
                    conn,
                    min_relevance=relevance_threshold,
                    dry_run=dry_run,
                )
                stats["emails_sent"] = emails_sent
            except Exception as exc:
                msg = f"Notification failed: {exc}"
                logger.error(msg)
                errors.append(msg)
        else:
            logger.warning("RESEND_API_KEY not set -- skipping notifications")

        # Finalise pipeline run
        status = "completed"
        db.finish_pipeline_run(
            conn, run_id,
            status=status,
            errors=errors if errors else None,
            **stats,
        )

        logger.info("=== Pipeline complete ===")
        logger.info("Stats: %s", json.dumps(stats, indent=2))
        if errors:
            logger.warning("Errors encountered: %d", len(errors))

    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        errors.append(str(exc))
        db.finish_pipeline_run(
            conn, run_id,
            status="failed",
            errors=errors,
            **stats,
        )
        raise
    finally:
        # Force WAL checkpoint so all data is in the main database file
        # (git only commits data/grants.sqlite, not the -wal/-shm journals)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        http_client.close()
        conn.close()

    return stats


def main() -> None:
    """Entry point for the pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Support --dry-run flag
    dry_run = "--dry-run" in sys.argv

    try:
        stats = run_pipeline(dry_run=dry_run)
        sys.exit(0)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
