"""Research Council of Norway (Forskningsradet) RSS adapter.

Parses the Forskningsradet RSS feed for open funding calls (utlysninger).
Content may be in Norwegian Bokmal or English.
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

# RSS feed hub page
_RSS_PAGE_URL = "https://www.forskningsradet.no/en/rss-feed/"

# Known feed URLs for calls/utlysninger
_KNOWN_FEED_URLS = [
    "https://www.forskningsradet.no/en/rss/utlysninger/",
    "https://www.forskningsradet.no/rss/utlysninger/",
    "https://www.forskningsradet.no/en/rss/calls/",
]


class NorwegianResearchCouncilAdapter(SourceAdapter):
    """Adapter for the Research Council of Norway (Forskningsradet).

    Discovers and parses the calls (utlysninger) RSS feed.
    Content may be in Norwegian Bokmal (nb) or English (en).
    """

    source_id: str = "norwegian_research_council"
    source_name: str = "Research Council of Norway"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect funding calls from the Research Council of Norway RSS feed.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from Forskningsradet.
        """
        opportunities: list[RawOpportunity] = []

        # Step 1: Discover the calls/utlysninger RSS feed URL
        feed_url = self._discover_feed_url(http_client)
        if not feed_url:
            logger.warning("Norwegian Research Council: could not discover RSS feed URL")
            return opportunities

        # Step 2: Fetch and parse the RSS feed
        try:
            response = http_client.get(feed_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Forskningsradet RSS feed at %s: %s", feed_url, exc)
            return opportunities

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            logger.warning(
                "Forskningsradet RSS feed parse error (no entries): %s",
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

            opportunity = RawOpportunity(
                url=full_url,
                title=title,
                funder_name="Research Council of Norway",
                scheme_name=title,
                source_id=self.source_id,
                content_text=content_text,
                deadline_date=deadline_date,
                language=language,
            )
            opportunities.append(opportunity)

        logger.info("Norwegian Research Council: found %d funding calls", len(opportunities))
        return opportunities

    def _discover_feed_url(self, http_client: httpx.Client) -> str | None:
        """Discover the RSS feed URL for calls/utlysninger.

        Attempts to load the RSS hub page and find a link to the
        calls feed. Falls back to known feed URLs.

        Args:
            http_client: Shared httpx client.

        Returns:
            The RSS feed URL, or None if discovery fails.
        """
        try:
            response = http_client.get(_RSS_PAGE_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Look for RSS/Atom link elements in the head
            rss_link = soup.find(
                "link",
                attrs={"type": lambda t: t and ("rss" in t or "xml" in t or "atom" in t)},
            )
            if rss_link and rss_link.get("href"):
                return urljoin(_RSS_PAGE_URL, rss_link["href"])

            # Look for calls/utlysninger RSS links in the page body
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                href_lower = href.lower()
                anchor_text = anchor.get_text(strip=True).lower()
                # Prioritise links that mention calls or utlysninger
                if any(kw in href_lower for kw in ["utlysning", "call", "rss"]) or \
                   any(kw in anchor_text for kw in ["utlysning", "call", "funding"]):
                    candidate = urljoin(_RSS_PAGE_URL, href)
                    if any(ext in candidate.lower() for ext in [".xml", "rss", "feed"]):
                        return candidate

        except httpx.HTTPError as exc:
            logger.debug("Could not fetch Forskningsradet RSS page for feed discovery: %s", exc)

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
        """Detect whether an entry is in Norwegian or English.

        Uses simple heuristics based on common Norwegian words.

        Args:
            title: The entry title.
            content: The entry content/summary text, if available.

        Returns:
            ISO 639-1 language code ("nb" for Norwegian Bokmal, or "en").
        """
        text = (title + " " + (content or "")).lower()
        norwegian_indicators = [
            "utlysning", "forskning", "soknad", "tilskudd",
            "forskningsradet", "prosjekt", "og", "kan",
            "frist", "midler",
        ]
        # Count Norwegian indicator matches
        matches = sum(1 for kw in norwegian_indicators if kw in text)
        if matches >= 2:
            return "nb"
        return "en"

    @staticmethod
    def _extract_deadline_text(text: str) -> str | None:
        """Extract deadline text from entry content.

        Looks for common deadline keywords in both English and Norwegian.

        Args:
            text: The entry content text.

        Returns:
            The deadline sentence or phrase, or None.
        """
        text_lower = text.lower()
        keywords = [
            "deadline", "closes", "closing date",
            "soknadsfrist", "frist", "siste frist",
        ]
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
