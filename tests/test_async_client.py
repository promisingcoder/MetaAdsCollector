"""Tests for meta_ads_collector.async_client (AsyncMetaAdsClient)."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


class TestImportGuard:
    def test_async_client_importable(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert AsyncMetaAdsClient is not None


# ---------------------------------------------------------------------------
# Method signatures
# ---------------------------------------------------------------------------


class TestMethodsAreCoroutines:
    def test_initialize_is_coroutine(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient.initialize)

    def test_search_ads_is_coroutine(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient.search_ads)

    def test_search_pages_is_coroutine(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient.search_pages)

    def test_get_ad_details_is_coroutine(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient.get_ad_details)

    def test_close_is_coroutine(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient.close)


# ---------------------------------------------------------------------------
# Shared logic reuse
# ---------------------------------------------------------------------------


class TestSharedLogicReuse:
    def test_extract_tokens_reuses_sync_logic(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient.__new__(AsyncMetaAdsClient)
        from meta_ads_collector.client import MetaAdsClient
        client._logic = MetaAdsClient.__new__(MetaAdsClient)
        from meta_ads_collector.fingerprint import generate_fingerprint
        client._logic._fingerprint = generate_fingerprint()
        client._logic._tokens = {}
        client._logic._doc_ids = {}
        client._logic._request_counter = 0

        html = '"LSD",[],{"token":"test_lsd_token_12345"}'
        tokens = client._extract_tokens(html)
        assert tokens.get("lsd") == "test_lsd_token_12345"

    def test_calculate_jazoest_reuses_sync_logic(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient.__new__(AsyncMetaAdsClient)
        from meta_ads_collector.client import MetaAdsClient
        client._logic = MetaAdsClient.__new__(MetaAdsClient)

        result = client._calculate_jazoest("abc")
        # Same calculation as sync: 2 + sum of ord('a','b','c') = 2 + 97+98+99 = 296
        assert result == "296"

    def test_parse_search_response_reuses_sync_logic(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient.__new__(AsyncMetaAdsClient)
        from meta_ads_collector.client import MetaAdsClient
        client._logic = MetaAdsClient.__new__(MetaAdsClient)

        data = {
            "data": {
                "ad_library_main": {
                    "search_results_connection": {
                        "edges": [],
                        "page_info": {"has_next_page": False},
                    }
                }
            }
        }
        result, cursor = client._parse_search_response(data)
        assert result["ads"] == []
        assert cursor is None


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        async with AsyncMetaAdsClient() as client:
            assert client is not None
            assert hasattr(client, '_client')
        # After exit, client should be closed
        assert client._initialized is False


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_construction(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        client = AsyncMetaAdsClient()
        assert client._initialized is False
        assert client.timeout == 30
        assert client.max_retries == 3

    def test_construction_with_proxy_string(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        client = AsyncMetaAdsClient(proxy="host:8080")
        assert client._proxy_string == "host:8080"

    def test_construction_with_proxy_list(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        client = AsyncMetaAdsClient(proxy=["host1:8080", "host2:8080"])
        assert client._proxy_pool is not None

    def test_invalid_proxy_format(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.exceptions import ProxyError
        with pytest.raises(ProxyError):
            AsyncMetaAdsClient(proxy="invalid:format:extra")

    def test_format_proxy_url_host_port(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert AsyncMetaAdsClient._format_proxy_url("host:8080") == "http://host:8080"

    def test_format_proxy_url_with_auth(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert (
            AsyncMetaAdsClient._format_proxy_url("host:8080:user:pass")
            == "http://user:pass@host:8080"
        )


# ---------------------------------------------------------------------------
# Session refresh (S5)
# ---------------------------------------------------------------------------


class TestAsyncSessionRefresh:
    """Tests for the _async_refresh_session method added in S5."""

    def test_has_async_refresh_session_method(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient._async_refresh_session)

    def test_has_rebuild_client_method(self):
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        assert inspect.iscoroutinefunction(AsyncMetaAdsClient._rebuild_client)

    @pytest.mark.asyncio
    async def test_refresh_session_resets_state(self):
        """After a successful refresh, tokens and init state are updated."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient()
        client._initialized = True
        client._tokens = {"lsd": "old_token"}
        client._logic._consecutive_refresh_failures = 0

        # Mock _rebuild_client and initialize
        client._rebuild_client = AsyncMock()
        client.initialize = AsyncMock(return_value=True)

        result = await client._async_refresh_session()

        assert result is True
        assert client._logic._consecutive_refresh_failures == 0
        client._rebuild_client.assert_awaited_once()
        client.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_session_increments_failures_on_init_error(self):
        """If initialize() raises, failure counter increments."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.exceptions import AuthenticationError

        client = AsyncMetaAdsClient()
        client._logic._consecutive_refresh_failures = 0

        client._rebuild_client = AsyncMock()
        client.initialize = AsyncMock(
            side_effect=AuthenticationError("token extraction failed"),
        )

        result = await client._async_refresh_session()

        assert result is False
        assert client._logic._consecutive_refresh_failures == 1

    @pytest.mark.asyncio
    async def test_refresh_session_raises_when_max_failures_exceeded(self):
        """SessionExpiredError raised when consecutive failures hit max."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.exceptions import SessionExpiredError

        client = AsyncMetaAdsClient(max_refresh_attempts=3)
        client._logic._consecutive_refresh_failures = 3

        with pytest.raises(SessionExpiredError, match="3 consecutive times"):
            await client._async_refresh_session()

    @pytest.mark.asyncio
    async def test_refresh_generates_new_fingerprint(self):
        """A fresh fingerprint is generated during refresh."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient()
        old_fingerprint = client._fingerprint
        client._logic._consecutive_refresh_failures = 0

        client._rebuild_client = AsyncMock()
        client.initialize = AsyncMock(return_value=True)

        await client._async_refresh_session()

        # Fingerprint should be a new object
        assert client._fingerprint is not old_fingerprint
        assert client._logic._fingerprint is client._fingerprint


# ---------------------------------------------------------------------------
# 403 handling in search_ads (S5)
# ---------------------------------------------------------------------------


class TestAsyncSearchAds403Handling:
    """Tests for 403 response handling in search_ads."""

    @pytest.mark.asyncio
    async def test_search_ads_refreshes_on_403(self):
        """search_ads calls _async_refresh_session on HTTP 403."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient()
        client._initialized = True
        client._init_time = 9999999999.0  # Far future -- not stale
        client._logic._init_time = client._init_time
        client._tokens = {"lsd": "test_lsd"}
        client._doc_ids = {}
        client._logic._tokens = client._tokens
        client._logic._doc_ids = client._doc_ids
        client._logic._request_counter = 0

        # First call returns 403, second returns 200 with valid data
        response_403 = MagicMock()
        response_403.status_code = 403

        response_200 = MagicMock()
        response_200.status_code = 200
        response_200.text = (
            '{"data":{"ad_library_main":{"search_results_connection":'
            '{"edges":[],"page_info":{"has_next_page":false}}}}}'
        )

        call_count = 0

        async def mock_make_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return response_403
            return response_200

        client._make_request = mock_make_request
        client._async_refresh_session = AsyncMock(return_value=True)

        result, cursor = await client.search_ads(query="test")

        client._async_refresh_session.assert_awaited_once()
        assert result["ads"] == []

    @pytest.mark.asyncio
    async def test_search_ads_stale_session_triggers_refresh(self):
        """search_ads proactively refreshes when session is stale."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient

        client = AsyncMetaAdsClient()
        client._initialized = True
        client._init_time = 0.0  # Very old -- definitely stale
        client._logic._init_time = client._init_time
        client._tokens = {"lsd": "test_lsd"}
        client._doc_ids = {}
        client._logic._tokens = client._tokens
        client._logic._doc_ids = client._doc_ids
        client._logic._request_counter = 0

        response_200 = MagicMock()
        response_200.status_code = 200
        response_200.text = (
            '{"data":{"ad_library_main":{"search_results_connection":'
            '{"edges":[],"page_info":{"has_next_page":false}}}}}'
        )

        client._make_request = AsyncMock(return_value=response_200)

        # The refresh should set _init_time to a recent value
        async def mock_refresh():
            client._init_time = 9999999999.0
            client._logic._init_time = client._init_time
            return True

        client._async_refresh_session = mock_refresh

        result, cursor = await client.search_ads(query="test")
        assert result["ads"] == []

    @pytest.mark.asyncio
    async def test_search_ads_stale_session_raises_if_refresh_fails(self):
        """search_ads raises SessionExpiredError if stale refresh fails."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.exceptions import SessionExpiredError

        client = AsyncMetaAdsClient()
        client._initialized = True
        client._init_time = 0.0  # Very stale
        client._logic._init_time = client._init_time
        client._tokens = {"lsd": "test_lsd"}
        client._doc_ids = {}
        client._logic._tokens = client._tokens
        client._logic._doc_ids = client._doc_ids

        client._async_refresh_session = AsyncMock(return_value=False)

        with pytest.raises(SessionExpiredError, match="Failed to refresh"):
            await client.search_ads(query="test")


# ---------------------------------------------------------------------------
# Proxy rotation (S6)
# ---------------------------------------------------------------------------


class TestAsyncProxyRotation:
    """Tests for functional proxy rotation in the async client."""

    @pytest.mark.asyncio
    async def test_proxy_rotation_rebuilds_client(self):
        """When proxy pool returns a new proxy, _rebuild_client is called."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.proxy_pool import ProxyPool

        pool = ProxyPool(["host1:8080", "host2:8080"])
        client = AsyncMetaAdsClient(proxy=pool)
        client._current_proxy = "http://host1:8080"

        # Make pool return a different proxy
        pool.get_next = MagicMock(return_value="http://host2:8080")

        rebuild_calls = []

        async def mock_rebuild(proxy_url=None):
            rebuild_calls.append(proxy_url)
            # Don't actually rebuild -- just record

        client._rebuild_client = mock_rebuild

        # Mock the actual request
        mock_response = MagicMock()
        mock_response.status_code = 200
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_response)
        client._client.headers = {}

        await client._make_request("GET", "http://example.com")

        assert len(rebuild_calls) == 1
        assert rebuild_calls[0] == "http://host2:8080"

    @pytest.mark.asyncio
    async def test_proxy_rotation_no_rebuild_when_same_proxy(self):
        """When pool returns the same proxy, no rebuild occurs."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.proxy_pool import ProxyPool

        pool = ProxyPool(["host1:8080"])
        client = AsyncMetaAdsClient(proxy=pool)
        client._current_proxy = "http://host1:8080"

        pool.get_next = MagicMock(return_value="http://host1:8080")

        client._rebuild_client = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_response)
        client._client.headers = {}

        await client._make_request("GET", "http://example.com")

        client._rebuild_client.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proxy_mark_success_on_successful_request(self):
        """Proxy pool's mark_success is called on success."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.proxy_pool import ProxyPool

        pool = ProxyPool(["host1:8080"])
        client = AsyncMetaAdsClient(proxy=pool)
        client._current_proxy = "http://host1:8080"

        pool.get_next = MagicMock(return_value="http://host1:8080")
        pool.mark_success = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_response)
        client._client.headers = {}

        await client._make_request("GET", "http://example.com")

        pool.mark_success.assert_called_once_with("http://host1:8080")

    @pytest.mark.asyncio
    async def test_proxy_mark_failure_on_429(self):
        """Proxy pool's mark_failure is called on 429 rate limit."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.exceptions import MetaAdsError
        from meta_ads_collector.proxy_pool import ProxyPool

        pool = ProxyPool(["host1:8080"])
        client = AsyncMetaAdsClient(proxy=pool, max_retries=1, retry_delay=0.0)
        client._current_proxy = "http://host1:8080"

        pool.get_next = MagicMock(return_value="http://host1:8080")
        pool.mark_failure = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 429
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_response)
        client._client.headers = {}

        # With max_retries=1, it will 429 once then fall through
        with pytest.raises(MetaAdsError):
            await client._make_request("GET", "http://example.com")

        pool.mark_failure.assert_called_with("http://host1:8080")

    @pytest.mark.asyncio
    async def test_proxy_mark_failure_on_http_error(self):
        """Proxy pool's mark_failure is called on connection error."""
        from meta_ads_collector.async_client import AsyncMetaAdsClient
        from meta_ads_collector.proxy_pool import ProxyPool

        pool = ProxyPool(["host1:8080"])
        client = AsyncMetaAdsClient(proxy=pool, max_retries=1, retry_delay=0.0)
        client._current_proxy = "http://host1:8080"

        pool.get_next = MagicMock(return_value="http://host1:8080")
        pool.mark_failure = MagicMock()

        client._client = MagicMock()
        client._client.request = AsyncMock(
            side_effect=ConnectionError("connection refused"),
        )
        client._client.headers = {}

        with pytest.raises(ConnectionError):
            await client._make_request("GET", "http://example.com")

        pool.mark_failure.assert_called_once_with("http://host1:8080")
