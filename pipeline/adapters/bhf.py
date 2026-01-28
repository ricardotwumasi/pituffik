"""British Heart Foundation source adapter.

Scrapes the BHF researcher information page for available funding opportunities.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://www.bhf.org.uk/for-professionals/information-for-researchers"


class BHFAdapter(SourceAdapter):
    """Adapter for British Heart Foundation funding.

    Scrapes the BHF researcher information page for grants,
    fellowships, and other funding schemes.
    """

    source_id: str = "bhf"
    source_name: str = "British Heart Foundation"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect funding opportunities from the BHF website.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from BHF.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch BHF researchers page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # BHF may use a variety of layout patterns: card grids,
        # promo blocks, or content sections with funding scheme links.
        cards = soup.select(
            ".card, .promo, article, .teaser, "
            ".listing-item, .content-block, .link-listing__item, "
            ".funding-scheme, .grid-item"
        )

        if not cards:
            # Fallback: search for links within the main content region
            main_content = soup.select_one("main, .main-content, #main, .region-content")
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

            # Only retain BHF-domain links and skip duplicates
            if "bhf.org.uk" not in full_url:
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extract title from heading or link text
            title = None
            heading = card.find(["h2", "h3", "h4"])
            if heading:
                title = heading.get_text(strip=True)
            elif link_tag.get_text(strip=True):
                title = link_tag.get_text(strip=True)

            if not title:
                continue

            # Look for scheme/programme name in metadata
            scheme_name = None
            scheme_el = card.find(class_=lambda c: c and ("scheme" in c or "programme" in c or "type" in c))
            if scheme_el:
                scheme_name = scheme_el.get_text(strip=True)

            # Extract deadline if visible
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
            if any(kw in card_text.lower() for kw in ["rolling", "always open", "no deadline"]):
                deadline_type = "rolling"

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="British Heart Foundation",
                scheme_name=scheme_name,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card_text,
                deadline_date=deadline_date,
                deadline_type=deadline_type,
                language="en",
            )
            opportunities.append(opportunity)

        logger.info("BHF: found %d funding opportunities", len(opportunities))
        return opportunities
