"""Tests for Pituffik source adapter base class and collector."""

import pytest

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity


class MockAdapter(SourceAdapter):
    """A mock adapter for testing."""
    source_id = "mock"
    source_name = "Mock Source"

    def collect(self, http_client, keywords):
        return [
            RawOpportunity(
                url="https://example.com/grant/1",
                title="Test Grant Opportunity",
                funder_name="Test Funder",
                source_id=self.source_id,
            ),
        ]


class TestSourceAdapter:
    """Tests for the SourceAdapter base class."""

    def test_collect_returns_raw_opportunities(self):
        adapter = MockAdapter()
        results = adapter.collect(None, {})
        assert len(results) == 1
        assert isinstance(results[0], RawOpportunity)
        assert results[0].source_id == "mock"

    def test_build_search_terms(self):
        adapter = MockAdapter()
        keywords = {
            "thematic": {
                "primary": ["health research", "mental health"],
            },
        }
        terms = adapter._build_search_terms(keywords)
        assert "health research" in terms
        assert "mental health" in terms

    def test_repr(self):
        adapter = MockAdapter()
        assert "MockAdapter" in repr(adapter)
        assert "mock" in repr(adapter)
