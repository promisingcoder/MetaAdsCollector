"""Async HTTP client for Meta Ad Library.

Uses ``curl_cffi.requests.AsyncSession`` with Chrome TLS fingerprint
impersonation -- the same approach as the sync client.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

from curl_cffi.requests import AsyncSession as CffiAsyncSession

from .client import MetaAdsClient
from .constants import (
    DOC_ID_SEARCH,
    DOC_ID_TYPEAHEAD,
    FALLBACK_REV,
    MAX_SESSION_AGE,
)
from .exceptions import (
    AuthenticationError,
    MetaAdsError,
    SessionExpiredError,
)
from .fingerprint import BrowserFingerprint, generate_fingerprint
from .proxy_pool import ProxyPool, parse_proxy

logger = logging.getLogger(__name__)


class AsyncMetaAdsClient:
    """Async HTTP client for the Meta Ad Library.

    Mirrors the public API of :class:`~meta_ads_collector.client.MetaAdsClient`
    but uses asynchronous I/O with ``curl_cffi.requests.AsyncSession`` and
    Chrome TLS impersonation.

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
        cookies: dict[str, str] | str | None = None,
    ) -> None:
        """Initialize the async Meta Ads client.

        Args:
            proxy: Proxy configuration (single string, list, ProxyPool, or None).
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts per request.
            retry_delay: Base delay between retries (exponential backoff).
            max_refresh_attempts: Max consecutive session refresh failures.
            cookies: Optional cookies to seed the session with, either a
                ``{name: value}`` dict or a ``"k=v; k2=v2"`` string.  This
                lets users reuse cookies from a logged-in browser session;
                the homepage bootstrap still runs to mine a fresh ``lsd``.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_refresh_attempts = max_refresh_attempts
        self._seed_cookies = cookies

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

        if isinstance(proxy, ProxyPool):
            self._proxy_pool = proxy
        elif isinstance(proxy, list):
            self._proxy_pool = ProxyPool(proxy)
        elif isinstance(proxy, str):
            self._proxy_string = proxy

        # Build the async HTTP client
        self._client: Any = None  # lazily set by _build_client
        self._build_client()

        logger.debug("Async client using curl_cffi with Chrome TLS impersonation")

    # ------------------------------------------------------------------
    # Client construction helpers
    # ------------------------------------------------------------------

    def _build_client(self, proxy_url: str | None = None) -> None:
        """Create the async HTTP client."""
        if proxy_url is None and self._proxy_string:
            proxy_url = self._format_proxy_url(self._proxy_string)

        kwargs: dict[str, Any] = {"impersonate": "chrome"}
        if proxy_url:
            kwargs["proxy"] = proxy_url
        self._client = CffiAsyncSession(**kwargs)
        self._client.headers.update(self._fingerprint.get_default_headers())

        # Re-seed user-supplied cookies on every (re)build so session
        # refreshes keep them.
        if self._seed_cookies:
            self._apply_cookies(self._seed_cookies)

    def _apply_cookies(self, cookies: dict[str, str] | str) -> None:
        """Seed session cookies for ``.facebook.com``.

        Accepts either a ``{name: value}`` dict or a cookie-header
        string of the form ``"k=v; k2=v2"``.
        """
        if isinstance(cookies, str):
            items = []
            for pair in cookies.split(";"):
                name, sep, value = pair.partition("=")
                if sep and name.strip():
                    items.append((name.strip(), value.strip()))
        else:
            items = [(str(k), str(v)) for k, v in cookies.items()]
        for name, value in items:
            self._client.cookies.set(name, value, domain=".facebook.com", path="/")

    @staticmethod
    def _format_proxy_url(proxy: str) -> str:
        """Normalize any proxy format accepted by :class:`ProxyPool`."""
        return parse_proxy(proxy)

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
        """Close the current client and create a new one."""
        await self._close_client()
        self._build_client(proxy_url)

    async def _close_client(self) -> None:
        """Close the underlying async client."""
        if self._client is None:
            return
        await self._client.close()

    async def _async_refresh_session(self) -> bool:
        """Re-initialize the session when cookies/tokens become stale.

        Closes the old client, generates a fresh fingerprint, creates
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

        # Recreate the client
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
    ) -> Any:
        """Make an async HTTP request with retry logic."""
        import asyncio

        merged_headers = dict(self._client.headers)
        if headers:
            merged_headers.update(headers)

        last_exception: Exception | None = None

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
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                    timeout=self.timeout,
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

            except Exception as exc:
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
        raise MetaAdsError("Request failed after all retries")

    async def _handle_challenge(self, response: Any) -> bool:
        """Handle Facebook's JavaScript verification challenge (async).

        Facebook returns a page with a JS challenge that POSTs to
        ``/__rd_verify_*`` and sets an ``rd_challenge`` cookie.

        Returns:
            True if the challenge was solved successfully.
        """
        import asyncio
        import re

        text = response.text
        match = re.search(r"fetch\('(/__rd_verify_[^']+)'", text)
        if not match:
            logger.debug("No challenge URL found in response")
            return False

        challenge_path = match.group(1)
        challenge_url = f"{self.BASE_URL}{challenge_path}"
        logger.info("Handling async verification challenge: %s...", challenge_path[:50])

        challenge_headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "origin": "https://www.facebook.com",
            "sec-ch-ua": self._fingerprint.sec_ch_ua,
            "sec-ch-ua-mobile": self._fingerprint.sec_ch_ua_mobile,
            "sec-ch-ua-platform": self._fingerprint.sec_ch_ua_platform,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": self._fingerprint.user_agent,
        }

        for attempt in range(3):
            try:
                await self._make_request(
                    "POST", challenge_url, headers=challenge_headers,
                )
                break
            except Exception as retry_err:
                logger.warning("Challenge POST attempt %d/3 failed: %s", attempt + 1, retry_err)
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        else:
            logger.error("All challenge POST attempts failed")
            return False

        # Check if we got the rd_challenge cookie
        for cookie in self._client.cookies:
            name = cookie.name if hasattr(cookie, "name") else str(cookie)
            if "challenge" in name.lower() or "rd_" in name.lower():
                logger.info("Challenge completed - %s cookie received", name)
                return True

        logger.warning("Challenge POST succeeded but no challenge cookie received")
        return False

    async def initialize(self) -> bool:
        """Initialize by loading the facebook.com homepage and extracting tokens.

        The logged-out homepage returns HTTP 200, sets real cookies
        (``datr``, ``fr``, ``sb``) and embeds a genuine ``lsd`` token,
        ``__spin_r`` revision and ``hsi`` -- unlike the Ad Library page,
        which now answers curl_cffi with a 403 JS challenge.

        Returns:
            True if initialization succeeded.

        Raises:
            AuthenticationError: If the homepage cannot be loaded or no
                genuine ``lsd`` token can be extracted.  Tokens are never
                fabricated -- a random ``lsd`` only triggers misleading
                "rate limit exceeded" (error 1675004) GraphQL failures.
        """
        import re

        logger.info("Initializing async Meta Ads client...")
        try:
            # Seed only the benign viewport cookies; the server sets the
            # real datr/fr/sb cookies on the homepage response.
            wd = f"{self._fingerprint.viewport_width}x{self._fingerprint.viewport_height}"
            self._client.cookies.set("wd", wd, domain=".facebook.com", path="/")
            self._client.cookies.set(
                "dpr", str(self._fingerprint.dpr),
                domain=".facebook.com", path="/",
            )

            init_headers = dict(self._fingerprint.get_default_headers())
            init_headers["sec-fetch-site"] = "none"

            response = await self._make_request(
                "GET", f"{self.BASE_URL}/", headers=init_headers,
            )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"Failed to load facebook.com homepage (HTTP {response.status_code})"
                )

            html = response.text
            self._tokens = self._extract_tokens(html)
            self._doc_ids = self._extract_doc_ids(html)

            # A genuine lsd is mandatory -- never fabricate one.
            if not self._tokens.get("lsd"):
                raise AuthenticationError(
                    "Could not extract lsd token from facebook.com homepage"
                )

            # jazoest is derived from the genuine lsd.
            if "jazoest" not in self._tokens:
                self._tokens["jazoest"] = self._calculate_jazoest(self._tokens["lsd"])

            # Benign defaults for spin metadata the homepage may omit.
            if "__spin_t" not in self._tokens:
                self._tokens["__spin_t"] = str(int(time.time()))
            if "__spin_b" not in self._tokens:
                self._tokens["__spin_b"] = "trunk"
            if "__rev" not in self._tokens:
                rev_match = re.search(r'"server_revision":(\d+)', html)
                if rev_match:
                    self._tokens["__rev"] = rev_match.group(1)
                    self._tokens["__spin_r"] = rev_match.group(1)
                else:
                    self._tokens["__rev"] = FALLBACK_REV
                    self._tokens["__spin_r"] = FALLBACK_REV

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
                # Rebuild the payload with the freshly mined tokens only --
                # never substitute fallback __dyn/__csr/fb_dtsg values.
                lsd = self._tokens.get("lsd", "")
                payload["lsd"] = lsd
                payload["jazoest"] = self._calculate_jazoest(lsd)
                for key in (
                    "__rev", "__spin_r", "__spin_t", "__spin_b", "__hsi",
                    "__dyn", "__csr", "fb_dtsg", "__hsdp", "__hblp",
                ):
                    if key in self._tokens:
                        payload[key] = self._tokens[key]
                    else:
                        payload.pop(key, None)

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

        except Exception as exc:
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

        Approaches attempted (in order):

        1. **GraphQL page-scoped search** (primary): a targeted search
           filtered by *page_id*, looking for the specific
           ``ad_archive_id`` in the results.

        2. **Ad Library detail page** (best-effort fallback): loads
           ``/ads/library/?id={archive_id}`` and extracts embedded JSON
           from the server-rendered HTML.  The page currently answers
           curl_cffi with a 403 JS challenge, so any non-200 response
           is tolerated and simply skipped.
        """
        if not self._initialized:
            await self.initialize()

        # Approach 1: page-scoped GraphQL search
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
                logger.debug("Approach 1 failed for ad %s: %s", ad_archive_id, exc)

        # Approach 2: detail page (best-effort; may be 403-challenged)
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
            else:
                logger.debug(
                    "Approach 2: detail page returned HTTP %d for ad %s",
                    response.status_code, ad_archive_id,
                )
        except Exception as exc:
            logger.debug("Approach 2 failed for ad %s: %s", ad_archive_id, exc)

        raise NotImplementedError(
            f"Could not retrieve detail data for ad {ad_archive_id}. "
            "All approaches exhausted."
        )

    async def close(self) -> None:
        """Close the underlying async client."""
        await self._close_client()
        self._initialized = False

    async def __aenter__(self) -> AsyncMetaAdsClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
