"""Grants.gov REST API adapter.

Queries the Grants.gov search endpoint for health-related federal
funding opportunities using keyword-based POST requests.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)

_API_URL = "https://www.grants.gov/grantsws/rest/opportunities/search/"


class GrantsGovAdapter(SourceAdapter):
    """Adapter for the Grants.gov REST API.

    Sends POST requests with keyword queries to the Grants.gov opportunity
    search endpoint. Results are filtered to health-related categories.
    """

    source_id: str = "grants_gov"
    source_name: str = "Grants.gov"

    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect grant opportunities from the Grants.gov API.

        Builds search queries from the keywords configuration, queries the
        Grants.gov REST API for each keyword, and deduplicates by opportunity URL.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances from Grants.gov.
        """
        search_terms = self._build_search_terms(keywords)
        if not search_terms:
            logger.warning("Grants.gov: no search terms configured, skipping")
            return []

        seen_urls: set[str] = set()
        opportunities: list[RawOpportunity] = []

        for keyword in search_terms:
            results = self._query_api(http_client, keyword)
            for opp in results:
                if opp.url not in seen_urls:
                    seen_urls.add(opp.url)
                    opportunities.append(opp)

        logger.info(
            "Grants.gov: collected %d unique opportunities from %d keyword queries",
            len(opportunities), len(search_terms),
        )
        return opportunities

    def _query_api(
        self,
        http_client: httpx.Client,
        keyword: str,
    ) -> list[RawOpportunity]:
        """Execute a single keyword search against the Grants.gov API.

        Args:
            http_client: Shared httpx client.
            keyword: The search keyword.

        Returns:
            A list of RawOpportunity instances from this query.
        """
        payload = {
            "keyword": keyword,
            "oppStatuses": "forecasted|posted",
            "fundingCategories": "HL",
        }

        logger.debug("Grants.gov: querying with keyword=%r", keyword)

        try:
            response = http_client.post(
                _API_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Grants.gov HTTP error for keyword=%r: %d %s",
                keyword, exc.response.status_code, exc.response.reason_phrase,
            )
            return []
        except httpx.RequestError as exc:
            logger.error("Grants.gov request error for keyword=%r: %s", keyword, exc)
            return []

        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            logger.error("Grants.gov: invalid JSON response for keyword=%r: %s", keyword, exc)
            return []

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> list[RawOpportunity]:
        """Parse the Grants.gov API JSON response into RawOpportunity instances.

        The response structure is expected to contain an 'oppHits' list, where
        each hit has fields such as 'id', 'title', 'agency', 'openDate',
        'closeDate', and 'oppDesc'.

        Args:
            data: The parsed JSON response dict.

        Returns:
            A list of RawOpportunity instances.
        """
        if not isinstance(data, dict):
            logger.warning("Grants.gov: response is not a dict, skipping")
            return []

        hits = data.get("oppHits", [])
        if not isinstance(hits, list):
            logger.warning("Grants.gov: 'oppHits' is not a list, skipping")
            return []

        opportunities: list[RawOpportunity] = []

        for hit in hits:
            if not isinstance(hit, dict):
                continue

            opp_id = hit.get("id", "")
            title = hit.get("title", "")
            agency = hit.get("agency", "")
            close_date = hit.get("closeDate", "")
            open_date = hit.get("openDate", "")
            description = hit.get("oppDesc", "") or hit.get("description", "")

            # Build the opportunity detail URL
            if opp_id:
                url = f"https://www.grants.gov/search-results-detail/{opp_id}"
            else:
                # Skip entries without an ID -- we cannot construct a useful URL
                logger.debug("Grants.gov: skipping entry with no ID: %s", title)
                continue

            # Parse the close date into ISO format if possible
            deadline_date = _normalise_date(close_date)

            opp = RawOpportunity(
                url=url,
                title=title.strip() if title else None,
                funder_name=agency.strip() if agency else "US Federal Government",
                scheme_name=None,
                source_id=self.source_id,
                content_text=description.strip() if description else None,
                content_html=None,
                deadline_date=deadline_date,
                deadline_type="fixed" if deadline_date else "unknown",
                amount_raw=None,
                language="en",
            )
            opportunities.append(opp)

        return opportunities


def _normalise_date(date_str: Optional[str]) -> Optional[str]:
    """Attempt to normalise a date string to ISO 8601 (YYYY-MM-DD).

    Grants.gov commonly returns dates in MM/DD/YYYY format.

    Args:
        date_str: The raw date string from the API.

    Returns:
        An ISO 8601 date string, or None if parsing fails.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    date_str = date_str.strip()

    # Try MM/DD/YYYY format (common in Grants.gov)
    parts = date_str.split("/")
    if len(parts) == 3:
        try:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{year:04d}-{month:02d}-{day:02d}"
        except (ValueError, IndexError):
            pass

    # Try ISO format directly (YYYY-MM-DD)
    if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
        return date_str[:10]

    logger.debug("Grants.gov: could not parse date %r", date_str)
    return None
