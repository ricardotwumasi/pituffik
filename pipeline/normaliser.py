"""URL canonicalisation, fuzzy deduplication, and grant type bucketing.

Handles:
- URL normalisation (strip tracking params, normalise scheme/host)
- Opportunity ID generation (SHA-256 of canonical URL)
- Fuzzy title+funder deduplication (rapidfuzz)
- Regex-based grant type classification
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz
from url_normalize import url_normalize

from pipeline.models import RawOpportunity, GrantTypeBucket

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yml"
_GRANT_TYPE_PATH = Path(__file__).resolve().parent.parent / "config" / "grant_type_mapping.yml"

# Query parameters to strip during URL normalisation
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "fbclid", "gclid", "mc_cid", "mc_eid",
}


def _load_settings() -> dict:
    """Load global settings."""
    with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_grant_type_mapping() -> dict:
    """Load grant type mapping configuration."""
    with open(_GRANT_TYPE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# -- URL Canonicalisation --

def canonicalise_url(url: str) -> str:
    """Normalise a URL for deduplication.

    - Applies standard URL normalisation (scheme, host, path)
    - Strips known tracking/analytics query parameters
    - Removes trailing slashes from path

    Args:
        url: The raw URL to normalise.

    Returns:
        The canonical URL string.
    """
    try:
        normalised = url_normalize(url)
    except Exception:
        # If url-normalize fails, fall back to basic cleanup
        normalised = url.strip()

    # Strip known tracking parameters
    normalised = _strip_query_params(normalised, _STRIP_PARAMS)

    # Remove trailing slash (unless it's the root)
    if normalised.endswith("/") and normalised.count("/") > 3:
        normalised = normalised.rstrip("/")

    return normalised


def _strip_query_params(url: str, params_to_strip: set[str]) -> str:
    """Remove specified query parameters from a URL."""
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    filtered = {
        k: v for k, v in query_params.items()
        if k.lower() not in params_to_strip
    }

    new_query = urlencode(filtered, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


# -- Opportunity ID Generation --

def generate_opportunity_id(canonical_url: str) -> str:
    """Generate a deterministic opportunity ID from a canonical URL.

    Uses SHA-256 truncated to 16 hex characters.

    Args:
        canonical_url: The canonicalised URL.

    Returns:
        A 16-character hex string.
    """
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


# -- Fuzzy Deduplication --

def deduplicate_opportunities(
    opportunities: list[RawOpportunity],
    existing_ids: set[str],
    fuzzy_threshold: int = 85,
) -> list[RawOpportunity]:
    """Remove duplicate opportunities using URL and fuzzy matching.

    Deduplication tiers:
    1. Exact canonical URL match (against existing DB IDs and within batch)
    2. Fuzzy title+funder match within the current batch

    Args:
        opportunities: Raw opportunities to deduplicate.
        existing_ids: Set of opportunity IDs already in the database.
        fuzzy_threshold: Minimum rapidfuzz score for fuzzy match (0-100).

    Returns:
        Deduplicated list of RawOpportunity instances.
    """
    unique: list[RawOpportunity] = []
    seen_ids: set[str] = set(existing_ids)
    seen_signatures: list[str] = []

    for opp in opportunities:
        canonical = canonicalise_url(opp.url)
        oid = generate_opportunity_id(canonical)

        # Tier 1: exact URL dedup
        if oid in seen_ids:
            logger.debug("Duplicate URL: %s", opp.url)
            continue
        seen_ids.add(oid)

        # Tier 2: fuzzy title+funder dedup
        sig = _opportunity_signature(opp)
        if sig and _is_fuzzy_duplicate(sig, seen_signatures, fuzzy_threshold):
            logger.debug("Fuzzy duplicate: %s", opp.title)
            continue
        if sig:
            seen_signatures.append(sig)

        unique.append(opp)

    logger.info(
        "Deduplication: %d input -> %d unique (%d removed)",
        len(opportunities), len(unique), len(opportunities) - len(unique),
    )
    return unique


def _opportunity_signature(opp: RawOpportunity) -> str | None:
    """Create a normalised signature for fuzzy matching.

    Combines title and funder into a lowercase string.
    """
    parts = []
    if opp.title:
        parts.append(opp.title.strip().lower())
    if opp.funder_name:
        parts.append(opp.funder_name.strip().lower())
    return " | ".join(parts) if parts else None


def _is_fuzzy_duplicate(
    signature: str,
    existing_signatures: list[str],
    threshold: int,
) -> bool:
    """Check if a signature fuzzy-matches any existing signature."""
    for existing in existing_signatures:
        score = fuzz.token_sort_ratio(signature, existing)
        if score >= threshold:
            return True
    return False


# -- Grant Type Bucketing --

_grant_type_mapping: Optional[dict] = None


def _get_grant_type_mapping() -> dict:
    """Load and cache the grant type mapping configuration."""
    global _grant_type_mapping
    if _grant_type_mapping is None:
        _grant_type_mapping = _load_grant_type_mapping()
    return _grant_type_mapping


def reset_grant_type_cache() -> None:
    """Clear the cached grant type mapping (useful for testing)."""
    global _grant_type_mapping
    _grant_type_mapping = None


def classify_grant_type(title: str) -> tuple[str, str]:
    """Classify a grant title into a type bucket using regex patterns.

    Patterns are tested in order from the grant_type_mapping.yml configuration.
    First match wins.

    Args:
        title: The grant/scheme title to classify.

    Returns:
        A tuple of (grant_type_bucket, grant_type_source) where source is
        "regex" if a pattern matched or "regex" with "other" bucket if no match.
    """
    if not title:
        return ("other", "regex")

    mapping = _get_grant_type_mapping()
    title_lower = title.lower().strip()

    for bucket_key, bucket_cfg in mapping.get("grant_type_buckets", {}).items():
        patterns = bucket_cfg.get("patterns", [])
        for pattern in patterns:
            try:
                if re.search(pattern, title_lower, re.IGNORECASE):
                    return (bucket_key, "regex")
            except re.error as exc:
                logger.warning("Invalid regex pattern '%s': %s", pattern, exc)

    return ("other", "regex")


def is_target_grant_type(grant_type_bucket: str) -> bool:
    """Check whether a grant type bucket corresponds to a target type.

    Target types: fellowship, project, programme.
    """
    mapping = _get_grant_type_mapping()
    bucket_cfg = mapping.get("grant_type_buckets", {}).get(grant_type_bucket, {})
    return bucket_cfg.get("target", False)
