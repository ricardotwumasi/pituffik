"""Swedish Research Council (Vetenskapsradet) RSS adapter.

Parses the VR calls RSS feed for open funding opportunities. The feed
may contain content in Swedish or English.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

# The RSS calls page, which links to the actual feed URL
_CALLS_PAGE_URL = "https://www.vr.se/english/applying-for-funding/calls-and-decisions/calls-as-rss-feed.html"

# Known feed URL patterns -- the page may link to one of these
_KNOWN_FEED_URLS = [
    "https://www.vr.se/rss/utlysningar.xml",
    "https://www.vr.se/english/applying-for-funding/rss.xml",
]


class SwedishResearchCouncilAdapter(SourceAdapter):
    """Adapter for the Swedish Research Council (Vetenskapsradet).

    Discovers the RSS feed URL from the calls page and parses
    entries for open funding calls. Content may be in Swedish (sv)
    or English (en).
    """

    source_id: str = "swedish_research_council"
    source_name: str = "Swedish Research Council"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect funding calls from the Swedish Research Council RSS feed.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from VR.
        """
        opportunities: list[RawOpportunity] = []

        # Step 1: Discover the RSS feed URL from the calls page
        feed_url = self._discover_feed_url(http_client)
        if not feed_url:
            logger.warning("Swedish Research Council: could not discover RSS feed URL")
            return opportunities

        # Step 2: Fetch and parse the RSS feed
        try:
            response = http_client.get(feed_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch VR RSS feed at %s: %s", feed_url, exc)
            return opportunities

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            logger.warning(
                "VR RSS feed parse error (no entries): %s",
                feed.bozo_exception,
            )
            return opportunities

        # Step 3: Process feed entries
        seen_urls: set[str] = set()

        for entry in feed.entries:
            link = getattr(entry, "link", None)
            if not link:
                continue

            full_url = urljoin(feed_url, link)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            title = getattr(entry, "title", None)
            if not title:
                continue

            # Extract description/summary
            summary = getattr(entry, "summary", None) or getattr(entry, "description", None)
            content_text = summary if summary else None

            # Detect language from entry content
            language = self._detect_entry_language(title, content_text)

            # Extract deadline from description if present
            deadline_date = None
            if content_text:
                deadline_date = self._extract_deadline_text(content_text)

            # Extract published date as potential open_date reference
            published = getattr(entry, "published", None)

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Swedish Research Council",
                scheme_name=title,
                source_id=self.source_id,
                content_text=content_text,
                deadline_date=deadline_date,
                language=language,
            )
            opportunities.append(opportunity)

        logger.info("Swedish Research Council: found %d funding calls", len(opportunities))
        return opportunities

    def _discover_feed_url(self, http_client: httpx.Client) -> str | None:
        """Discover the RSS feed URL from the VR calls page.

        First attempts to load the calls page and find an RSS link.
        Falls back to known feed URLs if the page cannot be parsed.

        Args:
            http_client: Shared httpx client.

        Returns:
            The RSS feed URL, or None if discovery fails.
        """
        try:
            response = http_client.get(_CALLS_PAGE_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Look for RSS/Atom link elements in the head
            rss_link = soup.find(
                "link",
                attrs={"type": lambda t: t and ("rss" in t or "xml" in t or "atom" in t)},
            )
            if rss_link and rss_link.get("href"):
                return urljoin(_CALLS_PAGE_URL, rss_link["href"])

            # Look for RSS links in the page body
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                if any(kw in href.lower() for kw in [".xml", "rss", "feed"]):
                    return urljoin(_CALLS_PAGE_URL, href)

        except httpx.HTTPError as exc:
            logger.debug("Could not fetch VR calls page for feed discovery: %s", exc)

        # Fall back to known feed URLs
        for url in _KNOWN_FEED_URLS:
            try:
                response = http_client.get(url)
                if response.status_code == 200:
                    return url
            except httpx.HTTPError:
                continue

        return None

    @staticmethod
    def _detect_entry_language(title: str, content: str | None) -> str:
        """Detect whether an entry is in Swedish or English.

        Uses simple heuristics based on common Swedish words.

        Args:
            title: The entry title.
            content: The entry content/summary text, if available.

        Returns:
            ISO 639-1 language code ("sv" or "en").
        """
        text = (title + " " + (content or "")).lower()
        swedish_indicators = [
            "utlysning", "bidrag", "ansokan", "forskning",
            "vetenskapsradet", "och", "for", "att",
        ]
        # Count Swedish indicator matches
        matches = sum(1 for kw in swedish_indicators if kw in text)
        if matches >= 2:
            return "sv"
        return "en"

    @staticmethod
    def _extract_deadline_text(text: str) -> str | None:
        """Extract deadline text from entry content.

        Looks for common deadline keywords in both English and Swedish.

        Args:
            text: The entry content text.

        Returns:
            The deadline sentence or phrase, or None.
        """
        text_lower = text.lower()
        keywords = ["deadline", "closes", "closing date", "sista dag", "sista ansokningsdag"]
        for kw in keywords:
            idx = text_lower.find(kw)
            if idx != -1:
                # Return the surrounding text (up to 100 characters after keyword)
                start = max(0, idx)
                end = min(len(text), idx + len(kw) + 100)
                snippet = text[start:end].strip()
                # Trim at sentence boundary if possible
                for sep in [".", "\n", "<"]:
                    sep_idx = snippet.find(sep, len(kw))
                    if sep_idx != -1:
                        snippet = snippet[:sep_idx].strip()
                        break
                return snippet
        return None
