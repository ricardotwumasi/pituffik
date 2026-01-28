"""Tests for the Pituffik database access layer."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from pipeline import db
from pipeline.models import (
    Enrichment,
    FxRate,
    Opportunity,
    OpportunitySnapshot,
)


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with schema initialised."""
    db_path = tmp_path / "test_grants.sqlite"
    conn = db.get_connection(db_path)
    db.initialise_schema(conn)
    yield conn
    conn.close()


class TestSchemaInitialisation:
    """Tests for schema creation."""

    def test_tables_created(self, test_db):
        tables = test_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "opportunities" in table_names
        assert "opportunity_snapshots" in table_names
        assert "enrichments" in table_names
        assert "pipeline_runs" in table_names
        assert "fx_rates" in table_names
        assert "user_actions" in table_names


class TestOpportunityCRUD:
    """Tests for opportunity insert/update/query."""

    def _make_opp(self, **overrides) -> Opportunity:
        defaults = {
            "opportunity_id": "abc123def456789a",
            "url_canonical": "https://example.com/grant/1",
            "url_source": "https://example.com/grant/1",
            "source_id": "test",
            "title": "Test Grant",
            "funder_name": "Test Funder",
        }
        defaults.update(overrides)
        return Opportunity(**defaults)

    def test_insert_new(self, test_db):
        opp = self._make_opp()
        is_new = db.upsert_opportunity(test_db, opp)
        assert is_new is True

    def test_update_existing(self, test_db):
        opp = self._make_opp()
        db.upsert_opportunity(test_db, opp)
        is_new = db.upsert_opportunity(test_db, opp)
        assert is_new is False

    def test_get_opportunity(self, test_db):
        opp = self._make_opp()
        db.upsert_opportunity(test_db, opp)
        result = db.get_opportunity(test_db, opp.opportunity_id)
        assert result is not None
        assert result.title == "Test Grant"

    def test_get_all_ids(self, test_db):
        opp = self._make_opp()
        db.upsert_opportunity(test_db, opp)
        ids = db.get_all_opportunity_ids(test_db)
        assert opp.opportunity_id in ids

    def test_update_fields(self, test_db):
        opp = self._make_opp()
        db.upsert_opportunity(test_db, opp)
        db.update_opportunity_fields(test_db, opp.opportunity_id, relevance_score=0.85)
        result = db.get_opportunity(test_db, opp.opportunity_id)
        assert result.relevance_score == 0.85


class TestSnapshots:
    """Tests for snapshot storage."""

    def test_insert_and_retrieve_hash(self, test_db):
        opp = Opportunity(
            opportunity_id="snap_test_id_1234",
            url_canonical="https://example.com/snap",
            url_source="https://example.com/snap",
            source_id="test",
        )
        db.upsert_opportunity(test_db, opp)

        snapshot = OpportunitySnapshot(
            opportunity_id=opp.opportunity_id,
            content_text="Test content",
            content_hash="abc123hash",
        )
        db.insert_snapshot(test_db, snapshot)
        result = db.get_latest_snapshot_hash(test_db, opp.opportunity_id)
        assert result == "abc123hash"


class TestEnrichments:
    """Tests for enrichment caching."""

    def test_insert_and_cache_lookup(self, test_db):
        opp = Opportunity(
            opportunity_id="enrich_test_1234",
            url_canonical="https://example.com/enrich",
            url_source="https://example.com/enrich",
            source_id="test",
        )
        db.upsert_opportunity(test_db, opp)

        enrichment = Enrichment(
            opportunity_id=opp.opportunity_id,
            task_type="relevance",
            prompt_version="v1",
            model_id="gemini-1.5-flash",
            input_hash="hash_abc_123",
            output_json='{"relevance_score": 0.9}',
        )
        db.insert_enrichment(test_db, enrichment)
        cached = db.get_cached_enrichment(test_db, "hash_abc_123", "relevance")
        assert cached is not None
        assert cached.output_json == '{"relevance_score": 0.9}'


class TestFxRates:
    """Tests for FX rate storage."""

    def test_upsert_and_retrieve(self, test_db):
        rate = FxRate(
            rate_date="2025-01-28",
            currency="GBP",
            rate_to_eur=0.8456,
            rate_to_gbp=1.0,
        )
        db.upsert_fx_rate(test_db, rate)
        result = db.get_fx_rate(test_db, "GBP", "2025-01-28")
        assert result is not None
        assert result.rate_to_eur == 0.8456

    def test_get_latest_rate(self, test_db):
        r1 = FxRate(rate_date="2025-01-27", currency="GBP", rate_to_eur=0.84)
        r2 = FxRate(rate_date="2025-01-28", currency="GBP", rate_to_eur=0.85)
        db.upsert_fx_rate(test_db, r1)
        db.upsert_fx_rate(test_db, r2)
        result = db.get_fx_rate(test_db, "GBP")
        assert result is not None
        assert result.rate_date == "2025-01-28"


class TestPipelineRuns:
    """Tests for pipeline run audit log."""

    def test_start_and_finish(self, test_db):
        run_id = db.start_pipeline_run(test_db)
        assert run_id > 0
        db.finish_pipeline_run(
            test_db, run_id,
            status="completed",
            opportunities_found=10,
            opportunities_new=5,
        )
        result = db.get_latest_pipeline_run(test_db)
        assert result is not None
        assert result.status == "completed"
        assert result.opportunities_found == 10
