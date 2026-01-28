"""Alzheimer's Research UK source adapter.

Scrapes the ARUK apply for funding page for available grants, fellowships,
and studentships.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://www.alzheimersresearchuk.org/research/for-researchers/apply/"


class ARUKAdapter(SourceAdapter):
    """Adapter for Alzheimer's Research UK funding.

    Scrapes the ARUK apply-for-funding page and extracts
    available grants, fellowships, and PhD studentships.
    """

    source_id: str = "aruk"
    source_name: str = "Alzheimer's Research UK"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect funding opportunities from the ARUK website.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from ARUK.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch ARUK funding page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # ARUK may present funding schemes as cards, sections, or
        # content blocks with links to individual scheme pages.
        cards = soup.select(
            ".card, article, .teaser, .listing-item, "
            ".funding-scheme, .content-block, .grid-item, "
            ".panel, .accordion-item, section.scheme"
        )

        if not cards:
            # Fallback: search for link-bearing elements in main content
            main_content = soup.select_one("main, .main-content, #content, .page-content")
            if main_content:
                cards = main_content.find_all(["article", "div", "li", "section"], recursive=True)
            else:
                cards = []

        seen_urls: set[str] = set()

        for card in cards:
            link_tag = card.find("a", href=True)
            if not link_tag:
                continue

            href = link_tag["href"]
            full_url = urljoin(_LISTING_URL, href)

            # Only retain ARUK-domain links and skip duplicates
            if "alzheimersresearchuk.org" not in full_url:
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

            # Extract deadline information
            card_text = card.get_text(separator=" ", strip=True)
            deadline_date = None
            deadline_el = card.find(
                string=lambda t: t and any(
                    kw in t.lower() for kw in ["deadline", "closes", "closing date", "apply by"]
                )
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            deadline_type = "unknown"
            if any(kw in card_text.lower() for kw in ["rolling", "always open"]):
                deadline_type = "rolling"

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Alzheimer's Research UK",
                scheme_name=title,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card_text,
                deadline_date=deadline_date,
                deadline_type=deadline_type,
                language="en",
            )
            opportunities.append(opportunity)

        logger.info("ARUK: found %d funding opportunities", len(opportunities))
        return opportunities
