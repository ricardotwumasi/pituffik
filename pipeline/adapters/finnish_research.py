"""Research Council of Finland source adapter.

Scrapes the Research Council of Finland (formerly Academy of Finland)
calls for applications page for open funding opportunities.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://www.aka.fi/en/research-funding/apply-for-funding/calls-for-applications/"


class FinnishResearchAdapter(SourceAdapter):
    """Adapter for the Research Council of Finland.

    Scrapes the calls for applications listing page for open
    funding opportunities. Content is primarily in English
    (via the /en/ path) but may reference Finnish-language materials.
    """

    source_id: str = "finnish_research"
    source_name: str = "Research Council of Finland"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect open calls from the Research Council of Finland.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from the Research Council of Finland.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Research Council of Finland calls page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # The AKA site may list calls as card items, table rows,
        # or content sections with links to individual call pages.
        cards = soup.select(
            ".card, article, .teaser, .listing-item, "
            ".call-item, .views-row, .content-block, "
            ".grid-item, table tbody tr, .accordion-item"
        )

        if not cards:
            # Fallback: look for link containers in main content
            main_content = soup.select_one("main, .main-content, #content, .page-content")
            if main_content:
                cards = main_content.find_all(["article", "div", "li", "tr"], recursive=True)
            else:
                cards = []

        seen_urls: set[str] = set()

        for card in cards:
            link_tag = card.find("a", href=True)
            if not link_tag:
                continue

            href = link_tag["href"]
            full_url = urljoin(_LISTING_URL, href)

            # Only retain AKA-domain links and skip duplicates
            if "aka.fi" not in full_url:
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

            # Extract card text for further parsing
            card_text = card.get_text(separator=" ", strip=True)

            # Look for deadline text
            deadline_date = None
            deadline_el = card.find(
                string=lambda t: t and any(
                    kw in t.lower() for kw in [
                        "deadline", "closes", "closing date",
                        "apply by", "application period",
                    ]
                )
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            # Check for status (open/closed)
            card_text_lower = card_text.lower()
            if "closed" in card_text_lower or "ended" in card_text_lower:
                continue

            deadline_type = "unknown"
            if "continuous" in card_text_lower or "rolling" in card_text_lower:
                deadline_type = "rolling"

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Research Council of Finland",
                scheme_name=title,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card_text,
                deadline_date=deadline_date,
                deadline_type=deadline_type,
                language="en",
            )
            opportunities.append(opportunity)

        logger.info("Finnish Research Council: found %d funding calls", len(opportunities))
        return opportunities
