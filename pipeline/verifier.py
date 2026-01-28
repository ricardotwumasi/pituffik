"""Grant opportunity verification module.

Fetches authoritative pages for grant opportunities to:
- Confirm the opportunity is still open
- Extract or update deadline dates (fixed, rolling, and open-ended)
- Detect closed/withdrawn indicators
- Store content snapshots for change detection
- Return a dict of field updates for the database
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from pipeline import db
from pipeline.models import Opportunity, OpportunitySnapshot

logger = logging.getLogger(__name__)

# Version string for snapshot tracking
_EXTRACTOR_VERSION = "v1"


# -- Deadline extraction patterns --

# Keywords that signal a deadline date in nearby text
_DEADLINE_KEYWORDS = [
    "application deadline",
    "closing date for applications",
    "submission deadline",
    "applications open until",
    "closing date",
    "close date",
    "apply by",
    "applications close",
    "deadline for applications",
    "last date to apply",
    "submit by",
    "final date",
    "due date",
    "response date",
    "ansoegningsfrist",      # Danish: application deadline
    "ansokningsfrist",       # Swedish: application deadline
    "soknadsfrist",          # Norwegian: application deadline
    "ansogningsfrist",       # Danish variant
    "sista ansokningsdag",   # Swedish: last application day
]

# Rolling/open-ended deadline indicators
_ROLLING_INDICATORS = [
    "open until further notice",
    "rolling",
    "no deadline",
    "no fixed deadline",
    "continuously open",
    "ongoing",
    "accepted on a rolling basis",
    "applications accepted at any time",
    "open call",
    "always open",
    "permanent call",
    "open-ended",
    "fortloebende",          # Danish: rolling/continuous
    "lopande",               # Swedish: rolling/continuous
    "lopende",               # Norwegian: rolling/continuous
]

# Closed/withdrawn indicators
_CLOSED_INDICATORS = [
    "this call is now closed",
    "this call has closed",
    "applications are no longer accepted",
    "applications are no longer being accepted",
    "this funding opportunity has been withdrawn",
    "this opportunity has been withdrawn",
    "this opportunity is now closed",
    "this opportunity has closed",
    "no longer accepting applications",
    "call closed",
    "opportunity closed",
    "funding closed",
    "expired",
    "this call has been withdrawn",
    "this scheme is now closed",
    "this programme is now closed",
    "this program is now closed",
    "submission is closed",
    "submissions are closed",
    "ansogningsfristen er udloebet",   # Danish: deadline has expired
    "ansokningsperioden har avslutats",  # Swedish: application period ended
    "soknadsfristen er utlopt",        # Norwegian: deadline has expired
]

# Month name lookup
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def verify_opportunity(
    conn: sqlite3.Connection,
    http_client: httpx.Client,
    opportunity: Opportunity,
) -> dict:
    """Fetch the authoritative page for an opportunity and extract updates.

    Performs a GET request to the opportunity URL, extracts page content,
    stores a snapshot if the content has changed, and checks for deadline
    and status information.

    Args:
        conn: Database connection for storing snapshots.
        http_client: HTTP client for fetching pages.
        opportunity: The opportunity record to verify.

    Returns:
        A dict of field updates. Possible keys:
        - deadline_date (str): ISO 8601 date if a fixed deadline was found.
        - deadline_type (str): "fixed", "rolling", or "none".
        - status (str): "open" or "closed".
        - last_verified_at (str): ISO 8601 timestamp of this verification.
    """
    updates: dict = {}
    now = datetime.utcnow().isoformat()

    url = opportunity.url_canonical or opportunity.url_source

    try:
        response = http_client.get(url)
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return updates

    # Handle HTTP error status codes
    if response.status_code == 404:
        updates["status"] = "closed"
        updates["last_verified_at"] = now
        logger.info(
            "Opportunity %s returned 404 -- marking closed",
            opportunity.opportunity_id,
        )
        return updates
    elif response.status_code == 410:
        # 410 Gone is a strong signal the resource has been permanently removed
        updates["status"] = "closed"
        updates["last_verified_at"] = now
        logger.info(
            "Opportunity %s returned 410 Gone -- marking closed",
            opportunity.opportunity_id,
        )
        return updates
    elif response.status_code >= 400:
        logger.warning(
            "Opportunity %s returned HTTP %d -- skipping verification",
            opportunity.opportunity_id, response.status_code,
        )
        return updates

    html = response.text
    text = _extract_text(html)

    # Store a content snapshot if the content has changed
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    latest_hash = db.get_latest_snapshot_hash(conn, opportunity.opportunity_id)

    if content_hash != latest_hash:
        snapshot = OpportunitySnapshot(
            opportunity_id=opportunity.opportunity_id,
            http_status=response.status_code,
            content_type=response.headers.get("content-type", ""),
            content_text=text,
            content_html=html,
            content_hash=content_hash,
            extractor_version=_EXTRACTOR_VERSION,
            notes=None,
        )
        db.insert_snapshot(conn, snapshot)
        logger.debug(
            "New snapshot for %s (hash changed)", opportunity.opportunity_id
        )

    # Check for closed/withdrawn indicators first
    if _page_indicates_closed(text):
        updates["status"] = "closed"
        updates["last_verified_at"] = now
        logger.info(
            "Opportunity %s: page indicates closed/withdrawn",
            opportunity.opportunity_id,
        )
        return updates

    # Check for rolling/open-ended deadline indicators
    if _page_indicates_rolling(text):
        updates["deadline_type"] = "rolling"
        updates["status"] = "open"
        updates["last_verified_at"] = now
        logger.debug(
            "Opportunity %s: rolling deadline detected",
            opportunity.opportunity_id,
        )
        return updates

    # Try to extract a fixed deadline date
    deadline_date = _extract_deadline(text)
    if deadline_date:
        updates["deadline_date"] = deadline_date
        updates["deadline_type"] = "fixed"

        # Check whether the deadline has passed
        try:
            deadline_dt = datetime.fromisoformat(deadline_date)
            if deadline_dt < datetime.utcnow():
                updates["status"] = "closed"
                logger.info(
                    "Opportunity %s: deadline %s has passed -- marking closed",
                    opportunity.opportunity_id, deadline_date,
                )
            else:
                updates["status"] = "open"
        except ValueError:
            pass
    else:
        # No deadline found, but page is live -- mark as verified
        updates["status"] = "open"

    updates["last_verified_at"] = now
    return updates


def verify_batch(
    conn: sqlite3.Connection,
    http_client: httpx.Client,
    opportunities: list[Opportunity],
) -> dict[str, dict]:
    """Verify a batch of opportunities.

    Args:
        conn: Database connection.
        http_client: HTTP client.
        opportunities: List of opportunities to verify.

    Returns:
        A dict mapping opportunity_id to its update dict.
    """
    results: dict[str, dict] = {}

    for opp in opportunities:
        try:
            updates = verify_opportunity(conn, http_client, opp)
            if updates:
                results[opp.opportunity_id] = updates
                # Apply updates to the database
                db.update_opportunity_fields(
                    conn, opp.opportunity_id, **updates
                )
        except Exception as exc:
            logger.error(
                "Error verifying opportunity %s: %s",
                opp.opportunity_id, exc, exc_info=True,
            )

    logger.info(
        "Verification batch: %d opportunities checked, %d with updates",
        len(opportunities), len(results),
    )
    return results


# -- Internal helpers --

def _extract_text(html: str) -> str:
    """Extract readable text from HTML, removing boilerplate elements.

    Args:
        html: The raw HTML string.

    Returns:
        Cleaned text content.
    """
    soup = BeautifulSoup(html, "lxml")
    # Remove script, style, navigation, and footer elements
    for element in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        element.decompose()
    return soup.get_text(separator=" ", strip=True)


def _extract_deadline(text: str) -> Optional[str]:
    """Try to extract a fixed deadline date from page text.

    Searches for date patterns in the vicinity of deadline-related keywords.
    Checks ISO, UK, US, European, and numeric date formats.

    Args:
        text: The page text content.

    Returns:
        An ISO 8601 date string (YYYY-MM-DD) or None.
    """
    text_lower = text.lower()

    for keyword in _DEADLINE_KEYWORDS:
        idx = text_lower.find(keyword)
        if idx == -1:
            continue

        # Examine text within 250 characters after the keyword
        region = text[idx:idx + 250]

        # Try ISO date: 2025-06-15
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", region)
        if iso_match:
            return iso_match.group(1)

        # Try UK date: 15 June 2025, 15th June 2025
        uk_match = re.search(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{4})",
            region,
            re.IGNORECASE,
        )
        if uk_match:
            date_str = _month_day_year_to_iso(
                uk_match.group(2), int(uk_match.group(1)), int(uk_match.group(3))
            )
            if date_str:
                return date_str

        # Try US date: June 15, 2025
        us_match = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
            region,
            re.IGNORECASE,
        )
        if us_match:
            date_str = _month_day_year_to_iso(
                us_match.group(1), int(us_match.group(2)), int(us_match.group(3))
            )
            if date_str:
                return date_str

        # Try DD/MM/YYYY (European convention)
        slash_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", region)
        if slash_match:
            day = int(slash_match.group(1))
            month = int(slash_match.group(2))
            year = int(slash_match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"

        # Try DD.MM.YYYY (common in Scandinavian/European contexts)
        dot_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", region)
        if dot_match:
            day = int(dot_match.group(1))
            month = int(dot_match.group(2))
            year = int(dot_match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def _page_indicates_closed(text: str) -> bool:
    """Check whether the page text contains indicators that the opportunity is closed.

    Args:
        text: The page text content.

    Returns:
        True if any closed/withdrawn indicator is found.
    """
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in _CLOSED_INDICATORS)


def _page_indicates_rolling(text: str) -> bool:
    """Check whether the page text contains rolling/open-ended deadline indicators.

    Args:
        text: The page text content.

    Returns:
        True if any rolling deadline indicator is found.
    """
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in _ROLLING_INDICATORS)


def _month_day_year_to_iso(
    month_name: str,
    day: int,
    year: int,
) -> Optional[str]:
    """Convert a month name, day, and year to an ISO 8601 date string.

    Args:
        month_name: Full English month name (e.g. "January").
        day: Day of the month.
        year: Four-digit year.

    Returns:
        An ISO 8601 date string (YYYY-MM-DD), or None if invalid.
    """
    month = _MONTH_NAMES.get(month_name.lower())
    if month is None:
        return None
    try:
        # Validate the date
        datetime(year, month, day)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None
