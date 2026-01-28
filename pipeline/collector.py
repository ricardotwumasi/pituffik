"""Source adapter registry and dispatch for Pituffik pipeline.

Loads enabled adapters from config/sources.yml and runs them to collect
raw grant opportunities from all configured sources.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Optional

import httpx
import yaml

from pipeline.adapters.base import SourceAdapter
from pipeline.models import RawOpportunity
from pipeline.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.yml"
_KEYWORDS_PATH = Path(__file__).resolve().parent.parent / "config" / "keywords.yml"


def _load_sources_config() -> dict:
    """Load the sources configuration from YAML."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_keywords() -> dict:
    """Load the keywords configuration from YAML."""
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_adapter_class(module_path: str) -> type[SourceAdapter]:
    """Dynamically import an adapter module and return its adapter class.

    Each adapter module is expected to define exactly one class that
    inherits from SourceAdapter.

    Args:
        module_path: Dotted Python module path (e.g. "pipeline.adapters.ukri").

    Returns:
        The SourceAdapter subclass found in the module.

    Raises:
        ImportError: If the module cannot be imported.
        ValueError: If no SourceAdapter subclass is found.
    """
    module = importlib.import_module(module_path)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, SourceAdapter)
            and attr is not SourceAdapter
        ):
            return attr
    raise ValueError(f"No SourceAdapter subclass found in {module_path}")


def get_enabled_adapters() -> list[tuple[str, SourceAdapter, dict]]:
    """Load all enabled source adapters.

    Returns:
        A list of (source_id, adapter_instance, source_config) tuples.
    """
    config = _load_sources_config()
    adapters = []

    for source_id, source_cfg in config.get("sources", {}).items():
        if not source_cfg.get("enabled", False):
            logger.info("Skipping disabled source: %s", source_id)
            continue

        module_path = source_cfg["adapter"]
        try:
            adapter_cls = _get_adapter_class(module_path)
            adapter = adapter_cls()
            adapters.append((source_id, adapter, source_cfg))
            logger.info("Loaded adapter: %s (%s)", source_id, adapter_cls.__name__)
        except (ImportError, ValueError) as exc:
            logger.error("Failed to load adapter for %s: %s", source_id, exc)

    return adapters


def collect_all(
    http_client: httpx.Client,
    rate_limiter: Optional[RateLimiter] = None,
) -> list[RawOpportunity]:
    """Run all enabled adapters and collect raw grant opportunities.

    Args:
        http_client: Shared httpx client.
        rate_limiter: Optional rate limiter instance.

    Returns:
        Combined list of RawOpportunity instances from all sources.
    """
    if rate_limiter is None:
        rate_limiter = RateLimiter()

    keywords = _load_keywords()
    adapters = get_enabled_adapters()
    all_opportunities: list[RawOpportunity] = []

    for source_id, adapter, source_cfg in adapters:
        min_interval = source_cfg.get("rate_limit_seconds", 2.0)
        rate_limiter.wait(source_id, min_interval)

        try:
            logger.info("Collecting from %s ...", source_id)
            opportunities = adapter.collect(http_client, keywords)
            rate_limiter.record_success(source_id)
            logger.info("Collected %d opportunities from %s", len(opportunities), source_id)
            all_opportunities.extend(opportunities)
        except Exception as exc:
            rate_limiter.record_error(source_id)
            logger.error("Error collecting from %s: %s", source_id, exc, exc_info=True)

    logger.info("Total raw opportunities collected: %d", len(all_opportunities))
    return all_opportunities
