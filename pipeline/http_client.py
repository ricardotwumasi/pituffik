"""Shared HTTP client for Pituffik pipeline.

Provides a configured httpx client with retries, timeouts, and caching headers.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Default timeout for all requests (seconds)
_DEFAULT_TIMEOUT = 30.0

# Maximum number of automatic retries
_MAX_RETRIES = 3

# Default user agent
_DEFAULT_USER_AGENT = (
    "Pituffik/1.0 (Health Research Grant Discovery; +https://github.com/ricardotwumasi/pituffik)"
)


def create_client(
    user_agent: Optional[str] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> httpx.Client:
    """Create a configured httpx client for pipeline use.

    Args:
        user_agent: Custom user agent string. Falls back to default.
        timeout: Request timeout in seconds.

    Returns:
        A configured httpx.Client instance.
    """
    transport = httpx.HTTPTransport(retries=_MAX_RETRIES)
    client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout),
        headers={
            "User-Agent": user_agent or _DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9,da;q=0.8,sv;q=0.7,nb;q=0.6",
        },
        follow_redirects=True,
        max_redirects=5,
    )
    return client


def fetch_url(client: httpx.Client, url: str) -> httpx.Response:
    """Fetch a URL with the shared client, logging the request.

    Args:
        client: The httpx client to use.
        url: The URL to fetch.

    Returns:
        The HTTP response.

    Raises:
        httpx.HTTPStatusError: If the response status code indicates an error.
    """
    logger.debug("Fetching: %s", url)
    response = client.get(url)
    response.raise_for_status()
    logger.debug("Fetched %s -- status %d, %d bytes", url, response.status_code, len(response.content))
    return response


def fetch_rss(client: httpx.Client, url: str) -> str:
    """Fetch an RSS/XML feed and return the text content.

    Args:
        client: The httpx client to use.
        url: The feed URL.

    Returns:
        The raw RSS/XML text.
    """
    response = fetch_url(client, url)
    return response.text


def fetch_html(client: httpx.Client, url: str) -> str:
    """Fetch an HTML page and return the text content.

    Args:
        client: The httpx client to use.
        url: The page URL.

    Returns:
        The raw HTML text.
    """
    response = fetch_url(client, url)
    return response.text
