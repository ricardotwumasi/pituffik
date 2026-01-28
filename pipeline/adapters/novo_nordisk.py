"""Novo Nordisk Foundation source adapter.

Scrapes the Novo Nordisk Foundation grants page for open funding calls.
The foundation is based in Denmark, so content may be in Danish or English.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_LISTING_URL = "https://novonordiskfonden.dk/en/grants/"


class NovoNordiskAdapter(SourceAdapter):
    """Adapter for Novo Nordisk Foundation funding.

    Scrapes the foundation's grants listing page for open calls.
    Content may appear in Danish or English; the adapter attempts
    to detect the language from page content.
    """

    source_id: str = "novo_nordisk"
    source_name: str = "Novo Nordisk Foundation"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect open funding calls from the Novo Nordisk Foundation.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from the Novo Nordisk Foundation.
        """
        opportunities: list[RawOpportunity] = []

        try:
            response = http_client.get(_LISTING_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Novo Nordisk Foundation grants page: %s", exc)
            return opportunities

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # Detect page language from the html lang attribute
        page_lang = self._detect_language(soup)

        # The grants page typically lists calls in card or list format.
        cards = soup.select(
            ".card, article, .teaser, .listing-item, "
            ".grant-item, .grant-card, .views-row, "
            ".content-listing__item, .grid-item"
        )

        if not cards:
            # Fallback: search main content area
            main_content = soup.select_one("main, .main-content, #content, .page-content")
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

            # Only retain NNF-domain links and skip duplicates
            if "novonordiskfonden.dk" not in full_url:
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

            # Try to detect if this individual entry is in Danish
            card_text = card.get_text(separator=" ", strip=True)
            entry_lang = page_lang
            danish_indicators = ["ansoegning", "ansogning", "bevilling", "frist", "tilskud", "forsknings"]
            if any(kw in card_text.lower() for kw in danish_indicators):
                entry_lang = "da"

            # Check for status (open/closed/upcoming)
            status_text = card_text.lower()
            if "closed" in status_text or "lukket" in status_text:
                # Skip closed calls
                continue

            # Extract deadline if visible
            deadline_date = None
            deadline_keywords_en = ["deadline", "closes", "closing date", "apply by"]
            deadline_keywords_da = ["frist", "ansoegningsfrist", "ansogningsfrist"]
            all_deadline_keywords = deadline_keywords_en + deadline_keywords_da

            deadline_el = card.find(
                string=lambda t: t and any(kw in t.lower() for kw in all_deadline_keywords)
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Novo Nordisk Foundation",
                scheme_name=title,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card_text,
                deadline_date=deadline_date,
                language=entry_lang,
            )
            opportunities.append(opportunity)

        logger.info("Novo Nordisk: found %d funding opportunities", len(opportunities))
        return opportunities

    @staticmethod
    def _detect_language(soup: BeautifulSoup) -> str:
        """Detect the page language from the html lang attribute.

        Args:
            soup: Parsed BeautifulSoup document.

        Returns:
            ISO 639-1 language code, defaulting to "en" for the English page.
        """
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].lower().strip()
            if lang.startswith("da"):
                return "da"
            if lang.startswith("en"):
                return "en"
        # The /en/ path indicates the English version
        return "en"
