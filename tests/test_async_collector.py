"""Tests for meta_ads_collector.async_collector (AsyncMetaAdsCollector)."""

from __future__ import annotations

import importlib.util
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

# Skip all tests if httpx is not installed
HAS_HTTPX = importlib.util.find_spec("httpx") is not None

pytestmark = pytest.mark.skipif(not HAS_HTTPX, reason="httpx not installed")


# ---------------------------------------------------------------------------
# API mirroring
# ---------------------------------------------------------------------------


class TestAPIMirroring:
    """Verify the async collector has the same public method names as sync."""

    def test_has_same_public_methods(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        from meta_ads_collector.collector import MetaAdsCollector

        async_methods = {
            name for name in dir(AsyncMetaAdsCollector)
            if not name.startswith("_")
            and callable(getattr(AsyncMetaAdsCollector, name))
        }

        # The async collector should have at least the core methods
        core_methods = {
            "search", "collect", "collect_to_json", "collect_to_csv",
            "search_pages", "close", "get_stats",
        }
        for method in core_methods:
            assert method in async_methods, f"Missing method: {method}"

        # Verify all sync public methods are also available on async
        sync_public = {
            name for name in dir(MetaAdsCollector)
            if not name.startswith("_")
            and callable(getattr(MetaAdsCollector, name))
        }
        for method in core_methods:
            assert method in sync_public, f"Core method {method} missing from sync"

    def test_search_is_async_generator(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert inspect.isasyncgenfunction(AsyncMetaAdsCollector.search)

    def test_collect_is_coroutine(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert inspect.iscoroutinefunction(AsyncMetaAdsCollector.collect)

    def test_collect_to_json_is_coroutine(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert inspect.iscoroutinefunction(AsyncMetaAdsCollector.collect_to_json)

    def test_collect_to_csv_is_coroutine(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert inspect.iscoroutinefunction(AsyncMetaAdsCollector.collect_to_csv)

    def test_search_pages_is_coroutine(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert inspect.iscoroutinefunction(AsyncMetaAdsCollector.search_pages)

    def test_close_is_coroutine(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert inspect.iscoroutinefunction(AsyncMetaAdsCollector.close)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestAsyncCollectorConstructor:
    def test_has_event_emitter(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        from meta_ads_collector.events import EventEmitter
        collector = AsyncMetaAdsCollector()
        assert isinstance(collector.event_emitter, EventEmitter)

    def test_callbacks_registered(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        from meta_ads_collector.events import AD_COLLECTED

        called = []
        collector = AsyncMetaAdsCollector(
            callbacks={AD_COLLECTED: lambda e: called.append(e)},
        )
        assert collector.event_emitter.has_listeners(AD_COLLECTED)


# ---------------------------------------------------------------------------
# Event emission during search
# ---------------------------------------------------------------------------


class TestAsyncSearchEvents:
    @pytest.mark.asyncio
    async def test_events_emitted_during_search(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        from meta_ads_collector.events import (
            AD_COLLECTED,
            COLLECTION_FINISHED,
            COLLECTION_STARTED,
            PAGE_FETCHED,
            EventEmitter,
        )

        collector = AsyncMetaAdsCollector.__new__(AsyncMetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_ads = AsyncMock(return_value=(
            {
                "ads": [
                    {"ad_archive_id": "ad-1"},
                    {"ad_archive_id": "ad-2"},
                ],
                "page_info": {},
            },
            None,
        ))
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.event_emitter = EventEmitter()
        collector.stats = {
            "requests_made": 0, "ads_collected": 0, "pages_fetched": 0,
            "errors": 0, "start_time": None, "end_time": None,
        }

        events = []
        for et in [COLLECTION_STARTED, AD_COLLECTED, PAGE_FETCHED, COLLECTION_FINISHED]:
            collector.event_emitter.on(et, lambda e: events.append(e.event_type))

        ads = []
        async for ad in collector.search(query="test", country="US"):
            ads.append(ad)

        assert len(ads) == 2
        assert COLLECTION_STARTED in events
        assert COLLECTION_FINISHED in events
        assert AD_COLLECTED in events
        assert PAGE_FETCHED in events

    @pytest.mark.asyncio
    async def test_collect_returns_list(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        from meta_ads_collector.events import EventEmitter

        collector = AsyncMetaAdsCollector.__new__(AsyncMetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_ads = AsyncMock(return_value=(
            {
                "ads": [{"ad_archive_id": "ad-1"}],
                "page_info": {},
            },
            None,
        ))
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.event_emitter = EventEmitter()
        collector.stats = {
            "requests_made": 0, "ads_collected": 0, "pages_fetched": 0,
            "errors": 0, "start_time": None, "end_time": None,
        }

        ads = await collector.collect(query="test", country="US")
        assert len(ads) == 1
        assert ads[0].id == "ad-1"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestAsyncCollectorContextManager:
    @pytest.mark.asyncio
    async def test_async_with(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector

        async with AsyncMetaAdsCollector() as collector:
            assert collector is not None

    @pytest.mark.asyncio
    async def test_close_is_called_on_exit(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector

        collector = AsyncMetaAdsCollector()
        collector.client = MagicMock()
        collector.client.close = AsyncMock()

        async with collector:
            pass

        collector.client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Constants mirroring
# ---------------------------------------------------------------------------


class TestAsyncCollectorConstants:
    def test_ad_type_constants(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert AsyncMetaAdsCollector.AD_TYPE_ALL == "ALL"
        assert AsyncMetaAdsCollector.AD_TYPE_POLITICAL == "POLITICAL_AND_ISSUE_ADS"

    def test_status_constants(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert AsyncMetaAdsCollector.STATUS_ACTIVE == "ACTIVE"

    def test_sort_constants(self):
        from meta_ads_collector.async_collector import AsyncMetaAdsCollector
        assert AsyncMetaAdsCollector.SORT_RELEVANCY is None
        assert AsyncMetaAdsCollector.SORT_IMPRESSIONS == "SORT_BY_TOTAL_IMPRESSIONS"
