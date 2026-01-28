"""Combined Danish research councils adapter.

Scrapes both Independent Research Fund Denmark (DFF / Danmarks Frie Forskningsfond)
and Innovation Fund Denmark (Innovationsfonden) for open funding calls.
Content may be in Danish or English.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

# Source URLs for the two Danish councils
_DFF_URLS = [
    "https://dff.dk/en/apply/calls",
    "https://dff.dk/en/apply",
]

_IFD_URLS = [
    "https://innovationsfonden.dk/en/programmes",
    "https://innovationsfonden.dk/en/apply",
]


class DanishCouncilsAdapter(SourceAdapter):
    """Combined adapter for Danish research funding councils.

    Scrapes both the Independent Research Fund Denmark (DFF) and
    Innovation Fund Denmark (IFD) for open calls. Each entry's
    funder_name is set to the originating council.
    """

    source_id: str = "danish_councils"
    source_name: str = "Danish Research Councils"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect open calls from both Danish research councils.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from DFF and IFD.
        """
        opportunities: list[RawOpportunity] = []

        # Collect from Independent Research Fund Denmark
        dff_opps = self._collect_from_council(
            http_client=http_client,
            urls=_DFF_URLS,
            funder_name="Independent Research Fund Denmark",
            domain_filter="dff.dk",
        )
        opportunities.extend(dff_opps)

        # Collect from Innovation Fund Denmark
        ifd_opps = self._collect_from_council(
            http_client=http_client,
            urls=_IFD_URLS,
            funder_name="Innovation Fund Denmark",
            domain_filter="innovationsfonden.dk",
        )
        opportunities.extend(ifd_opps)

        logger.info(
            "Danish Councils: found %d opportunities (DFF: %d, IFD: %d)",
            len(opportunities),
            len(dff_opps),
            len(ifd_opps),
        )
        return opportunities

    def _collect_from_council(
        self,
        http_client: httpx.Client,
        urls: list[str],
        funder_name: str,
        domain_filter: str,
    ) -> list[RawOpportunity]:
        """Scrape a specific council's pages for open calls.

        Tries each URL in the list until one succeeds.

        Args:
            http_client: Shared httpx client.
            urls: List of candidate URLs to scrape.
            funder_name: The funder name for generated opportunities.
            domain_filter: Domain string for filtering relevant links.

        Returns:
            A list of RawOpportunity instances from the council.
        """
        opportunities: list[RawOpportunity] = []
        soup = None

        # Try each URL until one succeeds
        for url in urls:
            try:
                response = http_client.get(url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")
                base_url = url
                break
            except httpx.HTTPError as exc:
                logger.debug("Failed to fetch %s: %s", url, exc)
                continue

        if soup is None:
            logger.warning("Could not fetch any page for %s", funder_name)
            return opportunities

        # Detect page language
        page_lang = self._detect_language(soup)

        # Look for call listings in common patterns
        cards = soup.select(
            ".card, article, .teaser, .listing-item, "
            ".views-row, .content-block, .call-item, "
            ".grid-item, .node--type-call, .accordion-item"
        )

        if not cards:
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
            full_url = urljoin(base_url, href)

            # Only retain links within the council's domain
            if domain_filter not in full_url:
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

            # Detect entry language
            card_text = card.get_text(separator=" ", strip=True)
            entry_lang = self._detect_entry_language(title, card_text, page_lang)

            # Check if the call is closed
            card_text_lower = card_text.lower()
            if "closed" in card_text_lower or "lukket" in card_text_lower or "afsluttet" in card_text_lower:
                continue

            # Extract deadline
            deadline_date = None
            deadline_keywords = [
                "deadline", "closes", "closing date",
                "ansogningsfrist", "ansoegningsfrist", "frist",
            ]
            deadline_el = card.find(
                string=lambda t: t and any(kw in t.lower() for kw in deadline_keywords)
            )
            if deadline_el:
                deadline_date = deadline_el.strip()

            deadline_type = "unknown"
            if any(kw in card_text_lower for kw in ["rolling", "loebende", "kontinuerlig"]):
                deadline_type = "rolling"

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name=funder_name,
                scheme_name=title,
                source_id=self.source_id,
                content_html=str(card),
                content_text=card_text,
                deadline_date=deadline_date,
                deadline_type=deadline_type,
                language=entry_lang,
            )
            opportunities.append(opportunity)

        return opportunities

    @staticmethod
    def _detect_language(soup: BeautifulSoup) -> str:
        """Detect the page language from the html lang attribute.

        Args:
            soup: Parsed BeautifulSoup document.

        Returns:
            ISO 639-1 language code.
        """
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].lower().strip()
            if lang.startswith("da"):
                return "da"
            if lang.startswith("en"):
                return "en"
        return "en"

    @staticmethod
    def _detect_entry_language(title: str, content: str, fallback: str = "en") -> str:
        """Detect whether an entry is in Danish or English.

        Args:
            title: The entry title.
            content: The entry card text.
            fallback: Default language code if detection is inconclusive.

        Returns:
            ISO 639-1 language code ("da" or "en").
        """
        text = (title + " " + content).lower()
        danish_indicators = [
            "ansogning", "ansoegning", "bevilling", "forskning",
            "forskningsfond", "frist", "tilskud", "midler",
            "og", "kan", "til",
        ]
        # Require at least 3 matches to classify as Danish, since some
        # short common words (og, kan, til) may appear in English context
        matches = sum(1 for kw in danish_indicators if kw in text)
        if matches >= 3:
            return "da"
        return fallback
