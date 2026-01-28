"""Cancer Research UK source adapter.

Scrapes the CRUK funding for researchers page for available grants and fellowships.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://www.cancerresearchuk.org/funding-for-researchers"


class CRUKAdapter(SourceAdapter):
    """Adapter for Cancer Research UK funding.

    Scrapes the CRUK researcher funding page and extracts
    available grants, fellowships, and programme opportunities.
    """

    source_id: str = "cruk"
    source_name: str = "Cancer Research UK"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect funding opportunities from the CRUK website.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from CRUK.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch CRUK funding page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # CRUK pages may use card layouts, teasers, or list items
        # to present funding opportunities.
        cards = soup.select(
            ".card, .teaser, article, .listing-item, "
            ".views-row, .node--type-funding-scheme, "
            ".funding-scheme, .grid-item, .content-listing__item"
        )

        if not cards:
            # Fallback: scan main content for link-bearing containers
            main_content = soup.select_one("main, .main-content, #content, .layout-content")
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

            # Only retain CRUK-domain links and skip duplicates
            if "cancerresearchuk.org" not in full_url:
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extract title
            title = None
            heading = card.find(["h2", "h3", "h4"])
            if heading:
                title = heading.get_text(strip=True)
            elif link_tag.get_text(strip=True):
                title = link_tag.get_text(strip=True)

            if not title:
                continue

            # Extract any status indication
            card_text = card.get_text(separator=" ", strip=True)
            deadline_type = "unknown"
            if any(kw in card_text.lower() for kw in ["rolling", "always open"]):
                deadline_type = "rolling"

            # Look for deadline text
            deadline_date = None
            deadline_el = card.find(
                string=lambda t: t and any(
                    kw in t.lower() for kw in ["deadline", "closes", "closing date"]
                )
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Cancer Research UK",
                source_id=self.source_id,
                content_html=str(card),
                content_text=card_text,
                deadline_date=deadline_date,
                deadline_type=deadline_type,
                language="en",
            )
            opportunities.append(opportunity)

        logger.info("CRUK: found %d funding opportunities", len(opportunities))
        return opportunities
