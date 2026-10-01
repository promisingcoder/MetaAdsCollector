"""Regression tests for collection limits, deduplication, and callbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from meta_ads_collector.async_collector import AsyncMetaAdsCollector
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.events import EventEmitter
from meta_ads_collector.exceptions import InvalidParameterError


def _sync_collector(*responses: tuple[dict, str | None]) -> MetaAdsCollector:
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    collector.client.search_ads.side_effect = list(responses)
    collector.rate_limit_delay = 0
    collector.jitter = 0
    collector.event_emitter = EventEmitter()
    collector.stats = {
        "requests_made": 0,
        "ads_collected": 0,
        "pages_fetched": 0,
        "errors": 0,
        "start_time": None,
        "end_time": None,
    }
    return collector


def _async_collector(*responses: tuple[dict, str | None]) -> AsyncMetaAdsCollector:
    collector = AsyncMetaAdsCollector.__new__(AsyncMetaAdsCollector)
    collector.client = MagicMock()
    collector.client.search_ads = AsyncMock(side_effect=list(responses))
    collector.rate_limit_delay = 0
    collector.jitter = 0
    collector.event_emitter = EventEmitter()
    collector.stats = {
        "requests_made": 0,
        "ads_collected": 0,
        "pages_fetched": 0,
        "errors": 0,
        "start_time": None,
        "end_time": None,
    }
    return collector


def _page(*ids: str, cursor: str | None = None) -> tuple[dict, str | None]:
    return {"ads": [{"ad_archive_id": ad_id} for ad_id in ids]}, cursor


def test_zero_max_results_returns_nothing_without_a_request() -> None:
    collector = _sync_collector(_page("ad-1"))

    assert list(collector.search(query="test", max_results=0)) == []
    collector.client.search_ads.assert_not_called()


def test_negative_max_results_is_rejected() -> None:
    collector = _sync_collector(_page("ad-1"))

    with pytest.raises(InvalidParameterError, match="max_results"):
        list(collector.search(query="test", max_results=-1))

    collector.client.search_ads.assert_not_called()


def test_progress_callback_error_propagates_without_dropping_or_tracking_ad() -> None:
    collector = _sync_collector(_page("ad-1"))
    tracker = DeduplicationTracker(mode="memory")

    def fail(_count: int, _total: int) -> None:
        raise RuntimeError("progress callback failed")

    with pytest.raises(RuntimeError, match="progress callback failed"):
        list(collector.search(query="test", dedup_tracker=tracker, progress_callback=fail))

    assert collector.stats["ads_collected"] == 0
    assert tracker.count() == 0
    assert tracker.get_last_collection_time() is None


def test_early_close_persists_yielded_ad_but_not_completed_run(tmp_path) -> None:
    collector = _sync_collector(_page("ad-1", "ad-2", cursor="next"))
    tracker = DeduplicationTracker(mode="persistent", db_path=str(tmp_path / "state.db"))
    iterator = collector.search(query="test", dedup_tracker=tracker)

    first = next(iterator)
    assert tracker.has_seen(first.id)
    iterator.close()

    assert tracker.get_last_collection_time() is None
    tracker.close()

    reopened = DeduplicationTracker(mode="persistent", db_path=str(tmp_path / "state.db"))
    try:
        assert reopened.has_seen(first.id)
        assert reopened.get_last_collection_time() is None
    finally:
        reopened.close()


def test_fully_consumed_sync_search_records_completion_time() -> None:
    collector = _sync_collector(_page("ad-1"))
    tracker = DeduplicationTracker(mode="memory")

    assert [ad.id for ad in collector.search(query="test", dedup_tracker=tracker)] == ["ad-1"]

    assert tracker.has_seen("ad-1")
    assert tracker.get_last_collection_time() is not None


def test_max_results_limit_with_more_pages_is_not_marked_complete() -> None:
    collector = _sync_collector(
        _page("ad-1", cursor="next"),
        _page("ad-2"),
    )
    tracker = DeduplicationTracker(mode="memory")

    assert [ad.id for ad in collector.search(query="test", max_results=1, dedup_tracker=tracker)] == ["ad-1"]

    assert tracker.has_seen("ad-1")
    assert tracker.get_last_collection_time() is None
    collector.client.search_ads.assert_called_once()


@pytest.mark.asyncio
async def test_async_zero_max_results_returns_nothing_without_a_request() -> None:
    collector = _async_collector(_page("ad-1"))

    assert [ad async for ad in collector.search(query="test", max_results=0)] == []
    collector.client.search_ads.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_negative_max_results_is_rejected() -> None:
    collector = _async_collector(_page("ad-1"))

    with pytest.raises(InvalidParameterError, match="max_results"):
        [ad async for ad in collector.search(query="test", max_results=-1)]

    collector.client.search_ads.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_progress_callback_error_propagates_without_tracking_ad() -> None:
    collector = _async_collector(_page("ad-1"))
    tracker = DeduplicationTracker(mode="memory")

    def fail(_count: int, _total: int) -> None:
        raise RuntimeError("progress callback failed")

    with pytest.raises(RuntimeError, match="progress callback failed"):
        [ad async for ad in collector.search(
            query="test", dedup_tracker=tracker, progress_callback=fail
        )]

    assert collector.stats["ads_collected"] == 0
    assert tracker.count() == 0
    assert tracker.get_last_collection_time() is None


@pytest.mark.asyncio
async def test_async_early_close_persists_yielded_ad_but_not_completed_run() -> None:
    collector = _async_collector(_page("ad-1", "ad-2", cursor="next"))
    tracker = DeduplicationTracker(mode="memory")
    iterator = collector.search(query="test", dedup_tracker=tracker)

    first = await iterator.__anext__()
    assert tracker.has_seen(first.id)
    await iterator.aclose()

    assert tracker.get_last_collection_time() is None


@pytest.mark.asyncio
async def test_fully_consumed_async_search_records_completion_time() -> None:
    collector = _async_collector(_page("ad-1"))
    tracker = DeduplicationTracker(mode="memory")

    ads = [ad async for ad in collector.search(query="test", dedup_tracker=tracker)]

    assert [ad.id for ad in ads] == ["ad-1"]
    assert tracker.has_seen("ad-1")
    assert tracker.get_last_collection_time() is not None


@pytest.mark.asyncio
async def test_async_max_results_limit_with_more_pages_is_not_marked_complete() -> None:
    collector = _async_collector(
        _page("ad-1", cursor="next"),
        _page("ad-2"),
    )
    tracker = DeduplicationTracker(mode="memory")

    ads = [ad async for ad in collector.search(
        query="test", max_results=1, dedup_tracker=tracker
    )]

    assert [ad.id for ad in ads] == ["ad-1"]
    assert tracker.has_seen("ad-1")
    assert tracker.get_last_collection_time() is None
    collector.client.search_ads.assert_awaited_once()
