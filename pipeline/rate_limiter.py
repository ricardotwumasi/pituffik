"""Per-source rate limiter with exponential backoff.

Ensures polite crawling by throttling requests to each source.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple per-source rate limiter.

    Tracks the last request time per source key and enforces a minimum
    interval between requests. Supports exponential backoff on errors.
    """

    def __init__(self) -> None:
        self._last_request: dict[str, float] = {}
        self._backoff_until: dict[str, float] = {}
        self._consecutive_errors: dict[str, int] = {}

    def wait(self, source_id: str, min_interval: float = 2.0) -> None:
        """Wait until it is safe to make a request to the given source.

        Args:
            source_id: Identifier for the source (e.g. "ukri").
            min_interval: Minimum seconds between requests to this source.
        """
        now = time.monotonic()

        # Check backoff
        backoff_until = self._backoff_until.get(source_id, 0.0)
        if now < backoff_until:
            sleep_time = backoff_until - now
            logger.debug("Rate limiter: backoff for %s -- sleeping %.1fs", source_id, sleep_time)
            time.sleep(sleep_time)

        # Check interval
        last = self._last_request.get(source_id, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            logger.debug("Rate limiter: throttle for %s -- sleeping %.1fs", source_id, sleep_time)
            time.sleep(sleep_time)

        self._last_request[source_id] = time.monotonic()

    def record_success(self, source_id: str) -> None:
        """Record a successful request, resetting the error counter."""
        self._consecutive_errors[source_id] = 0

    def record_error(self, source_id: str, base_backoff: float = 5.0) -> None:
        """Record a failed request and apply exponential backoff.

        Args:
            source_id: The source that errored.
            base_backoff: Base backoff time in seconds (doubled per consecutive error).
        """
        errors = self._consecutive_errors.get(source_id, 0) + 1
        self._consecutive_errors[source_id] = errors
        backoff = base_backoff * (2 ** (errors - 1))
        # Cap at 5 minutes
        backoff = min(backoff, 300.0)
        self._backoff_until[source_id] = time.monotonic() + backoff
        logger.warning(
            "Rate limiter: error #%d for %s -- backing off %.1fs",
            errors, source_id, backoff,
        )

    def get_consecutive_errors(self, source_id: str) -> int:
        """Return the number of consecutive errors for a source."""
        return self._consecutive_errors.get(source_id, 0)
