"""Async HTTP client for Meta Ad Library.

Uses ``httpx.AsyncClient`` as the transport layer while reusing all
token extraction, payload building, and response parsing logic from
the synchronous :class:`~meta_ads_collector.client.MetaAdsClient`.

Requires the ``httpx`` package::

    pip install meta-ads-collector[async]
"""

from __future__ import annotations

try:
    import httpx
except ImportError:
    raise ImportError(
        "httpx is required for async support. "
        "Install it with: pip install meta-ads-collector[async]"
    ) from None

import json
import logging
import random
import time
from typing import Any

from .client import MetaAdsClient
from .constants import (
    DOC_ID_SEARCH,
    DOC_ID_TYPEAHEAD,
    FALLBACK_CSR,
    FALLBACK_DYN,
    FALLBACK_REV,
    MAX_SESSION_AGE,
)
from .exceptions import (
    AuthenticationError,
    MetaAdsError,
    ProxyError,
    SessionExpiredError,
)
from .fingerprint import BrowserFingerprint, generate_fingerprint
from .proxy_pool import ProxyPool

logger = logging.getLogger(__name__)


class AsyncMetaAdsClient:
    """Async HTTP client for the Meta Ad Library.

    Mirrors the public API of :class:`~meta_ads_collector.client.MetaAdsClient`
    but uses ``httpx.AsyncClient`` for non-blocking I/O.  All token
    extraction, payload building, and response parsing logic is shared
    with the sync client to avoid duplication.

    Supports ``async with`` for resource cleanup::

        async with AsyncMetaAdsClient() as client:
            data, cursor = await client.search_ads(query="test")
    """

    BASE_URL = MetaAdsClient.BASE_URL
    AD_LIBRARY_URL = MetaAdsClient.AD_LIBRARY_URL
    GRAPHQL_URL = MetaAdsClient.GRAPHQL_URL

    def __init__(
        self,
        proxy: str | list[str] | ProxyPool | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        max_refresh_attempts: int = 3,
    ) -> None:
        """Initialize the async Meta Ads client.

        Args:
            proxy: Proxy configuration (single string, list, ProxyPool, or None).
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts per request.
            retry_delay: Base delay between retries (exponential backoff).
            max_refresh_attempts: Max consecutive session refresh failures.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_refresh_attempts = max_refresh_attempts

        # Reuse the sync client's logic helpers via composition.
        # _logic is ONLY used for non-HTTP methods; we never call its
        # network methods.
        self._logic = MetaAdsClient.__new__(MetaAdsClient)
        self._logic._fingerprint = generate_fingerprint()
        self._logic._tokens = {}
        self._logic._doc_ids = {}
        self._logic._request_counter = 0
        self._logic._init_time = None
        self._logic._consecutive_errors = 0
        self._logic._consecutive_refresh_failures = 0
        self._logic._max_session_age = MAX_SESSION_AGE
        self._logic.max_refresh_attempts = max_refresh_attempts

        self._fingerprint: BrowserFingerprint = self._logic._fingerprint
        self._tokens: dict[str, str] = self._logic._tokens
        self._doc_ids: dict[str, str] = self._logic._doc_ids
        self._initialized = False
        self._init_time: float | None = None

        # Proxy configuration
        self._proxy_pool: ProxyPool | None = None
        self._proxy_string: str | None = None
        self._current_proxy: str | None = None
        proxy_url: str | None = None

        if isinstance(proxy, ProxyPool):
            self._proxy_pool = proxy
        elif isinstance(proxy, list):
            self._proxy_pool = ProxyPool(proxy)
        elif isinstance(proxy, str):
            self._proxy_string = proxy
            proxy_url = self._format_proxy_url(proxy)

        # Build httpx client
        transport_kwargs: dict[str, Any] = {}
        if proxy_url:
            transport_kwargs["proxy"] = proxy_url

        self._client = httpx.AsyncClient(
            headers=self._fingerprint.get_default_headers(),
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            **transport_kwargs,
        )

    @staticmethod
    def _format_proxy_url(proxy: str) -> str:
        """Convert ``host:port`` or ``host:port:user:pass`` to a URL."""
        parts = proxy.split(":")
        if len(parts) == 4:
            host, port, username, password = parts
            return f"http://{username}:{password}@{host}:{port}"
        elif len(parts) == 2:
            host, port = parts
            return f"http://{host}:{port}"
        else:
            raise ProxyError(
                f"Invalid proxy format: {proxy!r}. "
                "Expected host:port or host:port:user:pass"
            )

    # ------------------------------------------------------------------
    # Delegated pure-logic helpers (no HTTP)
    # ------------------------------------------------------------------

    def _extract_tokens(self, html: str) -> dict[str, str]:
        return self._logic._extract_tokens(html)

    def _extract_doc_ids(self, html: str | None) -> dict[str, str]:
        return self._logic._extract_doc_ids(html)

    def _verify_tokens(self) -> None:
        self._logic._tokens = self._tokens
        self._logic._verify_tokens()

    def _calculate_jazoest(self, lsd: str) -> str:
        return self._logic._calculate_jazoest(lsd)

    def _build_graphql_payload(
        self,
        doc_id: str,
        variables: dict[str, Any],
        friendly_name: str,
    ) -> dict[str, str]:
        self._logic._tokens = self._tokens
        self._logic._doc_ids = self._doc_ids
        return self._logic._build_graphql_payload(doc_id, variables, friendly_name)

    def _parse_search_response(
        self, data: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        return self._logic._parse_search_response(data)

    def _parse_typeahead_response(
        self, data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self._logic._parse_typeahead_response(data)

    def _parse_ad_detail_page(
        self, html: str, ad_archive_id: str,
    ) -> dict[str, Any] | None:
        return self._logic._parse_ad_detail_page(html, ad_archive_id)

    def _is_session_stale(self) -> bool:
        if not self._init_time:
            return True
        return (time.time() - self._init_time) > self._logic._max_session_age

    async def _rebuild_client(self, proxy_url: str | None = None) -> None:
        """Close the current httpx client and create a new one.

        Args:
            proxy_url: Optional proxy URL for the new client.
        """
        await self._client.aclose()
        transport_kwargs: dict[str, Any] = {}
        if proxy_url:
            transport_kwargs["proxy"] = proxy_url
        self._client = httpx.AsyncClient(
            headers=self._fingerprint.get_default_headers(),
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            **transport_kwargs,
        )

    async def _async_refresh_session(self) -> bool:
        """Re-initialize the session when cookies/tokens become stale.

        Closes the old httpx client, generates a fresh fingerprint, creates
        a new client, and calls :meth:`initialize` to extract fresh tokens.

        Returns:
            True if the refresh succeeded.

        Raises:
            SessionExpiredError: If the maximum number of consecutive
                refresh failures has been exceeded.
        """
        if self._logic._consecutive_refresh_failures >= self.max_refresh_attempts:
            raise SessionExpiredError(
                f"Session refresh failed {self._logic._consecutive_refresh_failures} "
                f"consecutive times (max {self.max_refresh_attempts}). "
                "The Ad Library may be blocking this client."
            )

        logger.info("Refreshing async session (cookies/tokens may be stale)...")

        # Generate a fresh fingerprint
        self._fingerprint = generate_fingerprint()
        self._logic._fingerprint = self._fingerprint

        # Determine proxy URL for the new client
        proxy_url: str | None = None
        if self._proxy_string:
            proxy_url = self._format_proxy_url(self._proxy_string)
        elif self._proxy_pool is not None:
            proxy_url = self._proxy_pool.get_next()
            self._current_proxy = proxy_url

        # Recreate the httpx client
        await self._rebuild_client(proxy_url)

        # Reset session state
        self._tokens = {}
        self._doc_ids = {}
        self._logic._tokens = self._tokens
        self._logic._doc_ids = self._doc_ids
        self._logic._request_counter = 0
        self._logic._consecutive_errors = 0
        self._initialized = False

        try:
            result = await self.initialize()
            if result:
                self._logic._consecutive_refresh_failures = 0
            else:
                self._logic._consecutive_refresh_failures += 1
            return result
        except (AuthenticationError, MetaAdsError):
            self._logic._consecutive_refresh_failures += 1
            logger.warning(
                "Async session refresh failed (%d/%d)",
                self._logic._consecutive_refresh_failures,
                self.max_refresh_attempts,
            )
            return False

    # ------------------------------------------------------------------
    # Async HTTP methods
    # ------------------------------------------------------------------

    async def _make_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make an async HTTP request with retry logic."""
        merged_headers = dict(self._client.headers)
        if headers:
            merged_headers.update(headers)

        last_exception: Exception | None = None

        import asyncio

        for attempt in range(self.max_retries):
            # Proxy rotation: recreate client when the pool returns a new proxy
            pool_proxy: str | None = None
            if self._proxy_pool is not None:
                pool_proxy = self._proxy_pool.get_next()
                if pool_proxy != self._current_proxy:
                    self._current_proxy = pool_proxy
                    await self._rebuild_client(pool_proxy)

            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                )

                if response.status_code == 429:
                    if self._proxy_pool and pool_proxy:
                        self._proxy_pool.mark_failure(pool_proxy)
                    wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("Rate limited. Waiting %.2fs...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                # Mark proxy as successful
                if self._proxy_pool and pool_proxy:
                    self._proxy_pool.mark_success(pool_proxy)

                return response

            except httpx.HTTPError as exc:
                last_exception = exc
                # Mark proxy as failed
                if self._proxy_pool and pool_proxy:
                    self._proxy_pool.mark_failure(pool_proxy)
                wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Request failed (attempt %d/%d): %s",
                    attempt + 1, self.max_retries, exc,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait_time)

        if last_exception:
            raise last_exception
        raise httpx.HTTPError("Request failed after all retries")

    async def initialize(self) -> bool:
        """Initialize by loading the Ad Library page and extracting tokens.

        Returns:
            True if initialization succeeded.
        """
        import re

        logger.info("Initializing async Meta Ads client...")
        try:
            datr = self._logic._generate_datr()
            self._client.cookies.set(
                "datr", datr, domain=".facebook.com", path="/",
            )
            wd = f"{self._fingerprint.viewport_width}x{self._fingerprint.viewport_height}"
            self._client.cookies.set("wd", wd, domain=".facebook.com", path="/")
            self._client.cookies.set(
                "dpr", str(self._fingerprint.dpr),
                domain=".facebook.com", path="/",
            )

            init_headers = dict(self._fingerprint.get_default_headers())
            init_headers["sec-fetch-site"] = "none"

            response = await self._make_request(
                "GET",
                self.AD_LIBRARY_URL,
                params={
                    "active_status": "active",
                    "ad_type": "all",
                    "country": "US",
                    "media_type": "all",
                },
                headers=init_headers,
            )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"Failed to load Ad Library page (HTTP {response.status_code})"
                )

            html = response.text
            self._tokens = self._extract_tokens(html)
            self._doc_ids = self._extract_doc_ids(html)

            # Fallback LSD extraction
            if "lsd" not in self._tokens:
                lsd_match = re.search(r'"token":"([^"]{20,})"', html)
                if lsd_match:
                    self._tokens["lsd"] = lsd_match.group(1)

            # Generate fallback values
            if "__spin_t" not in self._tokens:
                self._tokens["__spin_t"] = str(int(time.time()))
            if "__spin_b" not in self._tokens:
                self._tokens["__spin_b"] = "trunk"
            if "__rev" not in self._tokens:
                rev_match = re.search(r'"server_revision":(\d+)', html)
                if rev_match:
                    self._tokens["__rev"] = rev_match.group(1)
                else:
                    self._tokens["__rev"] = FALLBACK_REV

            self._verify_tokens()
            self._initialized = True
            self._init_time = time.time()
            self._logic._init_time = self._init_time

            logger.info("Async client initialized successfully")
            return True

        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(f"Failed to initialize async client: {exc}") from exc

    async def search_ads(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = "ALL",
        active_status: str = "ACTIVE",
        media_type: str = "ALL",
        search_type: str = "KEYWORD_EXACT_PHRASE",
        page_ids: list[str] | None = None,
        cursor: str | None = None,
        first: int = 10,
        sort_direction: str = "DESCENDING",
        sort_mode: str | None = "SORT_BY_TOTAL_IMPRESSIONS",
        session_id: str | None = None,
        collation_token: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Search for ads (async version).

        Same parameters and return type as
        :meth:`~meta_ads_collector.client.MetaAdsClient.search_ads`.
        """
        if not self._initialized:
            await self.initialize()

        # Proactively refresh stale sessions
        if self._is_session_stale():
            logger.info("Async session is stale, refreshing before request...")
            if not await self._async_refresh_session():
                raise SessionExpiredError("Failed to refresh stale async session")

        import uuid
        from urllib.parse import quote

        session_id = session_id or str(uuid.uuid4())
        collation_token = collation_token or str(uuid.uuid4())

        variables: dict[str, Any] = {
            "activeStatus": active_status,
            "adType": ad_type,
            "bylines": [],
            "collationToken": collation_token,
            "contentLanguages": [],
            "countries": [country],
            "excludedIDs": [],
            "first": first,
            "isTargetedCountry": False,
            "location": None,
            "mediaType": media_type,
            "multiCountryFilterMode": None,
            "pageIDs": page_ids or [],
            "potentialReachInput": [],
            "publisherPlatforms": [],
            "queryString": query,
            "regions": [],
            "searchType": search_type,
            "sessionID": session_id,
            "source": None,
            "startDate": None,
            "v": self._tokens.get("v", "fbece7"),
            "viewAllPageID": "0",
        }

        if sort_mode == "SORT_BY_TOTAL_IMPRESSIONS":
            variables["sortData"] = {
                "direction": sort_direction,
                "mode": sort_mode,
            }

        if cursor:
            variables["cursor"] = cursor

        search_doc_id = self._doc_ids.get(
            "AdLibrarySearchPaginationQuery", DOC_ID_SEARCH,
        )
        payload = self._build_graphql_payload(
            doc_id=search_doc_id,
            variables=variables,
            friendly_name="AdLibrarySearchPaginationQuery",
        )

        ad_type_url = {
            "ALL": "all",
            "POLITICAL_AND_ISSUE_ADS": "political_and_issue_ads",
            "HOUSING_ADS": "housing",
            "EMPLOYMENT_ADS": "employment",
            "CREDIT_ADS": "credit",
        }.get(ad_type, "all")

        headers = dict(self._fingerprint.get_graphql_headers())
        headers["x-fb-friendly-name"] = "AdLibrarySearchPaginationQuery"
        headers["x-fb-lsd"] = self._tokens.get("lsd", "")
        headers["referer"] = (
            f"{self.AD_LIBRARY_URL}?active_status={active_status.lower()}"
            f"&ad_type={ad_type_url}&country={country}&q={quote(query)}"
        )

        response = await self._make_request(
            "POST", self.GRAPHQL_URL, data=payload, headers=headers,
        )

        # Handle 403 -- session likely expired, attempt refresh and retry
        if response.status_code == 403:
            logger.warning("Got 403 on async GraphQL request - refreshing session...")
            if await self._async_refresh_session():
                # Rebuild payload with new tokens
                lsd = self._tokens.get("lsd", "")
                payload["lsd"] = lsd
                payload["jazoest"] = self._calculate_jazoest(lsd)
                payload["__rev"] = self._tokens.get("__rev", FALLBACK_REV)
                payload["__spin_r"] = self._tokens.get("__spin_r", FALLBACK_REV)
                payload["__spin_t"] = self._tokens.get(
                    "__spin_t", str(int(time.time())),
                )
                payload["__spin_b"] = self._tokens.get("__spin_b", "trunk")
                payload["__hsi"] = self._tokens.get(
                    "__hsi", str(int(time.time() * 1000)),
                )
                payload["__dyn"] = self._tokens.get("__dyn", FALLBACK_DYN)
                payload["__csr"] = self._tokens.get("__csr", FALLBACK_CSR)
                if "__hsdp" in self._tokens:
                    payload["__hsdp"] = self._tokens["__hsdp"]
                if "__hblp" in self._tokens:
                    payload["__hblp"] = self._tokens["__hblp"]

                headers["x-fb-lsd"] = lsd
                response = await self._make_request(
                    "POST", self.GRAPHQL_URL, data=payload, headers=headers,
                )
            else:
                logger.error("Async session refresh failed, returning 403 response")

        if response.status_code != 200:
            raise MetaAdsError(
                f"GraphQL request failed with status {response.status_code}"
            )

        text = response.text
        if text.startswith("for (;;);"):
            text = text[9:]

        data = json.loads(text)

        if "errors" in data:
            errors = data["errors"]
            for error in errors:
                error_code = error.get("code")
                error_msg = error.get("message", "Unknown error")
                if error_code == 1675004 or "rate limit" in error_msg.lower():
                    return {
                        "ads": [], "page_info": {},
                        "rate_limited": True, "error": error_msg,
                    }, None
                if error_code in (1357004, 1357001) or "session" in error_msg.lower():
                    return {
                        "ads": [], "page_info": {},
                        "session_expired": True, "error": error_msg,
                    }, None
            if not data.get("data"):
                return {"ads": [], "page_info": {}, "error": str(errors)}, None

        return self._parse_search_response(data)

    async def search_pages(
        self,
        query: str,
        country: str = "US",
    ) -> list[dict[str, Any]]:
        """Search for pages using the typeahead endpoint (async version).

        Same parameters and return type as
        :meth:`~meta_ads_collector.client.MetaAdsClient.search_pages`.
        """
        if not self._initialized:
            await self.initialize()

        from urllib.parse import quote

        variables = {"queryString": query, "country": country, "adType": "ALL", "isMobile": False}
        typeahead_doc_id = self._doc_ids.get(
            "useAdLibraryTypeaheadSuggestionDataSourceQuery", DOC_ID_TYPEAHEAD,
        )
        payload = self._build_graphql_payload(
            doc_id=typeahead_doc_id,
            variables=variables,
            friendly_name="useAdLibraryTypeaheadSuggestionDataSourceQuery",
        )

        headers = dict(self._fingerprint.get_graphql_headers())
        headers["x-fb-friendly-name"] = "useAdLibraryTypeaheadSuggestionDataSourceQuery"
        headers["x-fb-lsd"] = self._tokens.get("lsd", "")
        headers["referer"] = (
            f"{self.AD_LIBRARY_URL}?active_status=all&ad_type=all"
            f"&country={country}&q={quote(query)}"
        )

        try:
            response = await self._make_request(
                "POST", self.GRAPHQL_URL, data=payload, headers=headers,
            )

            if response.status_code != 200:
                logger.error("Typeahead request failed: %d", response.status_code)
                return []

            text = response.text
            if text.startswith("for (;;);"):
                text = text[9:]

            data = json.loads(text)
            return self._parse_typeahead_response(data)

        except (json.JSONDecodeError, httpx.HTTPError) as exc:
            logger.error("Typeahead search failed: %s", exc)
            return []

    async def get_ad_details(
        self,
        ad_archive_id: str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch detailed ad data (async version).

        Same parameters and return type as
        :meth:`~meta_ads_collector.client.MetaAdsClient.get_ad_details`.
        """
        if not self._initialized:
            await self.initialize()

        # Approach 1: detail page
        try:
            headers = dict(self._fingerprint.get_default_headers())
            headers["referer"] = self.AD_LIBRARY_URL
            headers["sec-fetch-site"] = "same-origin"

            response = await self._make_request(
                "GET",
                self.AD_LIBRARY_URL,
                params={
                    "id": ad_archive_id,
                    "active_status": "all",
                    "ad_type": "all",
                    "country": "ALL",
                    "media_type": "all",
                },
                headers=headers,
            )

            if response.status_code == 200:
                detail_data = self._parse_ad_detail_page(
                    response.text, ad_archive_id,
                )
                if detail_data:
                    return detail_data
        except Exception as exc:
            logger.debug("Approach 1 failed for ad %s: %s", ad_archive_id, exc)

        # Approach 2: page-scoped search
        if page_id:
            try:
                response_data, _ = await self.search_ads(
                    query="",
                    search_type="PAGE",
                    page_ids=[page_id],
                    first=30,
                    active_status="ALL",
                    country="ALL",
                )
                for ad_data in response_data.get("ads", []):
                    found_id = str(
                        ad_data.get("ad_archive_id")
                        or ad_data.get("id")
                        or ad_data.get("adArchiveID")
                        or ""
                    )
                    if found_id == str(ad_archive_id):
                        return dict(ad_data)
            except Exception as exc:
                logger.debug("Approach 2 failed for ad %s: %s", ad_archive_id, exc)

        raise NotImplementedError(
            f"Could not retrieve detail data for ad {ad_archive_id}. "
            "All approaches exhausted."
        )

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
        self._initialized = False

    async def __aenter__(self) -> AsyncMetaAdsClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
