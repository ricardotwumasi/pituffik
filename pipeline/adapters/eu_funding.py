"""EU Funding & Tenders Portal adapter.

Scrapes the European Commission Funding & Tenders portal for open calls
for proposals, filtering by health-related programme identifiers
(Horizon Europe, EU4Health).
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

_PORTAL_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
    "screen/opportunities/calls-for-proposals"
)

# Programme identifiers relevant to health research
_TARGET_PROGRAMMES = {
    "horizon europe",
    "horizon-hlth",
    "eu4health",
    "horizon-msca",
    "horizon-erc",
    "horizon-widera",
    "horizon-infra",
    "horizon-cl1",     # Cluster 1: Health
    "cluster 1",
    "hlth",
}

# Base URL for constructing absolute links from relative paths
_BASE_URL = "https://ec.europa.eu"


class EuFundingAdapter(SourceAdapter):
    """Adapter for the EU Funding & Tenders Portal.

    Fetches the calls-for-proposals listing page, parses the HTML for
    individual call entries, and filters by health-related programme
    identifiers. Keyword filtering from the keywords configuration is
    also applied.
    """

    source_id: str = "eu_funding"
    source_name: str = "EU Funding & Tenders Portal"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect grant opportunities from the EU Funding & Tenders Portal.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from the EU portal.
        """
        logger.info("Fetching EU Funding & Tenders Portal: %s", _PORTAL_URL)

        try:
            response = http_client.get(_PORTAL_URL)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP error fetching EU portal: %d %s",
                exc.response.status_code, exc.response.reason_phrase,
            )
            return []
        except httpx.RequestError as exc:
            logger.error("Request error fetching EU portal: %s", exc)
            return []

        html = response.text
        search_terms = self._build_search_terms(keywords)

        opportunities = self._parse_listing(html, search_terms)

        logger.info(
            "EU Funding: parsed page, found %d matching opportunities",
            len(opportunities),
        )
        return opportunities

    def _parse_listing(
        self,
        html: str,
        search_terms: list[str],
    ) -> list[RawOpportunity]:
        """Parse the EU portal listing HTML for call entries.

        The portal renders call cards with titles, programme identifiers,
        deadlines, and links. This method extracts data from common HTML
        structures used by the portal.

        Args:
            html: The raw HTML of the listing page.
            search_terms: Keywords for additional content filtering.

        Returns:
            A list of RawOpportunity instances.
        """
        soup = BeautifulSoup(html, "lxml")
        opportunities: list[RawOpportunity] = []

        # The portal uses various container patterns for call cards.
        # We attempt multiple selectors for resilience.
        call_cards = (
            soup.select(".sedia-call-card")
            or soup.select("[class*='call-card']")
            or soup.select(".eui-card")
            or soup.select("article")
            or soup.select(".result-item")
        )

        if not call_cards:
            logger.warning(
                "EU Funding: no call cards found in HTML (page structure may have changed)"
            )
            # Fallback: attempt to extract links from the whole page
            call_cards = [soup]

        for card in call_cards:
            opp = self._parse_call_card(card, search_terms)
            if opp is not None:
                opportunities.append(opp)

        return opportunities

    def _parse_call_card(
        self,
        card,
        search_terms: list[str],
    ) -> Optional[RawOpportunity]:
        """Extract opportunity data from a single call card element.

        Args:
            card: A BeautifulSoup element representing a call card.
            search_terms: Keywords for content filtering.

        Returns:
            A RawOpportunity if the card matches filters, or None.
        """
        # Extract title and link
        title_el = (
            card.select_one("h3 a")
            or card.select_one("h2 a")
            or card.select_one("a[class*='title']")
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

        # Extract programme identifier from card text
        card_text = card.get_text(separator=" ", strip=True)
        card_text_lower = card_text.lower()

        # Filter: must relate to a target health programme OR match keywords
        programme_match = any(
            prog in card_text_lower for prog in _TARGET_PROGRAMMES
        )
        keyword_match = _text_matches_keywords(card_text, search_terms)

        if not programme_match and not keyword_match:
            return None

        # Extract deadline
        deadline_date = _extract_deadline(card_text)

        # Determine scheme/programme name from card text
        scheme_name = _extract_programme_name(card_text)

        return RawOpportunity(
            url=link,
            title=title.strip() if title else None,
            funder_name="European Commission",
            scheme_name=scheme_name,
            source_id=self.source_id,
            content_text=card_text.strip() if card_text else None,
            content_html=str(card),
            deadline_date=deadline_date,
            deadline_type="fixed" if deadline_date else "unknown",
            amount_raw=None,
            language="en",
        )


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

    Looks for common date patterns near deadline-related words.

    Args:
        text: The card text content.

    Returns:
        An ISO 8601 date string (YYYY-MM-DD) or None.
    """
    text_lower = text.lower()

    # Search near deadline keywords
    deadline_keywords = ["deadline", "closing date", "submission", "closes"]
    for kw in deadline_keywords:
        idx = text_lower.find(kw)
        if idx == -1:
            continue

        region = text[idx:idx + 150]

        # Try ISO date: 2025-06-15
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", region)
        if iso_match:
            return iso_match.group(1)

        # Try European date: 15 June 2025
        eu_match = re.search(
            r"(\d{1,2})\s+(January|February|March|April|May|June|July|"
            r"August|September|October|November|December)\s+(\d{4})",
            region,
            re.IGNORECASE,
        )
        if eu_match:
            return _to_iso_date(
                int(eu_match.group(3)),
                eu_match.group(2),
                int(eu_match.group(1)),
            )

        # Try DD/MM/YYYY (European convention)
        slash_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", region)
        if slash_match:
            day = int(slash_match.group(1))
            month = int(slash_match.group(2))
            year = int(slash_match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def _extract_programme_name(text: str) -> Optional[str]:
    """Extract the EU programme name from card text.

    Args:
        text: The card text content.

    Returns:
        The programme name or None.
    """
    text_lower = text.lower()

    programme_labels = {
        "horizon europe": "Horizon Europe",
        "eu4health": "EU4Health",
        "horizon-msca": "Horizon Europe MSCA",
        "horizon-erc": "Horizon Europe ERC",
        "horizon-hlth": "Horizon Europe Health",
        "horizon-cl1": "Horizon Europe Cluster 1 (Health)",
    }

    for key, label in programme_labels.items():
        if key in text_lower:
            return label

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
