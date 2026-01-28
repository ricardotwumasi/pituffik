"""NIH Grants RSS feed adapter.

Parses the NIH Guide for Grants and Contracts RSS feed to discover
health research funding opportunities from the US National Institutes of Health.
"""

from __future__ import annotations

import logging
from typing import Optional

import feedparser
import httpx

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_FEED_URL = "https://grants.nih.gov/grants/guide/rss/frontpage_rss.xml"


class NihRssAdapter(SourceAdapter):
    """Adapter for the NIH Grants RSS feed.

    Fetches the NIH Guide front-page RSS feed, parses entries with feedparser,
    and filters by health research keywords from the keywords configuration.
    """

    source_id: str = "nih_rss"
    source_name: str = "NIH Grants RSS"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect grant opportunities from the NIH RSS feed.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances matching the keyword filters.
        """
        logger.info("Fetching NIH RSS feed from %s", _FEED_URL)

        try:
            response = http_client.get(_FEED_URL)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP error fetching NIH RSS feed: %d %s",
                exc.response.status_code, exc.response.reason_phrase,
            )
            return []
        except httpx.RequestError as exc:
            logger.error("Request error fetching NIH RSS feed: %s", exc)
            return []

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            logger.warning(
                "NIH RSS feed parse error (no entries): %s",
                feed.bozo_exception,
            )
            return []

        search_terms = self._build_search_terms(keywords)
        opportunities: list[RawOpportunity] = []

        for entry in feed.entries:
            title = getattr(entry, "title", None) or ""
            link = getattr(entry, "link", None) or ""
            description = getattr(entry, "description", None) or ""
            summary = getattr(entry, "summary", None) or description

            if not link:
                logger.debug("Skipping NIH entry with no link: %s", title)
                continue

            # Filter by keywords -- check title and description
            if not _matches_keywords(title, summary, search_terms):
                continue

            # Extract deadline from the feed entry if present
            deadline_date = _extract_deadline_from_entry(entry)

            opp = RawOpportunity(
                url=link,
                title=title.strip() if title else None,
                funder_name="NIH",
                scheme_name=None,
                source_id=self.source_id,
                content_text=summary.strip() if summary else None,
                content_html=None,
                deadline_date=deadline_date,
                deadline_type="fixed" if deadline_date else "unknown",
                amount_raw=None,
                language="en",
            )
            opportunities.append(opp)

        logger.info(
            "NIH RSS: parsed %d entries, %d matched keyword filters",
            len(feed.entries), len(opportunities),
        )
        return opportunities


def _matches_keywords(
    title: str,
    description: str,
    search_terms: list[str],
) -> bool:
    """Check whether an entry's title or description contains any keyword.

    The match is case-insensitive. If search_terms is empty, all entries pass.

    Args:
        title: The entry title.
        description: The entry description or summary text.
        search_terms: List of keyword strings to match against.

    Returns:
        True if any keyword is found in the title or description.
    """
    if not search_terms:
        return True

    combined = f"{title} {description}".lower()
    return any(term.lower() in combined for term in search_terms)


def _extract_deadline_from_entry(entry) -> Optional[str]:
    """Attempt to extract a deadline date from a feedparser entry.

    Checks common date fields that feedparser may populate.

    Args:
        entry: A feedparser entry object.

    Returns:
        An ISO 8601 date string (YYYY-MM-DD) or None.
    """
    # feedparser normalises dates into *_parsed tuples
    for date_field in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, date_field, None)
        if parsed:
            try:
                # parsed is a time.struct_time; extract year-month-day
                return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}"
            except (AttributeError, TypeError):
                continue

    return None
