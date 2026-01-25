"""
Meta Ads Library HTTP Client

Handles session management, token extraction, and GraphQL requests
to the Facebook Ad Library.
"""

import re
import json
import time
import random
import string
import hashlib
import logging
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode, quote
import requests

logger = logging.getLogger(__name__)


class MetaAdsClient:
    """
    HTTP client for Meta Ad Library.

    Manages session state, extracts required tokens from the initial page load,
    and handles GraphQL API requests.
    """

    BASE_URL = "https://www.facebook.com"
    AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"
    GRAPHQL_URL = "https://www.facebook.com/api/graphql/"

    # GraphQL doc_ids (these may change with Facebook updates)
    DOC_ID_SEARCH = "25464068859919530"  # AdLibrarySearchPaginationQuery
    DOC_ID_TYPEAHEAD = "9755915494515334"  # useAdLibraryTypeaheadSuggestionDataSourceQuery

    # Chrome version to use consistently across all headers
    _CHROME_VERSION = "131"
    _CHROME_FULL_VERSION = "131.0.6778.140"
    _USER_AGENT = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{_CHROME_VERSION}.0.0.0 Safari/537.36"

    # Default headers mimicking Chrome browser - needs to look like first visit
    DEFAULT_HEADERS = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "dpr": "1.25",
        "sec-ch-prefers-color-scheme": "light",
        "sec-ch-ua": f'"Google Chrome";v="{_CHROME_VERSION}", "Chromium";v="{_CHROME_VERSION}", "Not_A Brand";v="24"',
        "sec-ch-ua-full-version-list": f'"Google Chrome";v="{_CHROME_FULL_VERSION}", "Chromium";v="{_CHROME_FULL_VERSION}", "Not_A Brand";v="24.0.0.0"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-model": '""',
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"15.0.0"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": _USER_AGENT,
        "viewport-width": "1920",
    }

    GRAPHQL_HEADERS = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.facebook.com",
        "sec-ch-prefers-color-scheme": "light",
        "sec-ch-ua": f'"Google Chrome";v="{_CHROME_VERSION}", "Chromium";v="{_CHROME_VERSION}", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"15.0.0"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": _USER_AGENT,
        "x-asbd-id": "359341",
    }

    def __init__(
        self,
        proxy: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        """
        Initialize the Meta Ads client.

        Args:
            proxy: Proxy string in format "host:port:username:password" or "host:port"
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Session state
        self.session = requests.Session()
        self._tokens: Dict[str, str] = {}
        self._initialized = False
        self._request_counter = 0
        self._init_time: Optional[float] = None
        self._consecutive_errors = 0
        self._max_session_age = 1800  # Re-initialize after 30 minutes

        # Configure proxy
        self._proxy_string = proxy
        self._setup_proxy(proxy)

        # Set default headers
        self.session.headers.update(self.DEFAULT_HEADERS)

    def _setup_proxy(self, proxy: Optional[str]) -> None:
        """Configure proxy from string format host:port:user:pass"""
        if not proxy:
            return

        parts = proxy.split(":")
        if len(parts) == 4:
            host, port, username, password = parts
            proxy_url = f"http://{username}:{password}@{host}:{port}"
        elif len(parts) == 2:
            host, port = parts
            proxy_url = f"http://{host}:{port}"
        else:
            raise ValueError(f"Invalid proxy format: {proxy}. Expected host:port or host:port:user:pass")

        self.session.proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        logger.info(f"Proxy configured: {host}:{port}")

    def _extract_tokens(self, html: str) -> Dict[str, str]:
        """Extract required tokens from the Ad Library HTML page."""
        tokens = {}

        # Extract LSD token (CSRF protection)
        lsd_patterns = [
            r'"LSD",\[\],\{"token":"([^"]+)"\}',
            r'\["LSD",\[\],\{"token":"([^"]+)"',
            r'"lsd":"([^"]+)"',
            r'name="lsd" value="([^"]+)"',
        ]
        for pattern in lsd_patterns:
            match = re.search(pattern, html)
            if match:
                tokens["lsd"] = match.group(1)
                break

        # Extract __rev (build revision)
        rev_patterns = [
            r'"__spin_r":(\d+)',
            r'"server_revision":(\d+)',
            r'"revision":(\d+)',
            r'{"__spin_r":(\d+)',
        ]
        for pattern in rev_patterns:
            match = re.search(pattern, html)
            if match:
                tokens["__rev"] = match.group(1)
                tokens["__spin_r"] = match.group(1)
                break

        # Extract __spin_t (timestamp)
        spin_t_match = re.search(r'"__spin_t":(\d+)', html)
        if spin_t_match:
            tokens["__spin_t"] = spin_t_match.group(1)

        # Extract __spin_b
        spin_b_match = re.search(r'"__spin_b":"([^"]+)"', html)
        if spin_b_match:
            tokens["__spin_b"] = spin_b_match.group(1)

        # Extract __hsi (session ID)
        hsi_match = re.search(r'"hsi":"(\d+)"', html)
        if hsi_match:
            tokens["__hsi"] = hsi_match.group(1)

        # Extract dtsg token if present
        dtsg_match = re.search(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"', html)
        if dtsg_match:
            tokens["fb_dtsg"] = dtsg_match.group(1)

        # Extract __dyn (dynamic modules) - IMPORTANT for avoiding rate limits
        dyn_match = re.search(r'"__dyn":"([^"]+)"', html)
        if dyn_match:
            tokens["__dyn"] = dyn_match.group(1)

        # Extract __csr
        csr_match = re.search(r'"__csr":"([^"]+)"', html)
        if csr_match:
            tokens["__csr"] = csr_match.group(1)

        # Extract __hs (hash)
        hs_match = re.search(r'"__hs":"([^"]+)"', html)
        if hs_match:
            tokens["__hs"] = hs_match.group(1)

        # Extract __hsdp
        hsdp_match = re.search(r'"__hsdp":"([^"]+)"', html)
        if hsdp_match:
            tokens["__hsdp"] = hsdp_match.group(1)

        # Extract __hblp
        hblp_match = re.search(r'"__hblp":"([^"]+)"', html)
        if hblp_match:
            tokens["__hblp"] = hblp_match.group(1)

        # Extract __comet_req
        comet_match = re.search(r'"__comet_req":(\d+)', html)
        if comet_match:
            tokens["__comet_req"] = comet_match.group(1)

        # Extract jazoest - calculate or extract
        jazoest_match = re.search(r'"jazoest["\s:]+(\d+)', html)
        if jazoest_match:
            tokens["jazoest"] = jazoest_match.group(1)

        logger.debug(f"Extracted tokens: {list(tokens.keys())}")
        return tokens

    def _generate_session_id(self) -> str:
        """Generate a random session ID in UUID format."""
        import uuid
        return str(uuid.uuid4())

    def _generate_collation_token(self) -> str:
        """Generate a collation token for search requests."""
        import uuid
        return str(uuid.uuid4())

    def _generate_datr(self) -> str:
        """Generate a datr cookie value (device fingerprint)."""
        # datr is a base64-like encoded value
        chars = string.ascii_letters + string.digits + "_-"
        return "".join(random.choices(chars, k=24))

    def _is_session_stale(self) -> bool:
        """Check if the current session is too old and needs refresh."""
        if not self._init_time:
            return True
        return (time.time() - self._init_time) > self._max_session_age

    def _refresh_session(self) -> bool:
        """
        Re-initialize the session when cookies/tokens become stale.
        Closes the old session and creates a fresh one.
        """
        logger.info("Refreshing session (cookies/tokens may be stale)...")
        # Close old session
        self.session.close()
        # Create new session
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self._tokens = {}
        self._initialized = False
        self._request_counter = 0
        self._consecutive_errors = 0
        # Re-configure proxy if it was set
        if hasattr(self, '_proxy_string'):
            self._setup_proxy(self._proxy_string)
        return self.initialize()

    def _handle_challenge(self, response: requests.Response) -> bool:
        """
        Handle Facebook's JavaScript verification challenge.

        Facebook returns a page with a JS challenge that POSTs to /__rd_verify_*
        and sets an rd_challenge cookie.

        Returns:
            True if challenge was handled successfully
        """
        text = response.text

        # Look for the challenge verification URL
        # Pattern: fetch('/__rd_verify_XXXXX?challenge=N'
        match = re.search(r"fetch\('(/__rd_verify_[^']+)'", text)

        if not match:
            logger.debug("No challenge URL found in response")
            return False

        challenge_path = match.group(1)
        challenge_url = f"{self.BASE_URL}{challenge_path}"

        logger.info(f"Handling verification challenge: {challenge_path[:50]}...")

        try:
            # POST to the challenge endpoint
            challenge_headers = {
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "content-type": "text/plain;charset=UTF-8",
                "origin": "https://www.facebook.com",
                "referer": response.url,
                "sec-ch-ua": self.DEFAULT_HEADERS.get("sec-ch-ua"),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": self.DEFAULT_HEADERS.get("user-agent"),
            }

            challenge_response = self.session.post(
                challenge_url,
                headers=challenge_headers,
                timeout=self.timeout,
            )

            logger.debug(f"Challenge response status: {challenge_response.status_code}")
            logger.debug(f"Challenge cookies: {list(self.session.cookies.keys())}")

            # Check if we got the rd_challenge cookie
            if "rd_challenge" in self.session.cookies:
                logger.info("Challenge completed - rd_challenge cookie received")
                return True
            else:
                # Sometimes the cookie is set with different name patterns
                for cookie in self.session.cookies:
                    if "challenge" in cookie.name.lower() or "rd_" in cookie.name.lower():
                        logger.info(f"Challenge completed - {cookie.name} cookie received")
                        return True

            logger.warning("Challenge POST completed but no challenge cookie received")
            return True  # Still try to proceed

        except Exception as e:
            logger.error(f"Failed to complete challenge: {e}")
            return False

    def initialize(self) -> bool:
        """
        Initialize the client by loading the Ad Library page and extracting tokens.

        Returns:
            True if initialization was successful
        """
        logger.info("Initializing Meta Ads client...")

        try:
            # Step 1: Generate initial cookies that Facebook expects
            # The datr cookie is a device fingerprint - we generate one
            datr = self._generate_datr()
            self.session.cookies.set("datr", datr, domain=".facebook.com", path="/")
            self.session.cookies.set("wd", "1920x1080", domain=".facebook.com", path="/")
            self.session.cookies.set("dpr", "1.25", domain=".facebook.com", path="/")

            logger.debug(f"Set initial cookies: datr={datr[:8]}...")

            # Step 2: Load the Ad Library page with minimal parameters
            # Using sec-fetch-site: none to appear as direct navigation
            init_headers = dict(self.DEFAULT_HEADERS)
            init_headers["sec-fetch-site"] = "none"

            response = self._make_request(
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

            logger.debug(f"Initial request status: {response.status_code}")
            logger.debug(f"Response cookies: {list(self.session.cookies.keys())}")

            # Check if we got a challenge response (403 with challenge script)
            if response.status_code == 403 or "/__rd_verify_" in response.text:
                logger.info("Got verification challenge, attempting to solve...")

                if self._handle_challenge(response):
                    # Wait a moment then retry
                    time.sleep(1.5)

                    init_headers["sec-fetch-site"] = "same-origin"
                    init_headers["referer"] = "https://www.facebook.com/"

                    response = self._make_request(
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
                    logger.debug(f"Post-challenge attempt status: {response.status_code}")

                    # If still getting challenge, try once more
                    if response.status_code == 403 or "/__rd_verify_" in response.text:
                        logger.info("Got another challenge, retrying...")
                        if self._handle_challenge(response):
                            time.sleep(1.5)
                            response = self._make_request(
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
                            logger.debug(f"Second post-challenge attempt status: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"Failed to load Ad Library page: {response.status_code}")
                # Log a snippet of the response for debugging
                logger.debug(f"Response preview: {response.text[:500]}")
                return False

            # Extract tokens from HTML
            self._tokens = self._extract_tokens(response.text)

            logger.debug(f"Extracted tokens: {list(self._tokens.keys())}")

            # Verify we got the essential tokens
            if "lsd" not in self._tokens:
                logger.warning("Could not extract LSD token - trying to find in response...")
                # Try alternative extraction
                lsd_match = re.search(r'"token":"([^"]{20,})"', response.text)
                if lsd_match:
                    self._tokens["lsd"] = lsd_match.group(1)
                    logger.info("Found LSD token via alternative pattern")

            # Generate fallback values for missing tokens
            if "__spin_t" not in self._tokens:
                self._tokens["__spin_t"] = str(int(time.time()))

            if "__spin_b" not in self._tokens:
                self._tokens["__spin_b"] = "trunk"

            if "__rev" not in self._tokens:
                # Extract from page if possible, otherwise use a recent known value
                rev_match = re.search(r'"server_revision":(\d+)', response.text)
                if rev_match:
                    self._tokens["__rev"] = rev_match.group(1)
                else:
                    self._tokens["__rev"] = "1032373751"

            self._initialized = True
            self._init_time = time.time()
            self._consecutive_errors = 0
            logger.info("Client initialized successfully")
            logger.info(f"Tokens available: {list(self._tokens.keys())}")

            # Add a small delay before first GraphQL request to appear more human
            time.sleep(random.uniform(1.5, 3.0))

            return True

        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        **kwargs,
    ) -> requests.Response:
        """Make an HTTP request with retry logic."""
        merged_headers = dict(self.session.headers)
        if headers:
            merged_headers.update(headers)

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                    timeout=self.timeout,
                    **kwargs,
                )

                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Rate limited. Waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
                    continue

                return response

            except requests.exceptions.RequestException as e:
                last_exception = e
                wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)

        raise last_exception or Exception("Request failed after all retries")

    def _make_graphql_request(
        self,
        payload: Dict[str, str],
        headers: Dict[str, str],
    ) -> requests.Response:
        """
        Make a GraphQL request with automatic session refresh on auth failures.

        If a 403 is received (expired cookies/tokens), refreshes the session
        and rebuilds the payload with new tokens, then retries once.
        """
        response = self._make_request("POST", self.GRAPHQL_URL, data=payload, headers=headers)

        if response.status_code == 403:
            logger.warning("Got 403 on GraphQL request - session likely expired, refreshing...")
            if self._refresh_session():
                # Rebuild payload with new tokens (lsd, jazoest, etc. changed)
                # Update the lsd-dependent fields
                lsd = self._tokens.get("lsd", "")
                payload["lsd"] = lsd
                payload["jazoest"] = self._calculate_jazoest(lsd)
                payload["__rev"] = self._tokens.get("__rev", "1032373751")
                payload["__spin_r"] = self._tokens.get("__spin_r", "1032373751")
                payload["__spin_t"] = self._tokens.get("__spin_t", str(int(time.time())))
                payload["__spin_b"] = self._tokens.get("__spin_b", "trunk")
                payload["__hsi"] = self._tokens.get("__hsi", str(int(time.time() * 1000)))
                payload["__dyn"] = self._tokens.get("__dyn", self.FALLBACK_DYN)
                payload["__csr"] = self._tokens.get("__csr", self.FALLBACK_CSR)
                if "__hsdp" in self._tokens:
                    payload["__hsdp"] = self._tokens["__hsdp"]
                if "__hblp" in self._tokens:
                    payload["__hblp"] = self._tokens["__hblp"]

                headers["x-fb-lsd"] = lsd
                response = self._make_request("POST", self.GRAPHQL_URL, data=payload, headers=headers)
            else:
                logger.error("Session refresh failed, returning 403 response")

        return response

    # Fallback values extracted from known working requests
    # These are used when we can't extract fresh values from the page
    FALLBACK_DYN = "7xeUmwlECdwn8K2Wmh0no6u5U4e1Fx-ewSAwHwNw9G2S2q0_EtxG4o0B-qbwgE1EEb87C1xwEwgo9oO0n24oaEd86a3a1YwBgao6C0Mo6i588Etw8WfK1LwPxe2GewbCXwJwmE2eUlwhE2Lw6OyES0gq0K-1LwqobU3Cwr86C1nwf6Eb87u1rwGwto461ww"
    FALLBACK_CSR = "gjSxK8GXhkbjAmy4j8gBkiHG8FVCIJBHjpXUrByK5HxuquEyUK5Emz8Oaw9G3S5UoyUK588E4a2W0C8eEcE4S2m12wg8O1fwau1IwiEow9qE5S3KUK320g-1fDw49w2v80PS07XU0ptw2Ao05Ey02zC0aFw0hIQ00BPo06XK6k00CSo072W09xw4jw"

    def _calculate_jazoest(self, lsd: str) -> str:
        """Calculate jazoest value from lsd token."""
        # jazoest is calculated as 2 + sum of char codes of lsd
        if not lsd:
            return "2893"
        total = sum(ord(c) for c in lsd)
        return str(2 + total)

    def _build_graphql_payload(
        self,
        doc_id: str,
        variables: Dict[str, Any],
        friendly_name: str,
    ) -> Dict[str, str]:
        """Build the form data payload for a GraphQL request."""
        self._request_counter += 1

        lsd = self._tokens.get("lsd", "")
        jazoest = self._tokens.get("jazoest") or self._calculate_jazoest(lsd)

        # Base payload with extracted tokens - matching Facebook's expected format
        payload = {
            "av": "0",
            "__aaid": "0",
            "__user": "0",
            "__a": "1",
            "__req": self._encode_request_id(self._request_counter),
            "__hs": self._tokens.get("__hs", "20476.HYP:comet_plat_default_pkg.2.1...0"),
            "dpr": "1",
            "__ccg": "GOOD",
            "__rev": self._tokens.get("__rev", "1032373751"),
            "__s": self._generate_short_id(),
            "__hsi": self._tokens.get("__hsi", str(int(time.time() * 1000))),
            "__comet_req": self._tokens.get("__comet_req", "94"),
            "lsd": lsd,
            "jazoest": jazoest,
            "__spin_r": self._tokens.get("__spin_r", "1032373751"),
            "__spin_b": self._tokens.get("__spin_b", "trunk"),
            "__spin_t": self._tokens.get("__spin_t", str(int(time.time()))),
            "__jssesw": "1",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly_name,
            "server_timestamps": "true",
            "variables": json.dumps(variables, separators=(",", ":")),
            "doc_id": doc_id,
        }

        # Add all extracted tokens - these are important for avoiding rate limits
        # Use fallback values if not extracted
        payload["__dyn"] = self._tokens.get("__dyn", self.FALLBACK_DYN)
        payload["__csr"] = self._tokens.get("__csr", self.FALLBACK_CSR)

        if "__hsdp" in self._tokens:
            payload["__hsdp"] = self._tokens["__hsdp"]
        if "__hblp" in self._tokens:
            payload["__hblp"] = self._tokens["__hblp"]

        logger.debug(f"Payload tokens: lsd={lsd[:10]}..., jazoest={jazoest}, __dyn present={bool(payload.get('__dyn'))}")

        return payload

    def _encode_request_id(self, counter: int) -> str:
        """Encode the request counter as a base-36 string."""
        if counter < 10:
            return str(counter)
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        result = ""
        while counter:
            result = chars[counter % 36] + result
            counter //= 36
        return result

    def _generate_short_id(self) -> str:
        """Generate a short session tracking ID."""
        import random
        import string
        parts = []
        for _ in range(3):
            part = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            parts.append(part)
        return ":".join(parts)

    def search_ads(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = "ALL",
        active_status: str = "ACTIVE",
        media_type: str = "ALL",
        search_type: str = "KEYWORD_EXACT_PHRASE",
        page_ids: Optional[list] = None,
        cursor: Optional[str] = None,
        first: int = 10,
        sort_direction: str = "DESCENDING",
        sort_mode: str = "SORT_BY_TOTAL_IMPRESSIONS",
        session_id: Optional[str] = None,
        collation_token: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Search for ads in the Meta Ad Library.

        Args:
            query: Search query string
            country: Country code (e.g., "US", "EG")
            ad_type: Type of ads - ALL, POLITICAL_AND_ISSUE_ADS, HOUSING_ADS, etc.
            active_status: ACTIVE, INACTIVE, or ALL
            media_type: ALL, IMAGE, VIDEO, MEME, NONE
            search_type: KEYWORD_UNORDERED, KEYWORD_EXACT_PHRASE, PAGE
            page_ids: List of page IDs to filter by
            cursor: Pagination cursor for next page
            first: Number of results per page (max ~30)
            sort_direction: ASCENDING or DESCENDING
            sort_mode: SORT_BY_TOTAL_IMPRESSIONS or None (omit for default/relevancy)
            session_id: Search session ID (reuse across pagination pages)
            collation_token: Collation token (reuse across pagination pages)

        Returns:
            Tuple of (response data dict, next cursor or None)
        """
        if not self._initialized:
            if not self.initialize():
                raise RuntimeError("Failed to initialize client")

        # Proactively refresh stale sessions
        if self._is_session_stale():
            logger.info("Session is stale, refreshing before request...")
            if not self._refresh_session():
                raise RuntimeError("Failed to refresh stale session")

        # Use provided IDs or generate new ones
        session_id = session_id or self._generate_session_id()
        collation_token = collation_token or self._generate_collation_token()

        # Build variables - exact format for AdLibrarySearchPaginationQuery
        # IMPORTANT: Use uppercase for activeStatus/mediaType, empty arrays not null
        variables = {
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
            "v": "fbece7",
            "viewAllPageID": "0",
        }

        # Only include sortData for SORT_BY_TOTAL_IMPRESSIONS.
        # Omitting sortData gives default server-side sort (relevancy).
        # Other sort mode strings cause noncoercible_variable_value errors.
        if sort_mode == "SORT_BY_TOTAL_IMPRESSIONS":
            variables["sortData"] = {
                "direction": sort_direction,
                "mode": sort_mode,
            }

        # Add cursor if provided (for pagination)
        if cursor:
            variables["cursor"] = cursor

        logger.debug(f"GraphQL variables: {json.dumps(variables, indent=2)}")

        # Build payload for search/pagination query
        payload = self._build_graphql_payload(
            doc_id=self.DOC_ID_SEARCH,
            variables=variables,
            friendly_name="AdLibrarySearchPaginationQuery",
        )

        # Build headers - map ad_type to URL-friendly param
        ad_type_url = {
            "ALL": "all",
            "POLITICAL_AND_ISSUE_ADS": "political_and_issue_ads",
            "HOUSING_ADS": "housing",
            "EMPLOYMENT_ADS": "employment",
            "CREDIT_ADS": "credit",
        }.get(ad_type, "all")

        headers = dict(self.GRAPHQL_HEADERS)
        headers["x-fb-friendly-name"] = "AdLibrarySearchPaginationQuery"
        headers["x-fb-lsd"] = self._tokens.get("lsd", "")
        headers["referer"] = f"{self.AD_LIBRARY_URL}?active_status={active_status.lower()}&ad_type={ad_type_url}&country={country}&q={quote(query)}"

        # Make request with session refresh on auth failure
        response = self._make_graphql_request(payload, headers)

        if response.status_code != 200:
            logger.error(f"GraphQL request failed: {response.status_code}")
            logger.debug(f"Response: {response.text[:500]}")
            raise Exception(f"GraphQL request failed with status {response.status_code}")

        # Parse response
        try:
            text = response.text
            if text.startswith("for (;;);"):
                text = text[9:]

            logger.debug(f"GraphQL response preview: {text[:1000]}")

            data = json.loads(text)

            logger.debug(f"Response keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")

            # Check for errors
            if "errors" in data:
                errors = data.get("errors", [])
                for error in errors:
                    error_code = error.get("code")
                    error_msg = error.get("message", "Unknown error")

                    if error_code == 1675004 or "rate limit" in error_msg.lower():
                        logger.warning(f"Rate limited: {error_msg}. Waiting before retry...")
                        self._consecutive_errors += 1
                        time.sleep(5 + random.uniform(0, 3))
                        return {"ads": [], "page_info": {}, "rate_limited": True, "error": error_msg}, None

                    # Session/auth errors - trigger refresh
                    if error_code in (1357004, 1357001) or "session" in error_msg.lower():
                        logger.warning(f"Session error: {error_msg}. Will refresh on next request.")
                        self._consecutive_errors += 1
                        if self._consecutive_errors >= 2:
                            self._refresh_session()
                        return {"ads": [], "page_info": {}, "session_expired": True, "error": error_msg}, None

                    logger.error(f"GraphQL error: {error_msg} (code: {error_code})")

                if not data.get("data"):
                    return {"ads": [], "page_info": {}, "error": str(errors)}, None

            # Success - reset error counter
            self._consecutive_errors = 0
            return self._parse_search_response(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response: {e}")
            logger.debug(f"Response text: {response.text[:500]}")
            raise

    def _parse_search_response(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
        """Parse the GraphQL search response and extract ads and pagination info."""
        # Navigate the nested structure
        # Response structure: data -> ad_library_main -> search_results_connection
        try:
            results = (
                data.get("data", {})
                .get("ad_library_main", {})
                .get("search_results_connection", {})
            )

            # Alternative structure
            if not results:
                results = (
                    data.get("data", {})
                    .get("adLibraryMain", {})
                    .get("searchResultsConnection", {})
                )

            # Another alternative
            if not results:
                results = data.get("data", {})

            edges = results.get("edges", [])
            page_info = results.get("page_info", {}) or results.get("pageInfo", {})

            next_cursor = None
            if page_info.get("has_next_page") or page_info.get("hasNextPage"):
                next_cursor = page_info.get("end_cursor") or page_info.get("endCursor")

            # Extract ad nodes - structure is edges[].node.collated_results[]
            ads = []
            for edge in edges:
                node = edge.get("node", edge)
                if node:
                    # The actual ad data is in collated_results
                    collated = node.get("collated_results", [])
                    for ad_data in collated:
                        # Flatten the structure for easier processing
                        # Move snapshot fields up to top level
                        snapshot = ad_data.get("snapshot", {})
                        flattened = {
                            "ad_archive_id": ad_data.get("ad_archive_id"),
                            "collation_count": ad_data.get("collation_count"),
                            "collation_id": ad_data.get("collation_id"),
                            "page_id": ad_data.get("page_id"),
                            **snapshot,  # Include all snapshot fields
                        }
                        ads.append(flattened)

            return {"ads": ads, "page_info": page_info, "raw": data}, next_cursor

        except Exception as e:
            logger.error(f"Failed to parse search response: {e}")
            return {"ads": [], "page_info": {}, "raw": data, "error": str(e)}, None

    def get_ad_details(self, ad_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific ad.

        Note: This may require a different doc_id or endpoint.
        """
        # This would require reverse engineering another endpoint
        raise NotImplementedError("Individual ad details endpoint not yet implemented")

    def close(self) -> None:
        """Close the session and cleanup resources."""
        self.session.close()
        self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
