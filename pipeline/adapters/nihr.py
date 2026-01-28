"""NIHR (National Institute for Health and Care Research) source adapter.

Scrapes the NIHR funding opportunities listing page for open research funding calls.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://www.nihr.ac.uk/researchers/funding-opportunities/"


class NIHRAdapter(SourceAdapter):
    """Adapter for NIHR funding opportunities.

    Scrapes the main funding opportunities listing page and extracts
    individual funding call titles, links, and programme names.
    """

    source_id: str = "nihr"
    source_name: str = "NIHR"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect open funding calls from the NIHR website.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances found on the NIHR listing page.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch NIHR listing page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # The NIHR listing page typically presents funding calls as linked
        # items within article or card-style containers. We look for common
        # patterns: article tags, divs with funding-related classes, or
        # list items containing links.
        cards = soup.select(
            "article, .card, .funding-opportunity, "
            ".views-row, .listing-item, .node--type-funding"
        )

        if not cards:
            # Fallback: look for any heading-link combinations within the
            # main content area.
            main_content = soup.select_one("main, #main-content, .main-content, .region-content")
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

            # Skip non-NIHR links and duplicates
            if "nihr.ac.uk" not in full_url:
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extract title from link text or nearest heading
            title = None
            heading = card.find(["h2", "h3", "h4"])
            if heading:
                title = heading.get_text(strip=True)
            elif link_tag.get_text(strip=True):
                title = link_tag.get_text(strip=True)

            if not title:
                continue

            # Try to extract programme name from subtitle or metadata
            programme_name = None
            subtitle = card.find(class_=lambda c: c and ("subtitle" in c or "programme" in c or "type" in c))
            if subtitle:
                programme_name = subtitle.get_text(strip=True)

            # Extract any deadline text visible in the card
            deadline_date = None
            deadline_el = card.find(
                string=lambda t: t and any(
                    kw in t.lower() for kw in ["deadline", "closes", "closing date", "apply by"]
                )
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="NIHR",
                scheme_name=programme_name,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card.get_text(separator=" ", strip=True),
                deadline_date=deadline_date,
                language="en",
            )
            opportunities.append(opportunity)

        logger.info("NIHR: found %d funding opportunities", len(opportunities))
        return opportunities
