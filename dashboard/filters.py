"""Filter logic for the Pituffik dashboard.

Provides helper functions for building filter UI choices and
applying filter logic to grant opportunity data.
"""

from __future__ import annotations

import sqlite3

from dashboard.data_access import get_distinct_values

# Display labels for the 9 grant type buckets
GRANT_TYPE_LABELS = {
    "fellowship": "Fellowship",
    "project": "Project Grant",
    "programme": "Programme Grant",
    "seed": "Seed / Pilot Funding",
    "studentship": "Studentship / Doctoral",
    "infrastructure": "Infrastructure",
    "centre": "Centre Grant",
    "travel": "Travel / Mobility",
    "other": "Other",
}

# Display labels for common funders
FUNDER_LABELS = {
    "UKRI": "UK Research and Innovation (UKRI)",
    "MRC": "Medical Research Council (MRC)",
    "ESRC": "Economic and Social Research Council (ESRC)",
    "Wellcome": "Wellcome Trust",
    "NIHR": "National Institute for Health and Care Research (NIHR)",
    "NIH": "National Institutes of Health (NIH)",
    "ERC": "European Research Council (ERC)",
    "Horizon Europe": "Horizon Europe",
    "DFF": "Danmarks Frie Forskningsfond (DFF)",
    "NordForsk": "NordForsk",
    "VR": "Vetenskapsradet (Swedish Research Council)",
    "NFR": "Norges Forskningsrad (Research Council of Norway)",
    "Novo Nordisk": "Novo Nordisk Foundation",
    "Lundbeck": "Lundbeck Foundation",
    "NHMRC": "National Health and Medical Research Council (NHMRC)",
    "ARC": "Australian Research Council (ARC)",
    "CIHR": "Canadian Institutes of Health Research (CIHR)",
}

# Display labels for languages
LANGUAGE_LABELS = {
    "en": "English",
    "da": "Danish",
    "sv": "Swedish",
    "nb": "Norwegian (Bokmal)",
    "nn": "Norwegian (Nynorsk)",
    "de": "German",
    "fr": "French",
    "nl": "Dutch",
}

# Display labels for career stages
CAREER_STAGE_LABELS = {
    "early_career": "Early Career / Postdoctoral",
    "mid_career": "Mid-Career / Senior Lecturer",
    "established": "Established / Professor",
    "any": "Any Career Stage",
    "doctoral": "Doctoral / PhD Student",
    "team": "Team / Multi-PI",
}


def get_filter_choices(conn: sqlite3.Connection) -> dict:
    """Build filter dropdown choices from the database.

    Returns:
        A dict with choices for each filter type.
    """
    funders = get_distinct_values(conn, "funder_name")
    grant_types = get_distinct_values(conn, "grant_type_bucket")
    regions = get_distinct_values(conn, "country_or_region")
    career_stages = get_distinct_values(conn, "career_stage")

    return {
        "funders": _build_funder_choices(funders),
        "grant_types": _build_grant_type_choices(grant_types),
        "regions": _build_region_choices(regions),
        "career_stages": _build_career_stage_choices(career_stages),
        "statuses": [
            ("open", "Open"),
            ("closed", "Closed"),
            ("unverified", "Unverified"),
        ],
    }


def _build_funder_choices(funders: list[str]) -> list[tuple[str, str]]:
    """Build funder filter choices from available funder names."""
    choices = [("", "All funders")]
    for funder in sorted(funders):
        label = FUNDER_LABELS.get(funder, funder)
        choices.append((funder, label))
    return choices


def _build_grant_type_choices(grant_types: list[str]) -> list[tuple[str, str]]:
    """Build grant type filter choices."""
    choices = [("", "All grant types")]
    for gt in grant_types:
        label = GRANT_TYPE_LABELS.get(gt, gt.replace("_", " ").title())
        choices.append((gt, label))
    return choices


def _build_region_choices(regions: list[str]) -> list[tuple[str, str]]:
    """Build region filter choices from available country/region values."""
    choices = [("", "All regions")]
    for region in sorted(regions):
        label = _region_label(region)
        choices.append((region, label))
    return choices


def _build_career_stage_choices(career_stages: list[str]) -> list[tuple[str, str]]:
    """Build career stage filter choices."""
    choices = [("", "All career stages")]
    for cs in career_stages:
        label = CAREER_STAGE_LABELS.get(cs, cs.replace("_", " ").title())
        choices.append((cs, label))
    return choices


def _region_label(code: str) -> str:
    """Convert a country or region code to a display label."""
    labels = {
        "GB": "United Kingdom",
        "UK": "United Kingdom",
        "US": "United States",
        "DK": "Denmark",
        "SE": "Sweden",
        "NO": "Norway",
        "DE": "Germany",
        "NL": "Netherlands",
        "FR": "France",
        "BE": "Belgium",
        "AT": "Austria",
        "CH": "Switzerland",
        "FI": "Finland",
        "IE": "Ireland",
        "IT": "Italy",
        "ES": "Spain",
        "PT": "Portugal",
        "AU": "Australia",
        "NZ": "New Zealand",
        "CA": "Canada",
        "EU": "European Union",
        "International": "International",
        "Scandinavia": "Scandinavia",
        "Nordic": "Nordic Countries",
    }
    return labels.get(code, code)
