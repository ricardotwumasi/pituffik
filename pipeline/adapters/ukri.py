"""UKRI Funding Finder adapter.

Scrapes the UK Research and Innovation (UKRI) opportunity listing page
for open funding opportunities across all research councils (MRC, ESRC,
EPSRC, BBSRC, AHRC, NERC, STFC, Innovate UK, Research England).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://www.ukri.org/opportunity/"
_BASE_URL = "https://www.ukri.org"

# UKRI council abbreviations for display
_COUNCIL_NAMES = {
    "mrc": "MRC",
    "esrc": "ESRC",
    "epsrc": "EPSRC",
    "bbsrc": "BBSRC",
    "ahrc": "AHRC",
    "nerc": "NERC",
    "stfc": "STFC",
    "innovate uk": "Innovate UK",
    "research england": "Research England",
    "ukri": "UKRI",
}


class UkriAdapter(SourceAdapter):
    """Adapter for the UKRI Funding Finder.

    Fetches the UKRI opportunity listing page, parses the HTML for
    opportunity cards, and filters using keywords from the configuration.
    Each card typically includes a title, link, council badge, and status.
    """

    source_id: str = "ukri"
    source_name: str = "UKRI Funding Finder"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect grant opportunities from the UKRI Funding Finder.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from UKRI.
        """
        logger.info("Fetching UKRI Funding Finder: %s", _LISTING_URL)

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP error fetching UKRI: %d %s",
                exc.response.status_code, exc.response.reason_phrase,
            )
            return []
        except httpx.RequestError as exc:
            logger.error("Request error fetching UKRI: %s", exc)
            return []

        html = response.text
        search_terms = self._build_search_terms(keywords)

        opportunities = self._parse_listing(html, search_terms)

        logger.info(
            "UKRI: parsed page, found %d matching opportunities",
            len(opportunities),
        )
        return opportunities

    def _parse_listing(
        self,
        html: str,
        search_terms: list[str],
    ) -> list[RawOpportunity]:
        """Parse the UKRI listing page HTML for opportunity cards.

        Args:
            html: The raw HTML of the listing page.
            search_terms: Keywords for content filtering.

        Returns:
            A list of RawOpportunity instances.
        """
        soup = BeautifulSoup(html, "lxml")
        opportunities: list[RawOpportunity] = []

        # UKRI uses various card/list structures for opportunities.
        # Attempt multiple selectors for resilience.
        cards = (
            soup.select(".opportunity-item")
            or soup.select("[class*='opportunity']")
            or soup.select(".listing-item")
            or soup.select("article.post")
            or soup.select("article")
            or soup.select(".card")
        )

        if not cards:
            logger.warning(
                "UKRI: no opportunity cards found (page structure may have changed)"
            )
            # Fallback: try to extract from any links containing /opportunity/
            cards = self._fallback_link_extraction(soup)

        for card in cards:
            opp = self._parse_opportunity_card(card, search_terms)
            if opp is not None:
                opportunities.append(opp)

        return opportunities

    def _fallback_link_extraction(self, soup: BeautifulSoup) -> list:
        """Extract opportunity links as a fallback when card selectors fail.

        Args:
            soup: Parsed HTML.

        Returns:
            A list of BeautifulSoup tag wrappers, one per link found.
        """
        links = soup.find_all("a", href=re.compile(r"/opportunity/"))
        # Wrap each link in a minimal container for uniform processing
        from bs4 import Tag
        wrappers = []
        for link in links:
            # Use the link's parent as the card-like container
            parent = link.parent
            if parent and parent not in wrappers:
                wrappers.append(parent)
        return wrappers

    def _parse_opportunity_card(
        self,
        card,
        search_terms: list[str],
    ) -> Optional[RawOpportunity]:
        """Extract opportunity data from a single card element.

        Args:
            card: A BeautifulSoup element representing an opportunity card.
            search_terms: Keywords for content filtering.

        Returns:
            A RawOpportunity if the card matches filters, or None.
        """
        # Extract title and link
        title_el = (
            card.select_one("h3 a")
            or card.select_one("h2 a")
            or card.select_one("a[class*='title']")
            or card.select_one("a[href*='/opportunity/']")
            or card.select_one("a")
        )

        if title_el is None:
            return None

        title = title_el.get_text(strip=True)
        link = title_el.get("href", "")

        if not link:
            return None

        # Make link absolute if relative
        if link.startswith("/"):
            link = f"{_BASE_URL}{link}"

        # Extract card text for keyword filtering
        card_text = card.get_text(separator=" ", strip=True)

        # Filter by keywords
        if search_terms and not _text_matches_keywords(card_text, search_terms):
            return None

        # Extract council badge
        funder_name = self._extract_council(card, card_text)

        # Extract status (open, closed, upcoming)
        status_text = self._extract_status(card, card_text)

        # Skip closed opportunities at the adapter level
        if status_text and "closed" in status_text.lower():
            logger.debug("UKRI: skipping closed opportunity: %s", title)
            return None

        # Extract deadline
        deadline_date = _extract_deadline(card_text)

        return RawOpportunity(
            url=link,
            title=title.strip() if title else None,
            funder_name=funder_name or "UKRI",
            scheme_name=None,
            source_id=self.source_id,
            content_text=card_text.strip() if card_text else None,
            content_html=str(card),
            deadline_date=deadline_date,
            deadline_type="fixed" if deadline_date else "unknown",
            amount_raw=None,
            language="en",
        )

    def _extract_council(self, card, card_text: str) -> Optional[str]:
        """Extract the research council name from a card.

        Args:
            card: The BeautifulSoup card element.
            card_text: The card's text content.

        Returns:
            The council name, or None.
        """
        # Look for a badge/tag element
        badge = (
            card.select_one("[class*='badge']")
            or card.select_one("[class*='tag']")
            or card.select_one("[class*='council']")
            or card.select_one("[class*='funder']")
        )

        if badge:
            badge_text = badge.get_text(strip=True).lower()
            for key, name in _COUNCIL_NAMES.items():
                if key in badge_text:
                    return name

        # Fallback: check the card text for council names
        card_lower = card_text.lower()
        for key, name in _COUNCIL_NAMES.items():
            if key in card_lower:
                return name

        return None

    def _extract_status(self, card, card_text: str) -> Optional[str]:
        """Extract the opportunity status (open/closed/upcoming) from a card.

        Args:
            card: The BeautifulSoup card element.
            card_text: The card's text content.

        Returns:
            The status string, or None.
        """
        status_el = (
            card.select_one("[class*='status']")
            or card.select_one("[class*='state']")
        )
        if status_el:
            return status_el.get_text(strip=True)

        # Fallback pattern matching
        for label in ("closed", "open", "upcoming", "closing soon"):
            if label in card_text.lower():
                return label

        return None


def _text_matches_keywords(text: str, search_terms: list[str]) -> bool:
    """Check whether text contains any of the search terms (case-insensitive).

    Args:
        text: The text to search within.
        search_terms: List of keyword strings.

    Returns:
        True if any keyword is found, or if search_terms is empty.
    """
    if not search_terms:
        return True

    text_lower = text.lower()
    return any(term.lower() in text_lower for term in search_terms)


def _extract_deadline(text: str) -> Optional[str]:
    """Extract a deadline date from card text.

    Looks for date patterns near deadline-related words.

    Args:
        text: The card text content.

    Returns:
        An ISO 8601 date string (YYYY-MM-DD) or None.
    """
    text_lower = text.lower()

    deadline_keywords = [
        "closing date", "deadline", "closes", "applications close",
        "apply by", "close date",
    ]

    for kw in deadline_keywords:
        idx = text_lower.find(kw)
        if idx == -1:
            continue

        region = text[idx:idx + 150]

        # ISO date: 2025-06-15
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", region)
        if iso_match:
            return iso_match.group(1)

        # UK date: 15 June 2025 or 15th June 2025
        uk_match = re.search(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|"
            r"August|September|October|November|December)\s+(\d{4})",
            region,
            re.IGNORECASE,
        )
        if uk_match:
            return _to_iso_date(
                int(uk_match.group(3)),
                uk_match.group(2),
                int(uk_match.group(1)),
            )

        # DD/MM/YYYY (UK convention)
        slash_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", region)
        if slash_match:
            day = int(slash_match.group(1))
            month = int(slash_match.group(2))
            year = int(slash_match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"

    return None


_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _to_iso_date(year: int, month_name: str, day: int) -> Optional[str]:
    """Convert a year, month name, and day to an ISO 8601 date string.

    Args:
        year: The four-digit year.
        month_name: The full English month name.
        day: The day of the month.

    Returns:
        An ISO 8601 date string, or None if invalid.
    """
    month = _MONTH_NAMES.get(month_name.lower())
    if month is None:
        return None
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (ValueError, TypeError):
        return None
