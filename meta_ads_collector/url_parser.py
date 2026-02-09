"""URL parsing utilities for extracting page IDs from Facebook URLs.

Handles various URL formats used by Facebook to identify pages,
including Ad Library URLs, profile URLs, and vanity URLs.
"""

import logging
from typing import Optional
from urllib.parse import ParseResult, parse_qs, urlparse

logger = logging.getLogger(__name__)

# Recognised Facebook hostnames
_FACEBOOK_HOSTS = frozenset({
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
    "mobile.facebook.com",
    "l.facebook.com",
    "business.facebook.com",
})


def _is_facebook_url(parsed: ParseResult) -> bool:
    """Return True if the parsed URL belongs to a known Facebook hostname."""
    host = parsed.hostname or ""
    return host in _FACEBOOK_HOSTS


def extract_page_id_from_url(url: str) -> Optional[str]:
    """Extract a numeric page ID from a Facebook URL.

    Supports the following URL patterns:

    * **Ad Library URLs** with ``view_all_page_id`` query parameter::

        https://www.facebook.com/ads/library/?...&view_all_page_id=123456

    * **Profile URLs** with ``id`` query parameter::

        https://www.facebook.com/profile.php?id=123456

    * **Direct numeric page paths**::

        https://www.facebook.com/123456
        https://m.facebook.com/123456/

    * **Vanity / username URLs** -- these cannot be resolved to a numeric ID
      without a network call, so ``None`` is returned::

        https://www.facebook.com/CocaCola

    Args:
        url: A URL string.  Both ``http`` and ``https`` schemes are accepted.

    Returns:
        The numeric page ID as a string, or ``None`` if the ID cannot be
        determined from the URL alone.
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if not url:
        return None

    # If the input looks like a bare numeric ID, return it directly
    if url.isdigit():
        return url

    # Ensure URL has a scheme so urlparse works correctly
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        logger.debug("Failed to parse URL: %s", url)
        return None

    if not _is_facebook_url(parsed):
        logger.debug("Not a Facebook URL: %s", url)
        return None

    # Strategy 1: Check query parameters for explicit page IDs
    query_params = parse_qs(parsed.query)

    # Ad Library URLs: view_all_page_id=123456
    view_all = query_params.get("view_all_page_id", [None])[0]
    if view_all and view_all.isdigit():
        return view_all

    # Profile URLs: id=123456
    profile_id = query_params.get("id", [None])[0]
    if profile_id and profile_id.isdigit():
        return profile_id

    # Strategy 2: Check the URL path for a numeric page ID
    path = parsed.path.strip("/")

    # Remove common path prefixes
    # e.g., /ads/library/ -> ignore, we already checked query params
    # /pages/category/PageName/123456 -> extract trailing numeric
    # /p/PageName/123456 -> extract trailing numeric
    path_parts = [p for p in path.split("/") if p]

    if not path_parts:
        return None

    # If the entire path (or last segment) is numeric, it's a page ID
    # e.g., facebook.com/123456 or facebook.com/pages/Name/123456
    for part in reversed(path_parts):
        if part.isdigit() and len(part) >= 5:
            return part

    # If the path is a single non-numeric segment, it's a vanity URL
    # e.g., facebook.com/CocaCola -> cannot resolve without network
    if len(path_parts) == 1 and not path_parts[0].isdigit():
        logger.debug(
            "Vanity URL detected (%s) -- cannot resolve without network call",
            path_parts[0],
        )
        return None

    # Could not determine page ID
    return None
