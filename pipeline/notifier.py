"""Email notification module using Resend.

Sends weekly digest emails containing new grant opportunities that meet
the relevance threshold. Checks a 7-day interval between digests unless
the force parameter is set.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import resend
from jinja2 import Environment, FileSystemLoader

from pipeline import db
from pipeline.models import Opportunity

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _get_resend_api_key() -> str:
    """Get the Resend API key from environment."""
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise RuntimeError("RESEND_API_KEY environment variable not set")
    return key


def _get_notification_email() -> str:
    """Get the notification recipient email from environment."""
    email = os.environ.get("NOTIFICATION_EMAIL", "ricardo.twumasi@kcl.ac.uk")
    return email


def _should_send_digest(conn: sqlite3.Connection) -> bool:
    """Check whether at least 7 days have passed since the last email.

    Returns True if no email has ever been sent or if the most recent
    emailed_at timestamp is older than 7 days.
    """
    last_sent = db.get_last_email_sent_at(conn)
    if last_sent is None:
        return True

    try:
        last_dt = datetime.fromisoformat(last_sent)
    except (ValueError, TypeError):
        return True

    return datetime.utcnow() - last_dt >= timedelta(days=7)


def _render_digest_html(opportunities: list[Opportunity]) -> str:
    """Render the HTML email digest template.

    Args:
        opportunities: List of grant opportunities to include.

    Returns:
        Rendered HTML string.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("email_digest.html")
    return template.render(opportunities=opportunities)


def send_digest(
    conn: sqlite3.Connection,
    sender: str = "onboarding@resend.dev",
    max_opportunities: int = 50,
    min_relevance: float = 0.3,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """Build and send a weekly email digest of new grant opportunities.

    Args:
        conn: Database connection.
        sender: Sender email address.
        max_opportunities: Maximum opportunities to include.
        min_relevance: Minimum relevance score for inclusion.
        dry_run: If True, log but do not actually send.
        force: If True, bypass the 7-day interval check.

    Returns:
        Number of opportunities included in the digest (0 if nothing to send).
    """
    # Check the weekly interval unless force is set
    if not force and not _should_send_digest(conn):
        logger.info(
            "Fewer than 7 days since last digest -- skipping (use force=True to override)"
        )
        return 0

    # Fetch opportunities not yet emailed, above the relevance threshold
    opportunities = db.get_opportunities_for_digest(
        conn, min_relevance=min_relevance, limit=max_opportunities,
    )

    if not opportunities:
        logger.info(
            "No new opportunities meet the digest criteria -- skipping email"
        )
        return 0

    logger.info("Preparing digest with %d opportunities", len(opportunities))

    # Render email
    html_body = _render_digest_html(opportunities)
    recipient = _get_notification_email()
    subject = (
        f"[Pituffik] {len(opportunities)} new health research grant"
        f" opportunit{'ies' if len(opportunities) != 1 else 'y'}"
    )

    if dry_run:
        logger.info(
            "DRY RUN: Would send digest to %s with %d opportunities",
            recipient,
            len(opportunities),
        )
        return len(opportunities)

    # Send via Resend
    resend.api_key = _get_resend_api_key()

    try:
        result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": subject,
            "html": html_body,
        })
        logger.info(
            "Digest sent to %s (Resend ID: %s)",
            recipient,
            result.get("id", "unknown"),
        )
    except Exception as exc:
        logger.error("Failed to send digest: %s", exc)
        raise

    # Mark opportunities as emailed
    opportunity_ids = [opp.opportunity_id for opp in opportunities]
    db.mark_opportunities_emailed(conn, opportunity_ids)

    return len(opportunities)
