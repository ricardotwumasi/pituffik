"""Gemini enrichment engine for Pituffik.

Handles all Gemini API interactions for grant opportunities:
- Relevance classification against target health research profile
- Structured field extraction (amounts, deadlines, eligibility, etc.)
- English synopsis for non-English grant adverts
- Grant type fallback classification

Results are cached by SHA-256(prompt_version + grant_text) to avoid
redundant API calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from typing import Optional

from google import genai
from google.genai import types

from pipeline import db
from pipeline.models import (
    Enrichment,
    EnrichmentTaskType,
    ExtractionResult,
    GrantTypeFallbackResult,
    Opportunity,
    RelevanceResult,
    SynopsisResult,
)
from pipeline.prompts import extraction, grant_type_fallback, relevance, synopsis

logger = logging.getLogger(__name__)

# Gemini model ID
_MODEL_ID = "gemini-2.5-flash-lite"


def _get_client() -> genai.Client:
    """Create a Gemini API client.

    Reads the API key from the GEMINI_API_KEY environment variable.

    Returns:
        A configured Gemini client instance.

    Raises:
        RuntimeError: If GEMINI_API_KEY is not set.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set")
    return genai.Client(api_key=api_key)


def _compute_input_hash(prompt_version: str, text: str) -> str:
    """Compute a cache key from prompt version and input text.

    Args:
        prompt_version: The version string of the prompt template.
        text: The input text (full prompt or grant text).

    Returns:
        A SHA-256 hex digest string.
    """
    combined = f"{prompt_version}:{text}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _call_gemini(
    client: genai.Client,
    prompt: str,
    temperature: float = 0.1,
    response_schema: Optional[type] = None,
) -> str:
    """Call Gemini and return the response text.

    Args:
        client: The Gemini API client.
        prompt: The full prompt text.
        temperature: Sampling temperature.
        response_schema: Optional Pydantic model for structured output.

    Returns:
        The raw response text from Gemini.
    """
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )

    response = client.models.generate_content(
        model=_MODEL_ID,
        contents=prompt,
        config=config,
    )
    return response.text


def _get_or_call(
    conn: sqlite3.Connection,
    client: genai.Client,
    opp_id: str,
    task_type: str,
    prompt_version: str,
    prompt_text: str,
    temperature: float = 0.1,
) -> str:
    """Check cache, call Gemini if miss, store result.

    Looks up the enrichment cache by input hash and task type. If a cached
    result exists, returns it immediately. Otherwise, calls Gemini, stores
    the result, and returns the output JSON string.

    Args:
        conn: Database connection.
        client: Gemini API client.
        opp_id: The opportunity ID for cache association.
        task_type: The enrichment task type string.
        prompt_version: The prompt version for cache keying.
        prompt_text: The full prompt text to send to Gemini.
        temperature: Sampling temperature for the Gemini call.

    Returns:
        The JSON output string (from cache or fresh call).
    """
    input_hash = _compute_input_hash(prompt_version, prompt_text)

    # Check cache
    cached = db.get_cached_enrichment(conn, input_hash, task_type)
    if cached:
        logger.debug("Cache hit for %s/%s", opp_id, task_type)
        return cached.output_json

    # Call Gemini
    logger.info("Calling Gemini for %s/%s", opp_id, task_type)
    output_text = _call_gemini(client, prompt_text, temperature=temperature)

    # Store in cache
    enrichment = Enrichment(
        opportunity_id=opp_id,
        task_type=task_type,
        prompt_version=prompt_version,
        model_id=_MODEL_ID,
        input_hash=input_hash,
        output_json=output_text,
    )
    db.insert_enrichment(conn, enrichment)

    return output_text


def enrich_relevance(
    conn: sqlite3.Connection,
    client: genai.Client,
    opp: Opportunity,
    grant_text: str,
) -> Optional[RelevanceResult]:
    """Run relevance classification on a grant opportunity.

    Args:
        conn: Database connection.
        client: Gemini API client.
        opp: The opportunity to classify.
        grant_text: The grant text to analyse.

    Returns:
        RelevanceResult or None if the call fails.
    """
    prompt = relevance.build_prompt(grant_text)
    try:
        output = _get_or_call(
            conn, client, opp.opportunity_id,
            EnrichmentTaskType.RELEVANCE.value,
            relevance.PROMPT_VERSION,
            prompt,
            temperature=0.1,
        )
        data = json.loads(output)
        return RelevanceResult(**data)
    except Exception as exc:
        logger.error(
            "Relevance enrichment failed for %s: %s", opp.opportunity_id, exc
        )
        return None


def enrich_extraction(
    conn: sqlite3.Connection,
    client: genai.Client,
    opp: Opportunity,
    grant_text: str,
) -> Optional[ExtractionResult]:
    """Run structured field extraction on a grant opportunity.

    Args:
        conn: Database connection.
        client: Gemini API client.
        opp: The opportunity to extract from.
        grant_text: The grant text to parse.

    Returns:
        ExtractionResult or None if the call fails.
    """
    prompt = extraction.build_prompt(grant_text)
    try:
        output = _get_or_call(
            conn, client, opp.opportunity_id,
            EnrichmentTaskType.EXTRACTION.value,
            extraction.PROMPT_VERSION,
            prompt,
            temperature=0.1,
        )
        data = json.loads(output)
        return ExtractionResult(**data)
    except Exception as exc:
        logger.error(
            "Extraction enrichment failed for %s: %s", opp.opportunity_id, exc
        )
        return None


def enrich_synopsis(
    conn: sqlite3.Connection,
    client: genai.Client,
    opp: Opportunity,
    grant_text: str,
) -> Optional[SynopsisResult]:
    """Generate an English synopsis for a non-English grant opportunity.

    Args:
        conn: Database connection.
        client: Gemini API client.
        opp: The opportunity to summarise.
        grant_text: The non-English grant text.

    Returns:
        SynopsisResult or None if the call fails.
    """
    prompt = synopsis.build_prompt(grant_text)
    try:
        output = _get_or_call(
            conn, client, opp.opportunity_id,
            EnrichmentTaskType.SYNOPSIS.value,
            synopsis.PROMPT_VERSION,
            prompt,
            temperature=0.3,
        )
        data = json.loads(output)
        return SynopsisResult(**data)
    except Exception as exc:
        logger.error(
            "Synopsis enrichment failed for %s: %s", opp.opportunity_id, exc
        )
        return None


def enrich_grant_type_fallback(
    conn: sqlite3.Connection,
    client: genai.Client,
    opp: Opportunity,
) -> Optional[GrantTypeFallbackResult]:
    """Classify a grant's type when regex mapping returns 'other'.

    Uses the opportunity title and optional scheme name as input to Gemini.

    Args:
        conn: Database connection.
        client: Gemini API client.
        opp: The opportunity with an ambiguous grant type.

    Returns:
        GrantTypeFallbackResult or None if the call fails.
    """
    if not opp.title:
        return None

    description = opp.scheme_name or ""
    prompt = grant_type_fallback.build_prompt(opp.title, description=description)
    try:
        output = _get_or_call(
            conn, client, opp.opportunity_id,
            EnrichmentTaskType.GRANT_TYPE_FALLBACK.value,
            grant_type_fallback.PROMPT_VERSION,
            prompt,
            temperature=0.1,
        )
        data = json.loads(output)
        return GrantTypeFallbackResult(**data)
    except Exception as exc:
        logger.error(
            "Grant type fallback failed for %s: %s", opp.opportunity_id, exc
        )
        return None


def enrich_opportunity(
    conn: sqlite3.Connection,
    client: genai.Client,
    opp: Opportunity,
    grant_text: str,
) -> dict:
    """Run all applicable enrichment tasks on a grant opportunity.

    Executes the following tasks in order:
    1. Relevance classification
    2. Structured field extraction
    3. English synopsis (only if the detected language is not English)
    4. Grant type fallback (only if regex classification returned 'other')

    Args:
        conn: Database connection.
        client: Gemini API client.
        opp: The opportunity to enrich.
        grant_text: The grant text content.

    Returns:
        A dict of field updates to apply to the opportunity record.
    """
    updates: dict = {}
    tasks_run = 0

    # 1. Relevance classification
    rel = enrich_relevance(conn, client, opp, grant_text)
    if rel:
        updates["relevance_score"] = rel.relevance_score
        updates["health_research_match"] = int(rel.health_research_match)
        updates["relevance_rationale"] = rel.rationale
        tasks_run += 1

    # 2. Structured extraction
    ext = enrich_extraction(conn, client, opp, grant_text)
    if ext:
        updates["title"] = ext.title
        updates["funder_name"] = ext.funder_name
        updates["scheme_name"] = ext.scheme_name
        updates["country_or_region"] = ext.country_or_region
        updates["language"] = ext.language
        updates["deadline_date"] = ext.deadline_date
        updates["deadline_type"] = ext.deadline_type
        updates["open_date"] = ext.open_date
        updates["eligibility"] = ext.eligibility
        updates["career_stage"] = ext.career_stage
        updates["amount_min"] = ext.amount_min
        updates["amount_max"] = ext.amount_max
        updates["amount_currency"] = ext.amount_currency
        updates["amount_confidence"] = ext.amount_confidence
        updates["duration_months"] = ext.duration_months
        updates["host_institution_required"] = (
            int(ext.host_institution_required)
            if ext.host_institution_required is not None
            else None
        )
        updates["topics"] = (
            json.dumps(ext.topic_tags) if ext.topic_tags else None
        )
        tasks_run += 1

    # 3. Synopsis for non-English opportunities
    detected_lang = ext.language if ext else opp.language
    if detected_lang and detected_lang not in ("en", "eng"):
        syn = enrich_synopsis(conn, client, opp, grant_text)
        if syn:
            updates["summary_en"] = syn.synopsis
            updates["language"] = syn.detected_language
            tasks_run += 1

    # 4. Grant type fallback if regex returned "other"
    title = ext.title if ext and ext.title else opp.title
    if title:
        from pipeline.normaliser import classify_grant_type

        grant_type_bucket, grant_type_source = classify_grant_type(title)
        if grant_type_bucket == "other":
            fallback = enrich_grant_type_fallback(conn, client, opp)
            if fallback:
                updates["grant_type_bucket"] = fallback.grant_type_bucket
                updates["grant_type_source"] = "gemini"
                tasks_run += 1
        else:
            updates["grant_type_bucket"] = grant_type_bucket
            updates["grant_type_source"] = grant_type_source

    logger.info("Enriched %s: %d tasks run", opp.opportunity_id, tasks_run)
    return updates
