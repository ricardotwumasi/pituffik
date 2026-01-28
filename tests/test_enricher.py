"""Tests for the Pituffik enricher module (unit tests, no API calls)."""

import json
import pytest

from pipeline.models import (
    ExtractionResult,
    GrantTypeFallbackResult,
    RelevanceResult,
    SynopsisResult,
)


class TestRelevanceResult:
    """Tests for RelevanceResult Pydantic model."""

    def test_valid_result(self):
        result = RelevanceResult(
            relevance_score=0.85,
            health_research_match=True,
            rationale="Strong match for mental health research funding.",
        )
        assert result.relevance_score == 0.85
        assert result.health_research_match is True

    def test_score_bounds(self):
        with pytest.raises(Exception):
            RelevanceResult(
                relevance_score=1.5,
                health_research_match=True,
                rationale="Invalid score",
            )


class TestExtractionResult:
    """Tests for ExtractionResult Pydantic model."""

    def test_valid_extraction(self):
        result = ExtractionResult(
            title="NIHR Research for Patient Benefit",
            funder_name="NIHR",
            deadline_date="2025-06-15",
            deadline_type="fixed",
            amount_min=150000.0,
            amount_max=350000.0,
            amount_currency="GBP",
            amount_confidence="high",
            amount_evidence="Up to GBP 350,000",
            topic_tags=["health services research", "patient benefit"],
        )
        assert result.funder_name == "NIHR"
        assert result.amount_max == 350000.0

    def test_sparse_extraction(self):
        result = ExtractionResult(title="Some Grant")
        assert result.funder_name is None
        assert result.topic_tags == []


class TestSynopsisResult:
    """Tests for SynopsisResult Pydantic model."""

    def test_valid_synopsis(self):
        result = SynopsisResult(
            synopsis="This grant funds research in occupational health.",
            detected_language="da",
        )
        assert result.detected_language == "da"


class TestGrantTypeFallbackResult:
    """Tests for GrantTypeFallbackResult Pydantic model."""

    def test_valid_classification(self):
        result = GrantTypeFallbackResult(
            grant_type_bucket="fellowship",
            confidence=0.9,
            reasoning="The title explicitly mentions 'fellowship'.",
        )
        assert result.grant_type_bucket == "fellowship"
        assert result.confidence == 0.9
