"""Wellcome Trust source adapter.

Scrapes the Wellcome Trust grant funding schemes page for current funding schemes.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://wellcome.org/grant-funding/schemes"


class WellcomeAdapter(SourceAdapter):
    """Adapter for Wellcome Trust funding schemes.

    Scrapes the Wellcome grant funding schemes page and extracts
    scheme names, links, and open/closed status.
    """

    source_id: str = "wellcome"
    source_name: str = "Wellcome Trust"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect current funding schemes from the Wellcome Trust website.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances for Wellcome funding schemes.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Wellcome schemes page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # Wellcome typically lists schemes as cards or teaser blocks with
        # links, titles, and status indicators (e.g. "Open", "Closed").
        cards = soup.select(
            ".card, .teaser, .scheme-card, .listing-item, "
            ".views-row, article, .grid-item"
        )

        if not cards:
            # Fallback: search the main content for link containers
            main_content = soup.select_one("main, .main-content, #content, .region-content")
            if main_content:
                cards = main_content.find_all(["article", "div", "li"], recursive=True)
            else:
                cards = []

        seen_urls: set[str] = set()

        for card in cards:
            link_tag = card.find("a", href=True)
            if not link_tag:
                continue

            href = link_tag["href"]
            full_url = urljoin(_LISTING_URL, href)

            # Only keep Wellcome links and avoid duplicates
            if "wellcome.org" not in full_url:
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extract scheme name from heading or link text
            title = None
            heading = card.find(["h2", "h3", "h4"])
            if heading:
                title = heading.get_text(strip=True)
            elif link_tag.get_text(strip=True):
                title = link_tag.get_text(strip=True)

            if not title:
                continue

            # Detect status (open/closed) from card content
            card_text_lower = card.get_text(separator=" ", strip=True).lower()
            status = None
            if "open" in card_text_lower:
                status = "open"
            elif "closed" in card_text_lower:
                status = "closed"
            elif "coming soon" in card_text_lower:
                status = "coming_soon"

            # Extract deadline if present
            deadline_date = None
            deadline_el = card.find(
                string=lambda t: t and any(
                    kw in t.lower() for kw in ["deadline", "closes", "closing", "apply by"]
                )
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            # Determine deadline type based on scheme characteristics
            deadline_type = "unknown"
            if any(kw in card_text_lower for kw in ["rolling", "open call", "no deadline"]):
                deadline_type = "rolling"

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Wellcome Trust",
                scheme_name=title,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card.get_text(separator=" ", strip=True),
                deadline_date=deadline_date,
                deadline_type=deadline_type,
                language="en",
            )
            opportunities.append(opportunity)

        logger.info("Wellcome: found %d funding schemes", len(opportunities))
        return opportunities
