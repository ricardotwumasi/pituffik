"""Abstract base class for Pituffik source adapters.

All source adapters must inherit from SourceAdapter and implement the
collect() method, which returns a list of RawOpportunity instances.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

import httpx

from pipeline.models import RawOpportunity

logger = logging.getLogger(__name__)


class SourceAdapter(abc.ABC):
    """Base class for all source adapters.

    Subclasses must implement collect() to fetch and parse grant listings
    from their respective source.
    """

    # Override in subclasses
    source_id: str = ""
    source_name: str = ""

    @abc.abstractmethod
    def collect(
        self,
        http_client: httpx.Client,
        keywords: dict,
    ) -> list[RawOpportunity]:
        """Collect grant opportunities from this source.

        Args:
            http_client: Shared httpx client for making requests.
            keywords: Keyword configuration dict (from keywords.yml).

        Returns:
            A list of RawOpportunity instances found at this source.
        """
        ...

    def _build_search_terms(self, keywords: dict) -> list[str]:
        """Build a flat list of search terms from the keywords config.

        Combines health research primary terms for constructing search queries.

        Args:
            keywords: The parsed keywords.yml dict.

        Returns:
            A list of search term strings.
        """
        thematic = keywords.get("thematic", {})
        terms = []
        terms.extend(thematic.get("primary", []))
        return terms

    def _build_combined_queries(self, keywords: dict, max_queries: int = 5) -> list[str]:
        """Build combined search queries pairing thematic terms.

        Useful for sources that support multi-word search.

        Args:
            keywords: The parsed keywords.yml dict.
            max_queries: Maximum number of queries to generate.

        Returns:
            A list of query strings.
        """
        thematic = keywords.get("thematic", {}).get("primary", [])
        domain = keywords.get("domain", {}).get("terms", [])

        queries = []
        for theme in thematic[:3]:
            for term in domain[:2]:
                queries.append(f"{theme} {term}")
                if len(queries) >= max_queries:
                    return queries
        return queries

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source_id={self.source_id!r}>"
