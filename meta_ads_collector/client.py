"""
Meta Ads Library HTTP Client

Handles session management, token extraction, and GraphQL requests
to the Facebook Ad Library.
"""

import json
import logging
import random
import re
import string
import time
from typing import Any, Optional, Union
from urllib.parse import quote

from curl_cffi.requests import Session as CffiSession
from curl_cffi.requests.exceptions import RequestException as CffiRequestException

from .constants import (
    CHROME_FULL_VERSION,
    CHROME_VERSION,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT,
    DOC_ID_SEARCH,
    DOC_ID_TYPEAHEAD,
    FALLBACK_CSR,
    FALLBACK_DYN,
    FALLBACK_REV,
    MAX_SESSION_AGE,
    USER_AGENT,
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


class MetaAdsClient:
    """
    HTTP client for Meta Ad Library.

    Manages session state, extracts required tokens from the initial page load,
    and handles GraphQL API requests.
    """

    BASE_URL = "https://www.facebook.com"
    AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"
    GRAPHQL_URL = "https://www.facebook.com/api/graphql/"

    # NOTE: These class-level header dicts are NO LONGER used for outgoing
    # requests.  The ``BrowserFingerprint`` instance (``self._fingerprint``)
    # generates randomized, internally-consistent headers via
    # ``get_default_headers()`` and ``get_graphql_headers()``.
    #
    # They are retained here as **documentation** of the expected header
    # structure so that developers can see at a glance which headers
    # Facebook expects for page-load and GraphQL requests.
    DEFAULT_HEADERS = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "dpr": "1.25",
        "sec-ch-prefers-color-scheme": "light",
        "sec-ch-ua": (
            f'"Google Chrome";v="{CHROME_VERSION}", '
            f'"Chromium";v="{CHROME_VERSION}", "Not_A Brand";v="24"'
        ),
        "sec-ch-ua-full-version-list": (
            f'"Google Chrome";v="{CHROME_FULL_VERSION}", '
            f'"Chromium";v="{CHROME_FULL_VERSION}", '
            '"Not_A Brand";v="24.0.0.0"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-model": '""',
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"15.0.0"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": USER_AGENT,
        "viewport-width": "1920",
    }

    GRAPHQL_HEADERS = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.facebook.com",
        "sec-ch-prefers-color-scheme": "light",
        "sec-ch-ua": f'"Google Chrome";v="{CHROME_VERSION}", "Chromium";v="{CHROME_VERSION}", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"15.0.0"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": USER_AGENT,
        "x-asbd-id": "359341",
    }

    def __init__(
        self,
        proxy: Optional[Union[str, list[str], ProxyPool]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        max_refresh_attempts: int = 3,
    ):
        """
        Initialize the Meta Ads client.

        Args:
            proxy: Proxy configuration. Accepts:
                - A single proxy string (``"host:port"`` or
                  ``"host:port:user:pass"``)
                - A list of proxy strings (creates a ProxyPool
                  automatically)
                - A :class:`ProxyPool` instance for full control
                - ``None`` for direct connections
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries (exponential backoff)
            max_refresh_attempts: Max consecutive session refresh failures
                before raising SessionExpiredError
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_refresh_attempts = max_refresh_attempts

        # Generate a randomised browser fingerprint for this session
        self._fingerprint: BrowserFingerprint = generate_fingerprint()

        # Session state -- curl_cffi provides Chrome-like TLS fingerprints
        self.session: Any = CffiSession(impersonate="chrome")
        logger.debug("Using curl_cffi session with Chrome TLS impersonation")
        self._tokens: dict[str, str] = {}
        self._doc_ids: dict[str, str] = {}
        self._initialized = False
        self._request_counter = 0
        self._init_time: Optional[float] = None
        self._consecutive_errors = 0
        self._consecutive_refresh_failures = 0
        self._max_session_age = MAX_SESSION_AGE

        # Configure proxy / proxy pool
        self._proxy_pool: Optional[ProxyPool] = None
        self._proxy_string: Optional[str] = None
        self._current_proxy: Optional[str] = None

        if isinstance(proxy, ProxyPool):
            self._proxy_pool = proxy
        elif isinstance(proxy, list):
            self._proxy_pool = ProxyPool(proxy)
        elif isinstance(proxy, str):
            self._proxy_string = proxy
            self._setup_proxy(proxy)
        # None => no proxy, nothing to do

        # Set default headers from the fingerprint
        self.session.headers.update(self._fingerprint.get_default_headers())

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
            raise ProxyError(f"Invalid proxy format: {proxy!r}. Expected host:port or host:port:user:pass")

        self.session.proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        logger.info(f"Proxy configured: {host}:{port}")

    def _extract_tokens(self, html: str) -> dict[str, str]:
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
        hsi_match = re.search(r'"__hsi":"(\d+)"', html)
        if not hsi_match:
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

        # Extract the "v" API version parameter (used in search variables)
        v_match = re.search(r'"v"\s*:\s*"([a-f0-9]{4,10})"', html)
        if v_match:
            tokens["v"] = v_match.group(1)

        # Extract x-asbd-id (anti-bot defense ID)
        asbd_match = re.search(r'"asbd_id"\s*:\s*"?(\d+)"?', html)
        if not asbd_match:
            asbd_match = re.search(r'x-asbd-id["\s:]+(\d+)', html)
        if asbd_match:
            tokens["x-asbd-id"] = asbd_match.group(1)

        logger.debug(f"Extracted tokens: {list(tokens.keys())}")
        return tokens

    def _extract_doc_ids(self, html: Optional[str]) -> dict[str, str]:
        """Extract GraphQL document IDs from the Ad Library page HTML.

        Attempts multiple regex patterns to find doc_id values from:
        - Relay query registrations
        - Query name strings paired with numeric IDs
        - Bundled JavaScript modules

        If extraction fails, returns an empty dict so callers can fall
        back to hardcoded values.

        Args:
            html: The raw HTML of the Ad Library page.

        Returns:
            Dict mapping query names to doc_id strings.
        """
        if not html:
            logger.debug("No HTML provided for doc_id extraction")
            return {}

        doc_ids: dict[str, str] = {}

        # Pattern 1: __d("AdLibrary...Query...") style with nearby numeric ID
        # e.g., __d("AdLibrarySearchPaginationQuery_foobar",[],{}) ... "12345678901234"
        pattern1_matches = re.findall(
            r'__d\("(AdLibrary\w+Query)[^"]*"[^)]*\).*?["\'](\d{10,20})["\']',
            html,
        )
        for name, doc_id in pattern1_matches:
            doc_ids[name] = doc_id
            logger.debug("Pattern 1 extracted %s: %s", name, doc_id)

        # Pattern 2: "queryID":"<number>" near "AdLibrary...Query"
        # e.g., "name":"AdLibrarySearchPaginationQuery",...,"queryID":"123456"
        pattern2_matches = re.findall(
            r'"(?:name|operationName)"\s*:\s*"(AdLibrary\w+Query)"'
            r'[^}]{0,200}'
            r'"(?:queryID|id|doc_id)"\s*:\s*"(\d{10,20})"',
            html,
        )
        for name, doc_id in pattern2_matches:
            if name not in doc_ids:
                doc_ids[name] = doc_id
                logger.debug("Pattern 2 extracted %s: %s", name, doc_id)

        # Pattern 3: reverse order — queryID first, then name
        pattern3_matches = re.findall(
            r'"(?:queryID|id|doc_id)"\s*:\s*"(\d{10,20})"'
            r'[^}]{0,200}'
            r'"(?:name|operationName)"\s*:\s*"(AdLibrary\w+Query)"',
            html,
        )
        for doc_id, name in pattern3_matches:
            if name not in doc_ids:
                doc_ids[name] = doc_id
                logger.debug("Pattern 3 extracted %s: %s", name, doc_id)

        if doc_ids:
            logger.debug("Extracted doc_ids: %s", doc_ids)
        else:
            logger.warning(
                "Dynamic doc_id extraction found no matches in page HTML. "
                "Falling back to hardcoded doc_ids which may be outdated. "
                "If requests fail, the hardcoded values in constants.py "
                "may need updating."
            )

        return doc_ids

    def _verify_tokens(self) -> None:
        """Verify that required tokens are present, generating fallbacks
        for any that could not be extracted from the page HTML.

        No token causes a hard failure -- if extraction didn't find it,
        a plausible value is generated so requests can proceed.
        """
        # LSD -- required for every GraphQL request
        if not self._tokens.get("lsd"):
            self._tokens["lsd"] = self._generate_lsd()
            logger.warning(
                "LSD token not extracted -- generated fallback: %s",
                self._tokens["lsd"][:6] + "...",
            )

        # fb_dtsg -- optional but improves success rates
        if "fb_dtsg" not in self._tokens:
            self._tokens["fb_dtsg"] = self._generate_fb_dtsg()
            logger.debug("fb_dtsg not extracted -- generated fallback")

        # jazoest -- calculated from LSD if not extracted
        if "jazoest" not in self._tokens:
            self._tokens["jazoest"] = self._calculate_jazoest(
                self._tokens["lsd"]
            )
            logger.debug("jazoest not extracted -- calculated from LSD")

        # __hsi -- session identifier, timestamp-based
        if "__hsi" not in self._tokens:
            self._tokens["__hsi"] = str(int(time.time() * 1000))
            logger.debug("__hsi not extracted -- generated from timestamp")

        # __hs -- hash string
        if "__hs" not in self._tokens:
            self._tokens["__hs"] = "20476.HYP:comet_plat_default_pkg.2.1...0"

        # __comet_req -- request counter seed
        if "__comet_req" not in self._tokens:
            self._tokens["__comet_req"] = "94"

        # __dyn / __csr -- rarely in page HTML anymore, use fallbacks
        if "__dyn" not in self._tokens:
            self._tokens["__dyn"] = FALLBACK_DYN
        if "__csr" not in self._tokens:
            self._tokens["__csr"] = FALLBACK_CSR

        # v -- API version hex
        if "v" not in self._tokens:
            self._tokens["v"] = "fbece7"

        # x-asbd-id -- anti-bot defense ID
        if "x-asbd-id" not in self._tokens:
            self._tokens["x-asbd-id"] = "359341"

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
        chars = string.ascii_letters + string.digits + "_-"
        return "".join(random.choices(chars, k=24))

    def _generate_lsd(self) -> str:
        """Generate a random LSD (CSRF) token.

        Facebook's LSD tokens are typically 8--12 character
        alphanumeric strings with mixed case and occasional
        underscores/hyphens.  When extraction fails, a plausible
        random value is generated.
        """
        chars = string.ascii_letters + string.digits + "_-"
        length = random.randint(8, 12)
        return "".join(random.choices(chars, k=length))

    def _generate_fb_dtsg(self) -> str:
        """Generate a random fb_dtsg token.

        The DTSG token is a longer anti-CSRF value, typically
        20--40 characters, Base64-URL-like.
        """
        chars = string.ascii_letters + string.digits + ":_-"
        length = random.randint(20, 40)
        return "".join(random.choices(chars, k=length))

    def _is_session_stale(self) -> bool:
        """Check if the current session is too old and needs refresh."""
        if not self._init_time:
            return True
        return (time.time() - self._init_time) > self._max_session_age

    def _refresh_session(self) -> bool:
        """
        Re-initialize the session when cookies/tokens become stale.
        Closes the old session and creates a fresh one.

        Raises:
            SessionExpiredError: If the maximum number of consecutive
                refresh failures has been exceeded.

        Returns:
            True if the refresh succeeded.
        """
        # Guard against infinite refresh loops
        if self._consecutive_refresh_failures >= self.max_refresh_attempts:
            raise SessionExpiredError(
                f"Session refresh failed {self._consecutive_refresh_failures} "
                f"consecutive times (max {self.max_refresh_attempts}). "
                "The Ad Library may be blocking this client."
            )

        logger.info("Refreshing session (cookies/tokens may be stale)...")
        # Close old session
        self.session.close()
        # Generate a fresh fingerprint for the new session
        self._fingerprint = generate_fingerprint()
        # Create new session with Chrome TLS impersonation
        self.session = CffiSession(impersonate="chrome")
        self.session.headers.update(self._fingerprint.get_default_headers())
        self._tokens = {}
        self._initialized = False
        self._request_counter = 0
        self._consecutive_errors = 0
        # Re-configure proxy if it was set (single-proxy mode)
        if self._proxy_string:
            self._setup_proxy(self._proxy_string)
        # Proxy pool is re-applied per-request in _make_request
        try:
            result = self.initialize()
            if result:
                self._consecutive_refresh_failures = 0
            else:
                self._consecutive_refresh_failures += 1
            return result
        except (AuthenticationError, MetaAdsError):
            self._consecutive_refresh_failures += 1
            logger.warning(
                "Session refresh failed (%d/%d)",
                self._consecutive_refresh_failures,
                self.max_refresh_attempts,
            )
            return False

    def _handle_challenge(self, response: Any) -> bool:
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
            # Real browsers send fetch(url, {method:'POST'}) with no body
            # and no Content-Type header -- do NOT set content-type here.
            challenge_headers = {
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "origin": "https://www.facebook.com",
                "referer": response.url,
                "sec-ch-ua": self._fingerprint.sec_ch_ua,
                "sec-ch-ua-mobile": self._fingerprint.sec_ch_ua_mobile,
                "sec-ch-ua-platform": self._fingerprint.sec_ch_ua_platform,
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": self._fingerprint.user_agent,
            }

            # Retry the challenge POST up to 3 times (connection can be flaky)
            challenge_response = None
            for attempt in range(3):
                try:
                    challenge_response = self.session.post(
                        challenge_url,
                        headers=challenge_headers,
                        timeout=self.timeout,
                    )
                    break
                except CffiRequestException as retry_err:
                    logger.warning(
                        f"Challenge POST attempt {attempt + 1}/3 failed: {retry_err}"
                    )
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))

            if challenge_response is None:
                logger.error("All challenge POST attempts failed")
                return False

            logger.debug(f"Challenge response status: {challenge_response.status_code}")
            logger.debug(f"Challenge cookies: {list(self.session.cookies.keys())}")

            # Check if we got the rd_challenge cookie
            if "rd_challenge" in self.session.cookies:
                logger.info("Challenge completed - rd_challenge cookie received")
                return True
            else:
                # Sometimes the cookie is set with different name patterns.
                # Cookie jars may yield Cookie objects (.name) or plain
                # strings, so normalise to string before checking.
                for cookie in self.session.cookies:
                    name = cookie.name if hasattr(cookie, "name") else str(cookie)
                    if "challenge" in name.lower() or "rd_" in name.lower():
                        logger.info(f"Challenge completed - {name} cookie received")
                        return True

            logger.warning("Challenge POST completed but no challenge cookie received")
            return False

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
            wd = f"{self._fingerprint.viewport_width}x{self._fingerprint.viewport_height}"
            self.session.cookies.set("wd", wd, domain=".facebook.com", path="/")
            self.session.cookies.set("dpr", str(self._fingerprint.dpr), domain=".facebook.com", path="/")

            logger.debug(f"Set initial cookies: datr={datr[:8]}...")

            # Step 2: Load the Ad Library page with minimal parameters
            # Using sec-fetch-site: none to appear as direct navigation
            init_headers = dict(self._fingerprint.get_default_headers())
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
                logger.debug(f"Response preview: {response.text[:500]}")
                raise AuthenticationError(
                    f"Failed to load Ad Library page (HTTP {response.status_code})"
                )

            # Extract tokens from HTML
            self._tokens = self._extract_tokens(response.text)

            # Attempt to extract dynamic doc_ids from the page
            self._doc_ids = self._extract_doc_ids(response.text)

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
                    self._tokens["__rev"] = FALLBACK_REV

            # Verify tokens before proceeding
            self._verify_tokens()

            self._initialized = True
            self._init_time = time.time()
            self._consecutive_errors = 0
            logger.info("Client initialized successfully")
            logger.info(f"Tokens available: {list(self._tokens.keys())}")

            # Add a small delay before first GraphQL request to appear more human
            time.sleep(random.uniform(1.5, 3.0))

            return True

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            raise AuthenticationError(f"Failed to initialize client: {e}") from e

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
        **kwargs: Any,
    ) -> Any:
        """Make an HTTP request with retry logic and proxy rotation."""
        merged_headers = dict(self.session.headers)
        if headers:
            merged_headers.update(headers)

        last_exception: Optional[CffiRequestException] = None

        for attempt in range(self.max_retries):
            # Rotate proxy from pool if available
            proxy_url: Optional[str] = None
            if self._proxy_pool is not None:
                proxy_url = self._proxy_pool.get_next()
                self._current_proxy = proxy_url
                self.session.proxies = self._proxy_pool.get_proxy_dict(  # type: ignore[assignment]
                    proxy_url
                )

            try:
                response = self.session.request(
                    method=method,  # type: ignore[arg-type]
                    url=url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                    timeout=self.timeout,
                    **kwargs,
                )

                # Check for rate limiting
                if response.status_code == 429:
                    if self._proxy_pool and proxy_url:
                        self._proxy_pool.mark_failure(proxy_url)
                    wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Rate limited. Waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
                    continue

                # Mark proxy as successful
                if self._proxy_pool and proxy_url:
                    self._proxy_pool.mark_success(proxy_url)

                return response

            except CffiRequestException as e:
                last_exception = e
                # Mark proxy as failed
                if self._proxy_pool and proxy_url:
                    self._proxy_pool.mark_failure(proxy_url)
                wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)

        raise last_exception or CffiRequestException(
            "Request failed after all retries"
        )

    def _make_graphql_request(
        self,
        payload: dict[str, str],
        headers: dict[str, str],
    ) -> Any:
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
                payload["__rev"] = self._tokens.get("__rev", FALLBACK_REV)
                payload["__spin_r"] = self._tokens.get("__spin_r", FALLBACK_REV)
                payload["__spin_t"] = self._tokens.get("__spin_t", str(int(time.time())))
                payload["__spin_b"] = self._tokens.get("__spin_b", "trunk")
                payload["__hsi"] = self._tokens.get("__hsi", str(int(time.time() * 1000)))
                payload["__dyn"] = self._tokens.get("__dyn", FALLBACK_DYN)
                payload["__csr"] = self._tokens.get("__csr", FALLBACK_CSR)
                if "__hsdp" in self._tokens:
                    payload["__hsdp"] = self._tokens["__hsdp"]
                if "__hblp" in self._tokens:
                    payload["__hblp"] = self._tokens["__hblp"]

                headers["x-fb-lsd"] = lsd
                response = self._make_request("POST", self.GRAPHQL_URL, data=payload, headers=headers)
            else:
                logger.error("Session refresh failed, returning 403 response")

        return response

    # Fallback values are imported from constants module

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
        variables: dict[str, Any],
        friendly_name: str,
    ) -> dict[str, str]:
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
            "__rev": self._tokens.get("__rev", FALLBACK_REV),
            "__s": self._generate_short_id(),
            "__hsi": self._tokens.get("__hsi", str(int(time.time() * 1000))),
            "__comet_req": self._tokens.get("__comet_req", "94"),
            "lsd": lsd,
            "jazoest": jazoest,
            "__spin_r": self._tokens.get("__spin_r", FALLBACK_REV),
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
        payload["__dyn"] = self._tokens.get("__dyn", FALLBACK_DYN)
        payload["__csr"] = self._tokens.get("__csr", FALLBACK_CSR)

        if "__hsdp" in self._tokens:
            payload["__hsdp"] = self._tokens["__hsdp"]
        if "__hblp" in self._tokens:
            payload["__hblp"] = self._tokens["__hblp"]

        logger.debug(
            f"Payload tokens: lsd={lsd[:10]}..., jazoest={jazoest}, "
            f"__dyn present={bool(payload.get('__dyn'))}"
        )

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
        sort_mode: Optional[str] = "SORT_BY_TOTAL_IMPRESSIONS",
        session_id: Optional[str] = None,
        collation_token: Optional[str] = None,
    ) -> tuple[dict[str, Any], Optional[str]]:
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
            self.initialize()

        # Proactively refresh stale sessions
        if self._is_session_stale():
            logger.info("Session is stale, refreshing before request...")
            if not self._refresh_session():
                raise SessionExpiredError("Failed to refresh stale session")

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
            "v": self._tokens.get("v", "fbece7"),
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
        # Use dynamically extracted doc_id if available, else hardcoded fallback
        search_doc_id = self._doc_ids.get(
            "AdLibrarySearchPaginationQuery", DOC_ID_SEARCH
        )
        payload = self._build_graphql_payload(
            doc_id=search_doc_id,
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

        headers = dict(self._fingerprint.get_graphql_headers())
        headers["x-fb-friendly-name"] = "AdLibrarySearchPaginationQuery"
        headers["x-fb-lsd"] = self._tokens.get("lsd", "")
        if "x-asbd-id" in self._tokens:
            headers["x-asbd-id"] = self._tokens["x-asbd-id"]
        headers["referer"] = (
            f"{self.AD_LIBRARY_URL}?active_status={active_status.lower()}"
            f"&ad_type={ad_type_url}&country={country}&q={quote(query)}"
        )

        # Make request with session refresh on auth failure
        response = self._make_graphql_request(payload, headers)

        if response.status_code != 200:
            logger.error(f"GraphQL request failed: {response.status_code}")
            logger.debug(f"Response: {response.text[:500]}")
            raise MetaAdsError(f"GraphQL request failed with status {response.status_code}")

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

            # Success - reset error counters
            self._consecutive_errors = 0
            self._consecutive_refresh_failures = 0
            return self._parse_search_response(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response: {e}")
            logger.debug(f"Response text: {response.text[:500]}")
            raise

    def _parse_search_response(self, data: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
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
                        # Pass through all fields from the collated result.
                        # The live API puts everything (body, title, videos,
                        # images, page_id, etc.) directly on ad_data with no
                        # snapshot wrapper.  Older response formats may nest
                        # creative data under a "snapshot" key, so we overlay
                        # snapshot fields on top to handle both cases.
                        snapshot = ad_data.get("snapshot") or {}
                        flattened = dict(ad_data)
                        if snapshot:
                            # Overlay snapshot fields without overwriting
                            # existing top-level keys from ad_data
                            for key, value in snapshot.items():
                                if key not in flattened:
                                    flattened[key] = value
                        ads.append(flattened)

            return {"ads": ads, "page_info": page_info, "raw": data}, next_cursor

        except Exception as e:
            logger.error(f"Failed to parse search response: {e}")
            return {"ads": [], "page_info": {}, "raw": data, "error": str(e)}, None

    def search_pages(
        self,
        query: str,
        country: str = "US",
    ) -> list[dict[str, Any]]:
        """Search for pages in the Ad Library using the typeahead endpoint.

        Uses the ``DOC_ID_TYPEAHEAD`` GraphQL document to find pages
        matching the given query string.  Results are lightweight page
        summaries suitable for resolving a page name to an ID that can
        then be passed to :meth:`search_ads`.

        Args:
            query: The search string (e.g. a page name like "Coca-Cola").
            country: ISO 3166-1 alpha-2 country code (default ``"US"``).

        Returns:
            A list of raw dicts, one per matching page.  Each dict
            typically contains ``page_id``, ``page_name``,
            ``page_profile_uri``, ``page_profile_picture_url``, etc.
            Returns an empty list on any error or if no matches are found.
        """
        if not self._initialized:
            self.initialize()

        # Proactively refresh stale sessions
        if self._is_session_stale():
            logger.info("Session is stale, refreshing before typeahead request...")
            if not self._refresh_session():
                logger.error("Failed to refresh stale session for typeahead")
                return []

        variables = {
            "queryString": query,
            "country": country,
            "adType": "ALL",
            "isMobile": False,
        }

        # Use dynamically extracted doc_id if available
        typeahead_doc_id = self._doc_ids.get(
            "useAdLibraryTypeaheadSuggestionDataSourceQuery", DOC_ID_TYPEAHEAD
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
            response = self._make_graphql_request(payload, headers)

            if response.status_code != 200:
                logger.error("Typeahead request failed: %d", response.status_code)
                return []

            text = response.text
            if text.startswith("for (;;);"):
                text = text[9:]

            data = json.loads(text)

            if "errors" in data:
                logger.warning("Typeahead response contained errors: %s", data["errors"])
                # Fall through -- data may still have partial results

            return self._parse_typeahead_response(data)

        except (json.JSONDecodeError, CffiRequestException) as exc:
            logger.error("Typeahead search failed: %s", exc)
            return []

    def _parse_typeahead_response(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse the typeahead GraphQL response into page dicts.

        Handles multiple possible response structures gracefully.

        Args:
            data: Parsed JSON response from the typeahead endpoint.

        Returns:
            A list of page dicts.  Empty on failure.
        """
        try:
            # Primary structure: data -> ad_library_main -> typeahead_suggestions
            raw_suggestions = (
                data.get("data", {})
                .get("ad_library_main", {})
                .get("typeahead_suggestions")
            )

            # typeahead_suggestions can be a dict with page_results/keyword_results
            # or a list of page dicts, depending on the API version.
            suggestions: list[dict[str, Any]] = []
            if isinstance(raw_suggestions, dict):
                suggestions = raw_suggestions.get("page_results", [])
            elif isinstance(raw_suggestions, list):
                suggestions = raw_suggestions

            # Alternative camelCase structure
            if not suggestions:
                raw_alt = (
                    data.get("data", {})
                    .get("adLibraryMain", {})
                    .get("typeaheadSuggestions")
                )
                if isinstance(raw_alt, dict):
                    suggestions = raw_alt.get("page_results", []) or raw_alt.get("pageResults", [])
                elif isinstance(raw_alt, list):
                    suggestions = raw_alt

            # Another common pattern: suggestions wrapped in edges/nodes
            if not suggestions:
                edges = (
                    data.get("data", {})
                    .get("ad_library_main", {})
                    .get("typeahead_suggestions_connection", {})
                    .get("edges", [])
                )
                suggestions = [edge.get("node", edge) for edge in edges]

            if not suggestions:
                logger.debug("No typeahead suggestions found in response")
                return []

            pages: list[dict[str, Any]] = []
            for item in suggestions:
                page = {
                    "page_id": str(
                        item.get("page_id", "")
                        or item.get("pageID", "")
                    ),
                    "page_name": (
                        item.get("page_name", "")
                        or item.get("pageName", "")
                        or item.get("name", "")
                    ),
                    "page_profile_uri": (
                        item.get("page_profile_uri")
                        or item.get("pageProfileURI")
                        or item.get("page_url")
                        or ""
                    ),
                    "page_alias": (
                        item.get("page_alias")
                        or item.get("pageAlias")
                    ),
                    "page_logo_url": (
                        item.get("page_profile_picture_url")
                        or item.get("pageProfilePictureURL")
                        or item.get("profile_picture_url")
                        or item.get("image_uri")
                    ),
                    "page_verified": (
                        item.get("is_verified")
                        or item.get("isVerified")
                        or item.get("verification")
                    ),
                    "page_like_count": (
                        item.get("page_like_count")
                        or item.get("pageLikeCount")
                        or item.get("likes")
                    ),
                    "category": (
                        item.get("category")
                        or item.get("page_category")
                    ),
                }
                # Only include pages that have at least a page_id
                if page["page_id"]:
                    pages.append(page)

            logger.debug("Parsed %d pages from typeahead response", len(pages))
            return pages

        except Exception as exc:
            logger.error("Failed to parse typeahead response: %s", exc)
            return []

    def get_ad_details(self, ad_archive_id: str, page_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch detailed ad data beyond what search results provide.

        Approaches attempted (in order):

        1. **Ad Library detail page**: Loads
           ``https://www.facebook.com/ads/library/?id={archive_id}`` and
           extracts embedded JSON data from the server-rendered HTML.
           This page typically contains the full ad snapshot including
           creative content, targeting hints, and demographic data that
           may not be present in search result edges.

        2. **Collated search with page_id**: If *page_id* is supplied,
           performs a targeted search filtered by page ID and looks for
           the specific ``ad_archive_id`` in the results.  This can
           surface extra fields that are only returned when a page-scoped
           query is made.

        Args:
            ad_archive_id: The numeric archive ID of the ad.
            page_id: Optional page ID to enable approach 2.

        Returns:
            A dict of parsed ad detail data.  Keys are a superset of the
            fields available in search results.

        Raises:
            NotImplementedError: If no approach yields useful data.
        """
        if not self._initialized:
            self.initialize()

        # ── Approach 1: Ad Library detail page ────────────────────
        try:
            detail_url = f"{self.AD_LIBRARY_URL}"
            params = {
                "id": ad_archive_id,
                "active_status": "all",
                "ad_type": "all",
                "country": "ALL",
                "media_type": "all",
            }

            headers = dict(self._fingerprint.get_default_headers())
            headers["referer"] = self.AD_LIBRARY_URL
            headers["sec-fetch-site"] = "same-origin"

            response = self._make_request(
                "GET", detail_url, params=params, headers=headers,
            )

            if response.status_code == 200:
                detail_data = self._parse_ad_detail_page(response.text, ad_archive_id)
                if detail_data:
                    logger.debug(
                        "Approach 1 succeeded for ad %s: %d fields",
                        ad_archive_id, len(detail_data),
                    )
                    return detail_data
                logger.debug(
                    "Approach 1: page loaded but no detail data found for ad %s",
                    ad_archive_id,
                )
            else:
                logger.debug(
                    "Approach 1 failed for ad %s: HTTP %d",
                    ad_archive_id, response.status_code,
                )
        except Exception as exc:
            logger.debug("Approach 1 failed for ad %s: %s", ad_archive_id, exc)

        # ── Approach 2: targeted page-scoped search ───────────────
        if page_id:
            try:
                response_data, _ = self.search_ads(
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
                        logger.debug(
                            "Approach 2 succeeded for ad %s via page %s",
                            ad_archive_id, page_id,
                        )
                        return dict(ad_data)
            except Exception as exc:
                logger.debug("Approach 2 failed for ad %s: %s", ad_archive_id, exc)

        raise NotImplementedError(
            f"Could not retrieve detail data for ad {ad_archive_id}. "
            "All approaches exhausted."
        )

    def _parse_ad_detail_page(self, html: str, ad_archive_id: str) -> Optional[dict[str, Any]]:
        """Extract ad detail data embedded in the Ad Library detail page HTML.

        Facebook embeds pre-fetched GraphQL results as JSON blobs within
        ``<script>`` tags.  This method searches for the blob that
        corresponds to the requested *ad_archive_id*.

        Args:
            html: The raw HTML of the detail page.
            ad_archive_id: The archive ID to match.

        Returns:
            Parsed dict of ad data, or ``None`` if extraction fails.
        """
        try:
            # The detail page embeds ad data in a JSON blob within script tags.
            # Look for patterns that contain the ad_archive_id.

            # Pattern 1: Search for ad data in require() / handlePayload() calls
            # These contain serialised GraphQL results.
            import re as _re

            # Find JSON objects that contain our ad_archive_id
            pattern = (
                r'\{[^{}]*"ad_archive_id"\s*:\s*"?' + _re.escape(str(ad_archive_id)) + r'"?[^{}]*\}'
            )
            matches = _re.findall(pattern, html)
            for match_text in matches:
                try:
                    candidate = json.loads(match_text)
                    if isinstance(candidate, dict) and str(candidate.get("ad_archive_id")) == str(ad_archive_id):
                        return dict(candidate)
                except (json.JSONDecodeError, ValueError):
                    continue

            # Pattern 2: Look for larger JSON blobs containing collated_results
            # with our ad ID
            blob_pattern = r'"collated_results"\s*:\s*\[([^\]]{10,})\]'
            blob_matches = _re.finditer(blob_pattern, html)
            for blob_match in blob_matches:
                blob_text = "[" + blob_match.group(1) + "]"
                try:
                    items = json.loads(blob_text)
                    for item in items:
                        if isinstance(item, dict):
                            found_id = str(item.get("ad_archive_id", ""))
                            if found_id == str(ad_archive_id):
                                return dict(item)
                except (json.JSONDecodeError, ValueError):
                    continue

            # Pattern 3: Find any JSON blob that looks like ad snapshot data
            # by searching for the archive ID as a value, then using
            # brace-counting to extract the enclosing JSON object.
            #
            # Limitations: manual brace-counting can be confused by
            # escaped braces inside string values.  We mitigate this by
            # keeping tight search windows and wrapping in try/except.
            snapshot_pattern = (
                r'"(?:adArchiveID|ad_archive_id)"\s*:\s*"?' + _re.escape(str(ad_archive_id)) + r'"?'
            )

            # Limit how far we search into the HTML to avoid runaway
            # parsing on very large pages.
            max_backward = 5000
            max_forward = 10000

            snapshot_match = _re.search(snapshot_pattern, html)
            if snapshot_match:
                try:
                    start = snapshot_match.start()
                    # Walk backwards to find opening brace
                    brace_count = 0
                    obj_start = start
                    search_start = max(start - max_backward, 0)
                    found_open = False
                    for i in range(start, search_start - 1, -1):
                        ch = html[i]
                        if ch == "}":
                            brace_count += 1
                        elif ch == "{":
                            if brace_count == 0:
                                obj_start = i
                                found_open = True
                                break
                            brace_count -= 1

                    if not found_open:
                        # Could not find an opening brace within window
                        logger.debug(
                            "Pattern 3: no opening brace found within "
                            "%d chars before ad_archive_id match",
                            max_backward,
                        )
                    else:
                        # Walk forward to find matching closing brace
                        brace_count = 0
                        obj_end = obj_start
                        search_end = min(obj_start + max_forward, len(html))
                        found_close = False
                        for i in range(obj_start, search_end):
                            ch = html[i]
                            if ch == "{":
                                brace_count += 1
                            elif ch == "}":
                                brace_count -= 1
                                if brace_count == 0:
                                    obj_end = i + 1
                                    found_close = True
                                    break

                        if not found_close:
                            logger.debug(
                                "Pattern 3: no matching closing brace found "
                                "within %d chars after opening brace",
                                max_forward,
                            )
                        else:
                            candidate = json.loads(html[obj_start:obj_end])
                            if isinstance(candidate, dict):
                                return dict(candidate)

                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug(
                        "Pattern 3: JSON parse failed for brace-extracted "
                        "blob: %s", exc,
                    )
                except (IndexError, OverflowError) as exc:
                    logger.debug(
                        "Pattern 3: index error during brace extraction: %s",
                        exc,
                    )

        except Exception as exc:
            logger.debug("Failed to parse ad detail page: %s", exc)

        return None

    def close(self) -> None:
        """Close the session and cleanup resources."""
        self.session.close()
        self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
