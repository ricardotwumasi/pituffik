"""Pydantic models for Pituffik pipeline data structures.

Defines schemas for grant opportunities, enrichment outputs, and Gemini structured responses.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# -- Enums --

class OpportunityStatus(str, Enum):
    """Grant opportunity open/closed status."""
    OPEN = "open"
    CLOSED = "closed"
    UNVERIFIED = "unverified"


class DeadlineType(str, Enum):
    """How the deadline is determined."""
    FIXED = "fixed"
    ROLLING = "rolling"
    NONE = "none"
    UNKNOWN = "unknown"


class GrantTypeBucket(str, Enum):
    """Standardised grant type buckets."""
    FELLOWSHIP = "fellowship"
    PROJECT = "project"
    PROGRAMME = "programme"
    SEED = "seed"
    STUDENTSHIP = "studentship"
    INFRASTRUCTURE = "infrastructure"
    CENTRE = "centre"
    TRAVEL = "travel"
    OTHER = "other"


class GrantTypeSource(str, Enum):
    """How the grant type bucket was determined."""
    REGEX = "regex"
    GEMINI = "gemini"


class AmountConfidence(str, Enum):
    """Confidence level for extracted monetary amounts."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EnrichmentTaskType(str, Enum):
    """Types of Gemini enrichment task."""
    RELEVANCE = "relevance"
    EXTRACTION = "extraction"
    SYNOPSIS = "synopsis"
    GRANT_TYPE_FALLBACK = "grant_type_fallback"


class PipelineRunStatus(str, Enum):
    """Pipeline run outcome."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# -- Raw opportunity from source adapters --

class RawOpportunity(BaseModel):
    """A grant opportunity as collected from a source adapter, before enrichment."""
    url: str
    title: Optional[str] = None
    funder_name: Optional[str] = None
    scheme_name: Optional[str] = None
    source_id: str
    content_text: Optional[str] = None
    content_html: Optional[str] = None
    deadline_date: Optional[str] = None
    deadline_type: str = "unknown"
    amount_raw: Optional[str] = None
    language: Optional[str] = "en"


# -- Gemini structured output schemas --

class RelevanceResult(BaseModel):
    """Gemini relevance classification output."""
    relevance_score: float = Field(ge=0.0, le=1.0, description="Relevance to health research profile (0-1)")
    health_research_match: bool = Field(description="Whether the grant matches target health research themes")
    rationale: str = Field(description="One-sentence justification for the relevance score")


class ExtractionResult(BaseModel):
    """Gemini structured field extraction output for grants."""
    title: Optional[str] = None
    funder_name: Optional[str] = None
    scheme_name: Optional[str] = None
    country_or_region: Optional[str] = None
    language: Optional[str] = None
    deadline_date: Optional[str] = None
    deadline_type: Optional[str] = None
    open_date: Optional[str] = None
    eligibility: Optional[str] = None
    career_stage: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    amount_currency: Optional[str] = None
    amount_confidence: str = "unknown"
    amount_evidence: Optional[str] = None
    deadline_evidence: Optional[str] = None
    duration_months: Optional[int] = None
    host_institution_required: Optional[bool] = None
    topic_tags: list[str] = Field(default_factory=list)


class SynopsisResult(BaseModel):
    """Gemini English synopsis output for non-English grant adverts."""
    synopsis: str = Field(description="English summary of the grant opportunity")
    detected_language: str = Field(description="ISO 639-1 language code of the original text")


class GrantTypeFallbackResult(BaseModel):
    """Gemini grant type classification output for ambiguous titles."""
    grant_type_bucket: str = Field(
        description="One of: fellowship, project, programme, seed, studentship, "
        "infrastructure, centre, travel, other"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the classification")
    reasoning: str = Field(description="Brief explanation of the classification")


# -- Database row models --

class Opportunity(BaseModel):
    """A canonical grant opportunity record as stored in the database."""
    opportunity_id: str
    url_canonical: str
    url_source: str
    source_id: str
    title: Optional[str] = None
    funder_name: Optional[str] = None
    scheme_name: Optional[str] = None
    country_or_region: Optional[str] = None
    language: str = "en"
    deadline_date: Optional[str] = None
    deadline_type: str = "unknown"
    open_date: Optional[str] = None
    status: str = "unverified"
    summary_en: Optional[str] = None
    topics: Optional[str] = None  # JSON array stored as text
    eligibility: Optional[str] = None
    career_stage: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    amount_currency: Optional[str] = None
    amount_gbp_min: Optional[float] = None
    amount_gbp_max: Optional[float] = None
    amount_confidence: str = "unknown"
    duration_months: Optional[int] = None
    host_institution_required: Optional[bool] = None
    grant_type_bucket: Optional[str] = None
    grant_type_source: str = "regex"
    relevance_score: Optional[float] = None
    health_research_match: bool = False
    relevance_rationale: Optional[str] = None
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    emailed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OpportunitySnapshot(BaseModel):
    """A raw content snapshot for change detection."""
    snapshot_id: Optional[int] = None
    opportunity_id: str
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    content_text: Optional[str] = None
    content_html: Optional[str] = None
    content_hash: str
    extractor_version: str = "v1"
    notes: Optional[str] = None
    captured_at: Optional[str] = None


class Enrichment(BaseModel):
    """A Gemini enrichment result."""
    enrichment_id: Optional[int] = None
    opportunity_id: str
    task_type: str
    prompt_version: str
    model_id: str
    input_hash: str
    output_json: str
    tokens_used: Optional[int] = None
    created_at: Optional[str] = None


class PipelineRun(BaseModel):
    """An audit log entry for a pipeline execution."""
    run_id: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str = "running"
    opportunities_found: int = 0
    opportunities_new: int = 0
    opportunities_updated: int = 0
    enrichments_made: int = 0
    emails_sent: int = 0
    errors: Optional[str] = None  # JSON array
    run_metadata: Optional[str] = None  # JSON object


class FxRate(BaseModel):
    """An ECB exchange rate cached by date and currency."""
    rate_date: str
    currency: str
    rate_to_eur: float
    rate_to_gbp: Optional[float] = None
