"""Seed pages adapter for user-editable funding URLs.

Reads URLs from config/seed_urls.yml, fetches each page, and extracts
title, deadline, and funding amount information. This adapter allows
users to add arbitrary funding page URLs without writing adapter code.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import httpx
import yaml
from bs4 import BeautifulSoup

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "seed_urls.yml"

# Regex patterns for extracting monetary amounts in common currencies.
# Matches patterns like: GBP 100,000 / EUR 1.5 million / $50,000 / 2,000,000 DKK
_CURRENCY_SYMBOLS = {
    "GBP": r"(?:GBP|gbp|\xa3|pounds?\s*sterling)",
    "EUR": r"(?:EUR|eur|\u20ac|euros?)",
    "USD": r"(?:USD|usd|\$|US\s*dollars?)",
    "DKK": r"(?:DKK|dkk|Danish\s*kroner?)",
    "SEK": r"(?:SEK|sek|Swedish\s*kronor?)",
    "NOK": r"(?:NOK|nok|Norwegian\s*kroner?)",
}

# Number patterns: 1,000,000 or 1.000.000 or 1000000 or 1.5 million
_NUMBER_PATTERN = r"[\d,.]+"
_MULTIPLIER_PATTERN = r"(?:\s*(?:million|m|thousand|k|billion|bn))?"

# Combined pattern: currency then number, or number then currency
_AMOUNT_PATTERNS: list[re.Pattern] = []
for _currency_name, _currency_re in _CURRENCY_SYMBOLS.items():
    # Currency before number: GBP 100,000
    _AMOUNT_PATTERNS.append(
        re.compile(
            rf"{_currency_re}\s*{_NUMBER_PATTERN}{_MULTIPLIER_PATTERN}",
            re.IGNORECASE,
        )
    )
    # Number before currency: 100,000 GBP
    _AMOUNT_PATTERNS.append(
        re.compile(
            rf"{_NUMBER_PATTERN}{_MULTIPLIER_PATTERN}\s*{_currency_re}",
            re.IGNORECASE,
        )
    )

# Deadline keywords used to locate deadline text on pages
_DEADLINE_KEYWORDS = [
    "deadline",
    "closing date",
    "closes",
    "apply by",
    "applications close",
    "submission deadline",
    "must be submitted by",
    "due date",
    "last date",
    "ansogningsfrist",
    "ansoegningsfrist",
    "frist",
    "sista ansokningsdag",
    "soknadsfrist",
]


class SeedPagesAdapter(SourceAdapter):
    """Adapter for user-editable seed page URLs.

    Reads config/seed_urls.yml, fetches each listed page, and extracts:
    - Title from h1 or title tag
    - Deadline text from page content
    - Funding amount from monetary patterns

    This lets users add funding sources by simply editing a YAML file.
    """

    source_id: str = "seed_pages"
    source_name: str = "Seed Pages"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect opportunities from user-configured seed page URLs.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances, one per seed URL.
        """
        config = self._load_seed_config()
        if not config:
            logger.warning("Seed pages: no configuration loaded or empty pages list")
            return []

        pages = config.get("pages", [])
        if not pages:
            logger.info("Seed pages: no URLs configured in seed_urls.yml")
            return []

        opportunities: list[RawOpportunity] = []

        for entry in pages:
            url = entry.get("url")
            if not url:
                logger.debug("Seed pages: skipping entry with no URL")
                continue

            funder = entry.get("funder", "Unknown")
            deadline_type = entry.get("deadline_type", "unknown")

            opportunity = self._process_seed_page(
                http_client=http_client,
                url=url,
                funder_name=funder,
                deadline_type=deadline_type,
            )
            if opportunity:
                opportunities.append(opportunity)

        logger.info("Seed pages: processed %d of %d URLs", len(opportunities), len(pages))
        return opportunities

    def _load_seed_config(self) -> dict | None:
        """Load the seed URLs configuration from YAML.

        Returns:
            The parsed YAML dict, or None if loading fails.
        """
        if not _CONFIG_PATH.exists():
            logger.warning("Seed pages config not found at %s", _CONFIG_PATH)
            return None

        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Failed to load seed_urls.yml: %s", exc)
            return None

    def _process_seed_page(
        self,
        http_client: httpx.Client,
        url: str,
        funder_name: str,
        deadline_type: str,
    ) -> RawOpportunity | None:
        """Fetch and process a single seed page URL.

        Args:
            http_client: Shared httpx client.
            url: The page URL to fetch.
            funder_name: The funder name from configuration.
            deadline_type: The deadline type from configuration.

        Returns:
            A RawOpportunity, or None if the page could not be processed.
        """
        try:
            response = http_client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Seed pages: failed to fetch %s: %s", url, exc)
            return None

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # Extract title from h1 or <title> tag
        title = self._extract_title(soup)

        # Extract page text for deadline and amount searching
        page_text = soup.get_text(separator=" ", strip=True)

        # Extract deadline text
        deadline_date = self._extract_deadline(soup, page_text)

        # Extract amount using regex patterns
        amount_raw = self._extract_amount(page_text)

        # Detect language
        language = self._detect_language(soup)

        return RawOpportunity(
            url=url,
            title=title,
            funder_name=funder_name,
            source_id=self.source_id,
            content_html=html,
            content_text=page_text[:10000] if page_text else None,  # Truncate very long pages
            deadline_date=deadline_date,
            deadline_type=deadline_type,
            amount_raw=amount_raw,
            language=language,
        )

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str | None:
        """Extract the page title from h1 or title tag.

        Prefers h1 within main content, falls back to the <title> tag.

        Args:
            soup: Parsed BeautifulSoup document.

        Returns:
            The extracted title string, or None.
        """
        # Try h1 tags first (more likely to be the page-specific title)
        h1 = soup.find("h1")
        if h1:
            title_text = h1.get_text(strip=True)
            if title_text:
                return title_text

        # Fall back to <title> tag
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            if title_text:
                # Strip common suffixes like " | UKRI" or " - Wellcome"
                for sep in [" | ", " - ", " :: ", " -- "]:
                    if sep in title_text:
                        title_text = title_text.split(sep)[0].strip()
                return title_text

        return None

    @staticmethod
    def _extract_deadline(soup: BeautifulSoup, page_text: str) -> str | None:
        """Extract deadline text from the page.

        Searches for deadline-related keywords and returns the
        surrounding text as a raw deadline string for later parsing.

        Args:
            soup: Parsed BeautifulSoup document.
            page_text: Full page text content.

        Returns:
            The extracted deadline text snippet, or None.
        """
        page_text_lower = page_text.lower()

        for keyword in _DEADLINE_KEYWORDS:
            idx = page_text_lower.find(keyword)
            if idx == -1:
                continue

            # Extract a window of text around the keyword
            start = max(0, idx)
            end = min(len(page_text), idx + len(keyword) + 150)
            snippet = page_text[start:end].strip()

            # Trim at paragraph or sentence boundary
            for sep in ["\n", ". ", "  "]:
                sep_idx = snippet.find(sep, len(keyword))
                if sep_idx != -1 and sep_idx > len(keyword) + 5:
                    snippet = snippet[:sep_idx].strip()
                    break

            if snippet:
                return snippet

        # Also check for structured deadline elements (e.g. <time>, <span class="deadline">)
        deadline_el = soup.find(
            class_=lambda c: c and any(
                kw in c.lower() for kw in ["deadline", "closing-date", "due-date"]
            )
        )
        if deadline_el:
            return deadline_el.get_text(strip=True)

        # Check for <time> tags with datetime attributes
        time_tags = soup.find_all("time")
        for time_tag in time_tags:
            parent_text = ""
            if time_tag.parent:
                parent_text = time_tag.parent.get_text(separator=" ", strip=True).lower()
            if any(kw in parent_text for kw in ["deadline", "closing", "closes", "apply"]):
                return time_tag.get_text(strip=True)

        return None

    @staticmethod
    def _extract_amount(page_text: str) -> str | None:
        """Extract the first monetary amount found on the page.

        Uses regex patterns to match common funding amount formats
        across GBP, EUR, USD, DKK, SEK, and NOK.

        Args:
            page_text: Full page text content.

        Returns:
            The matched amount string, or None.
        """
        for pattern in _AMOUNT_PATTERNS:
            match = pattern.search(page_text)
            if match:
                return match.group(0).strip()
        return None

    @staticmethod
    def _detect_language(soup: BeautifulSoup) -> str:
        """Detect the page language from the html lang attribute.

        Args:
            soup: Parsed BeautifulSoup document.

        Returns:
            ISO 639-1 language code, defaulting to "en".
        """
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].lower().strip()
            # Return the base language code
            if "-" in lang:
                lang = lang.split("-")[0]
            if lang in ("en", "da", "sv", "nb", "no", "fi"):
                # Normalise Norwegian to Bokmal
                if lang == "no":
                    return "nb"
                return lang
        return "en"
