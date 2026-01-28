"""Tests for the Pituffik normaliser module."""

import pytest

from pipeline.normaliser import (
    canonicalise_url,
    classify_grant_type,
    deduplicate_opportunities,
    generate_opportunity_id,
    is_target_grant_type,
    reset_grant_type_cache,
)
from pipeline.models import RawOpportunity


class TestCanonicaliseUrl:
    """Tests for URL canonicalisation."""

    def test_strips_tracking_params(self):
        url = "https://example.com/grant?utm_source=email&id=123"
        result = canonicalise_url(url)
        assert "utm_source" not in result
        assert "id=123" in result

    def test_strips_trailing_slash(self):
        url = "https://example.com/opportunity/12345/"
        result = canonicalise_url(url)
        assert not result.endswith("/")

    def test_preserves_root_slash(self):
        url = "https://example.com/"
        result = canonicalise_url(url)
        assert result.endswith("/")

    def test_handles_malformed_url(self):
        url = "not a valid url"
        result = canonicalise_url(url)
        # url_normalize adds https:// prefix to bare strings
        assert result is not None
        assert len(result) > 0


class TestGenerateOpportunityId:
    """Tests for opportunity ID generation."""

    def test_deterministic(self):
        url = "https://example.com/grant/123"
        id1 = generate_opportunity_id(url)
        id2 = generate_opportunity_id(url)
        assert id1 == id2

    def test_length(self):
        url = "https://example.com/grant/123"
        result = generate_opportunity_id(url)
        assert len(result) == 16

    def test_different_urls_different_ids(self):
        id1 = generate_opportunity_id("https://example.com/grant/1")
        id2 = generate_opportunity_id("https://example.com/grant/2")
        assert id1 != id2


class TestDeduplicateOpportunities:
    """Tests for opportunity deduplication."""

    def test_removes_exact_url_duplicates(self):
        opps = [
            RawOpportunity(url="https://example.com/grant/1", title="Grant A", source_id="test"),
            RawOpportunity(url="https://example.com/grant/1", title="Grant A", source_id="test"),
        ]
        result = deduplicate_opportunities(opps, set())
        assert len(result) == 1

    def test_removes_fuzzy_duplicates(self):
        opps = [
            RawOpportunity(
                url="https://example.com/grant/1",
                title="NIHR Research for Patient Benefit",
                funder_name="NIHR",
                source_id="test",
            ),
            RawOpportunity(
                url="https://other.com/grant/2",
                title="NIHR Research for Patient Benefit Programme",
                funder_name="NIHR",
                source_id="test",
            ),
        ]
        result = deduplicate_opportunities(opps, set(), fuzzy_threshold=80)
        assert len(result) == 1

    def test_keeps_distinct_opportunities(self):
        opps = [
            RawOpportunity(
                url="https://example.com/grant/1",
                title="NIHR Research for Patient Benefit Programme",
                funder_name="NIHR",
                source_id="test",
            ),
            RawOpportunity(
                url="https://example.com/grant/2",
                title="Wellcome Trust Early Career Fellowship",
                funder_name="Wellcome",
                source_id="test",
            ),
        ]
        result = deduplicate_opportunities(opps, set())
        assert len(result) == 2

    def test_skips_existing_ids(self):
        opps = [
            RawOpportunity(url="https://example.com/grant/1", title="Grant A", source_id="test"),
        ]
        canonical = canonicalise_url("https://example.com/grant/1")
        existing = {generate_opportunity_id(canonical)}
        result = deduplicate_opportunities(opps, existing)
        assert len(result) == 0


class TestClassifyGrantType:
    """Tests for grant type classification."""

    def setup_method(self):
        reset_grant_type_cache()

    def test_fellowship(self):
        bucket, source = classify_grant_type("Early Career Research Fellowship")
        assert bucket == "fellowship"
        assert source == "regex"

    def test_project_grant(self):
        bucket, source = classify_grant_type("Standard Research Grant")
        assert bucket == "project"
        assert source == "regex"

    def test_programme_grant(self):
        bucket, source = classify_grant_type("Programme Grant for Applied Research")
        assert bucket == "programme"
        assert source == "regex"

    def test_studentship(self):
        bucket, source = classify_grant_type("PhD Studentship in Psychology")
        assert bucket == "studentship"
        assert source == "regex"

    def test_seed_pilot(self):
        bucket, source = classify_grant_type("Pilot Study Grant")
        assert bucket == "seed"
        assert source == "regex"

    def test_unknown_returns_other(self):
        bucket, source = classify_grant_type("Miscellaneous Support")
        assert bucket == "other"
        assert source == "regex"

    def test_empty_title(self):
        bucket, source = classify_grant_type("")
        assert bucket == "other"


class TestIsTargetGrantType:
    """Tests for target grant type checking."""

    def setup_method(self):
        reset_grant_type_cache()

    def test_fellowship_is_target(self):
        assert is_target_grant_type("fellowship") is True

    def test_project_is_target(self):
        assert is_target_grant_type("project") is True

    def test_programme_is_target(self):
        assert is_target_grant_type("programme") is True

    def test_studentship_is_not_target(self):
        assert is_target_grant_type("studentship") is False

    def test_other_is_not_target(self):
        assert is_target_grant_type("other") is False
