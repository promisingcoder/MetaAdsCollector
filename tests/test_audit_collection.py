"""Behavioral audit tests for sync and async collection paths.

These tests replay captured public Meta rows with controlled pagination and
failure signals. They supplement live tests and never prove live transport.
"""

from __future__ import annotations

from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock

import pytest

from meta_ads_collector.async_collector import AsyncMetaAdsCollector
from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.events import ERROR_OCCURRED, PAGE_FETCHED, EventEmitter
from meta_ads_collector.exceptions import MetaAdsError, RateLimitError, SessionExpiredError
from meta_ads_collector.filters import FilterConfig
from meta_ads_collector.models import Ad, PageInfo
from tests.audit_meta_samples import CAPTURED_ADS


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
    from copy import deepcopy

    captured = {row["ad_archive_id"]: row for row in CAPTURED_ADS}
    return {"ads": [deepcopy(captured[ad_id]) for ad_id in ids]}, cursor


@pytest.mark.parametrize(
    ("marker", "expected_error"),
    [
        ({"rate_limited": True, "ads": []}, RateLimitError),
        ({"session_expired": True, "ads": []}, SessionExpiredError),
    ],
    ids=["rate-limit-exhausted", "session-refresh-exhausted"],
)
def test_sync_exhausted_server_retries_are_not_reported_as_success(
    marker: dict, expected_error: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exhausted rate/session retries must be surfaced to callers.

    The current implementation returns normally with an empty/partial result,
    even though it emits an error event. That makes a failed collection look
    like a complete successful search.
    """
    from meta_ads_collector import collector as collector_module

    monkeypatch.setattr(collector_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(collector_module.random, "uniform", lambda *_args: 0)
    collector = _sync_collector(*[(marker, None)] * 3)
    tracker = DeduplicationTracker(mode="memory")

    with pytest.raises(expected_error):
        list(collector.search(query="audit", dedup_tracker=tracker))

    assert collector.stats["errors"] == 1
    assert collector.stats["requests_made"] == 3
    assert tracker.get_last_collection_time() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("marker", "expected_error"),
    [
        ({"rate_limited": True, "ads": []}, RateLimitError),
        ({"session_expired": True, "ads": []}, SessionExpiredError),
    ],
    ids=["rate-limit-exhausted", "session-refresh-exhausted"],
)
async def test_async_exhausted_server_retries_are_not_reported_as_success(
    marker: dict, expected_error: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Async collection has the same non-silent exhaustion contract."""
    import asyncio

    from meta_ads_collector import async_collector as collector_module

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setattr(collector_module.random, "uniform", lambda *_args: 0)
    collector = _async_collector(*[(marker, None)] * 3)
    tracker = DeduplicationTracker(mode="memory")

    with pytest.raises(expected_error):
        [ad async for ad in collector.search(query="audit", dedup_tracker=tracker)]

    assert collector.stats["errors"] == 1
    assert collector.stats["requests_made"] == 3
    assert tracker.get_last_collection_time() is None


def test_sync_follows_cursor_after_empty_intermediate_page() -> None:
    """A returned cursor remains authoritative when an intermediate page is empty."""
    collector = _sync_collector(
        _page(cursor="cursor-1"),
        _page(CAPTURED_ADS[0]["ad_archive_id"]),
    )

    ads = list(collector.search(query="audit"))

    assert [ad.id for ad in ads] == [CAPTURED_ADS[0]["ad_archive_id"]]
    assert collector.client.search_ads.call_count == 2


@pytest.mark.asyncio
async def test_async_follows_cursor_after_empty_intermediate_page() -> None:
    collector = _async_collector(
        _page(cursor="cursor-1"),
        _page(CAPTURED_ADS[0]["ad_archive_id"]),
    )

    ads = [ad async for ad in collector.search(query="audit")]

    assert [ad.id for ad in ads] == [CAPTURED_ADS[0]["ad_archive_id"]]
    assert collector.client.search_ads.await_count == 2


def test_sync_repeated_cursor_is_stopped_before_a_third_fetch() -> None:
    """A finite duplicate-cursor response sequence isolates the cycle guard."""
    collector = _sync_collector(
        _page(CAPTURED_ADS[0]["ad_archive_id"], cursor="same-cursor"),
        _page(CAPTURED_ADS[1]["ad_archive_id"], cursor="same-cursor"),
        _page(),
    )

    tracker = DeduplicationTracker(mode="memory")
    with suppress(MetaAdsError):
        list(collector.search(query="audit", dedup_tracker=tracker))

    assert collector.client.search_ads.call_count <= 2
    assert tracker.get_last_collection_time() is None


@pytest.mark.asyncio
async def test_async_repeated_cursor_is_stopped_before_a_third_fetch() -> None:
    collector = _async_collector(
        _page(CAPTURED_ADS[0]["ad_archive_id"], cursor="same-cursor"),
        _page(CAPTURED_ADS[1]["ad_archive_id"], cursor="same-cursor"),
        _page(),
    )

    tracker = DeduplicationTracker(mode="memory")
    with suppress(MetaAdsError):
        [ad async for ad in collector.search(query="audit", dedup_tracker=tracker)]

    assert collector.client.search_ads.await_count <= 2
    assert tracker.get_last_collection_time() is None


def test_sync_malformed_root_parser_error_does_not_mark_dedup_run_complete() -> None:
    """A parser failure returned as empty results is not a completed run."""
    client = MetaAdsClient.__new__(MetaAdsClient)
    # Exercise the real response parser's malformed-root recovery path, which
    # returns an empty ads list plus an error instead of raising.
    parsed, cursor = client._parse_search_response({"data": []})
    assert parsed["ads"] == []
    assert parsed.get("error")
    assert cursor is None

    collector = _sync_collector((parsed, cursor))
    tracker = DeduplicationTracker(mode="memory")
    with pytest.raises(MetaAdsError, match="list.*get"):
        list(collector.search(query="audit", dedup_tracker=tracker))

    assert tracker.get_last_collection_time() is None


@pytest.mark.asyncio
async def test_async_malformed_root_parser_error_does_not_mark_dedup_run_complete() -> None:
    client = MetaAdsClient.__new__(MetaAdsClient)
    parsed, cursor = client._parse_search_response({"data": []})
    assert parsed["ads"] == []
    assert parsed.get("error")
    tracker = DeduplicationTracker(mode="memory")
    collector = _async_collector((parsed, cursor))

    with pytest.raises(MetaAdsError, match="list.*get"):
        [ad async for ad in collector.search(query="audit", dedup_tracker=tracker)]

    assert tracker.get_last_collection_time() is None


@pytest.mark.parametrize(
    "error_payload",
    [
        {"errors": [{"code": 999999, "message": "Internal server error"}]},
        {"data": []},  # malformed/null-root parser recovery
    ],
    ids=["unknown-graphql-error", "malformed-root-parser-error"],
)
def test_real_sync_client_error_result_does_not_advance_dedup_checkpoint(
    error_payload: dict,
) -> None:
    """Client-level error-shaped empty results must not advance run state."""
    import json

    client = MetaAdsClient.__new__(MetaAdsClient)
    client._initialized = True
    client._tokens = {}
    client._doc_ids = {}
    client._request_counter = 0
    client._fingerprint = MagicMock()
    client._fingerprint.get_graphql_headers.return_value = {}
    client._is_session_stale = lambda: False
    response = MagicMock(status_code=200, text=json.dumps(error_payload))
    client._make_graphql_request = lambda *_args, **_kwargs: response
    result, cursor = client.search_ads(query="audit")

    assert result["ads"] == []
    assert result.get("error")
    assert cursor is None
    collector = _sync_collector((result, cursor))
    tracker = DeduplicationTracker(mode="memory")
    with pytest.raises(MetaAdsError, match="Internal server error|list.*get"):
        list(collector.search(query="audit", dedup_tracker=tracker))
    assert tracker.get_last_collection_time() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proxy_url",
    ["http://localhost:8080", "socks5://localhost:1080"],
    ids=["http-proxy-url", "socks5-proxy-url"],
)
async def test_async_client_accepts_documented_proxy_url_schemes(proxy_url: str) -> None:
    """Async proxy setup should retain the URL forms supported by ProxyPool."""
    from unittest.mock import patch

    from meta_ads_collector.async_client import AsyncMetaAdsClient

    with patch("meta_ads_collector.async_client.CffiAsyncSession") as session_factory:
        client = AsyncMetaAdsClient(proxy=proxy_url)
        session_factory.assert_called_once()
        assert session_factory.call_args.kwargs["proxy"] == proxy_url
        client._close_client = AsyncMock()
        await client.close()


def test_sync_normal_retry_then_success_counts_attempts_and_page_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control case: transient exceptions retry, then account for one page."""
    from meta_ads_collector import collector as collector_module

    monkeypatch.setattr(collector_module.time, "sleep", lambda _seconds: None)
    collector = _sync_collector(_page(CAPTURED_ADS[0]["ad_archive_id"]))
    collector.client.search_ads.side_effect = [RuntimeError("temporary"), _page(CAPTURED_ADS[0]["ad_archive_id"])]

    assert [ad.id for ad in collector.search(query="audit")] == [CAPTURED_ADS[0]["ad_archive_id"]]
    assert collector.stats["requests_made"] == 2
    assert collector.stats["pages_fetched"] == 1
    assert collector.stats["errors"] == 1


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_collection_counts_dedup_and_filter_skips(async_mode: bool) -> None:
    first_id = CAPTURED_ADS[0]["ad_archive_id"]
    second_id = CAPTURED_ADS[1]["ad_archive_id"]
    responses = (_page(first_id, first_id, second_id),)
    tracker = DeduplicationTracker(mode="memory")
    tracker.mark_seen(first_id)
    if async_mode:
        collector = _async_collector(*responses)

        async def run() -> list[Ad]:
            return [ad async for ad in collector.search(
                query="audit",
                filter_config=FilterConfig(publisher_platforms=["__absent__"]),
                dedup_tracker=tracker,
            )]

        import asyncio
        result = asyncio.run(run())
    else:
        collector = _sync_collector(*responses)
        result = list(collector.search(
            query="audit",
            filter_config=FilterConfig(publisher_platforms=["__absent__"]),
            dedup_tracker=tracker,
        ))

    assert result == []
    assert collector.stats["duplicates_skipped"] == 2
    assert collector.stats["filtered_out"] == 1


def test_sync_enrichment_merges_every_supported_missing_detail_field() -> None:
    """Fields present in a captured real Meta ad must survive detail merging."""
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    detail_data = CAPTURED_ADS[0]
    details = Ad.from_graphql_response(detail_data)
    collector.client.get_ad_details.return_value = detail_data
    source = Ad(id=details.id)

    enriched = collector.enrich_ad(source)

    actual = {
        "page_id": enriched.page.id if enriched.page else None,
        "page_name": enriched.page.name if enriched.page else None,
        "delivery_start_time": enriched.delivery_start_time.isoformat()
        if enriched.delivery_start_time else None,
        "delivery_stop_time": enriched.delivery_stop_time.isoformat()
        if enriched.delivery_stop_time else None,
        "is_active": enriched.is_active,
        "creative_video": enriched.creatives[0].video_url if enriched.creatives else None,
    }
    assert actual == {
        "page_id": details.page.id,
        "page_name": details.page.name,
        "delivery_start_time": details.delivery_start_time.isoformat(),
        "delivery_stop_time": details.delivery_stop_time.isoformat(),
        "is_active": details.is_active,
        "creative_video": details.creatives[0].video_url,
    }
    # Enrichment is copy-on-write; the original ad remains unchanged.
    assert source.page is None
    assert source.is_active is None
    assert source.impressions is None


def test_enrichment_preserves_existing_false_and_zero_values() -> None:
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    detail_data = {
        **CAPTURED_ADS[0],
        "is_active": True,
        "estimated_audience_size": {"lower_bound": 50, "upper_bound": 100},
    }
    collector.client.get_ad_details.return_value = detail_data
    source = Ad(
        id=CAPTURED_ADS[0]["ad_archive_id"],
        is_active=False,
        page=PageInfo(
            id=CAPTURED_ADS[0]["page_id"],
            name=CAPTURED_ADS[0]["page_name"],
            likes=0,
            verified=False,
        ),
        estimated_audience_size_lower=0,
    )

    enriched = collector.enrich_ad(source)

    assert enriched.is_active is False
    assert enriched.page is not None and enriched.page.likes == 0
    assert enriched.page.verified is False
    assert enriched.estimated_audience_size_lower == 0
    assert source.is_active is False




def _assert_search_variables(
    payload: dict[str, str], *, cursor: str | None
) -> dict[str, object]:
    import json

    variables = json.loads(payload["variables"])
    assert variables["activeStatus"] == "INACTIVE"
    assert variables["adType"] == "HOUSING_ADS"
    assert variables["countries"] == ["EG"]
    actual_page_ids = [CAPTURED_ADS[0]["page_id"], CAPTURED_ADS[1]["page_id"]]
    assert variables["pageIDs"] == actual_page_ids
    assert variables["queryString"] == "solar roof"
    assert variables["searchType"] == "KEYWORD_UNORDERED"
    assert variables["first"] == 17
    assert variables["sessionID"] == "stable-session"
    assert variables["collationToken"] == "stable-collation"
    assert variables.get("cursor") == cursor
    assert variables["sortData"] == {
        "direction": "ASCENDING",
        "mode": "SORT_BY_TOTAL_IMPRESSIONS",
    }
    return variables


def test_sync_client_search_parameter_matrix_and_cursor_forwarding() -> None:
    """Explicit search inputs survive payload construction on both pages."""
    import json

    client = MetaAdsClient.__new__(MetaAdsClient)
    client._initialized = True
    client._init_time = 1.0
    client._max_session_age = 10**12
    client._tokens = {"lsd": "test-lsd"}
    client._doc_ids = {}
    client._request_counter = 0
    client._fingerprint = MagicMock()
    client._fingerprint.get_graphql_headers.return_value = {}
    empty_page = MagicMock(
        status_code=200,
        text=json.dumps({"data": {"ad_library_main": {
            "search_results_connection": {"edges": [], "page_info": {}}
        }}}),
    )
    payloads: list[dict[str, str]] = []

    def respond(payload: dict[str, str], _headers: dict[str, str]) -> MagicMock:
        payloads.append(dict(payload))
        return empty_page

    client._make_graphql_request = respond
    common = {
        "query": "solar roof",
        "country": "EG",
        "ad_type": "HOUSING_ADS",
        "active_status": "INACTIVE",
        "search_type": "KEYWORD_UNORDERED",
        "page_ids": [CAPTURED_ADS[0]["page_id"], CAPTURED_ADS[1]["page_id"]],
        "first": 17,
        "sort_direction": "ASCENDING",
        "sort_mode": "SORT_BY_TOTAL_IMPRESSIONS",
        "session_id": "stable-session",
        "collation_token": "stable-collation",
    }

    client.search_ads(**common)
    client.search_ads(**common, cursor="cursor-next")

    _assert_search_variables(payloads[0], cursor=None)
    assert "cursor" not in json.loads(payloads[0]["variables"])
    _assert_search_variables(payloads[1], cursor="cursor-next")


@pytest.mark.asyncio
async def test_async_client_search_parameter_matrix_and_cursor_forwarding() -> None:
    """Async client serializes the same public search parameters as sync."""
    import json
    from unittest.mock import patch

    from meta_ads_collector.async_client import AsyncMetaAdsClient

    empty_page = MagicMock(
        status_code=200,
        text=json.dumps({"data": {"ad_library_main": {
            "search_results_connection": {"edges": [], "page_info": {}}
        }}}),
    )
    with patch("meta_ads_collector.async_client.CffiAsyncSession"):
        client = AsyncMetaAdsClient()
    client._initialized = True
    client._init_time = 1.0
    client._logic._max_session_age = 10**12
    client._tokens = {"lsd": "test-lsd"}
    client._logic._tokens = client._tokens
    client._doc_ids = {}
    client._logic._doc_ids = client._doc_ids
    client._fingerprint = MagicMock()
    client._fingerprint.get_graphql_headers.return_value = {}
    client._client.headers = {}
    payloads: list[dict[str, str]] = []

    async def respond(
        _method: str, _url: str, *, data: dict[str, str], **_kwargs: object
    ) -> MagicMock:
        payloads.append(dict(data))
        return empty_page

    client._make_request = AsyncMock(side_effect=respond)
    common = {
        "query": "solar roof",
        "country": "EG",
        "ad_type": "HOUSING_ADS",
        "active_status": "INACTIVE",
        "search_type": "KEYWORD_UNORDERED",
        "page_ids": [CAPTURED_ADS[0]["page_id"], CAPTURED_ADS[1]["page_id"]],
        "first": 17,
        "sort_direction": "ASCENDING",
        "sort_mode": "SORT_BY_TOTAL_IMPRESSIONS",
        "session_id": "stable-session",
        "collation_token": "stable-collation",
    }

    await client.search_ads(**common)
    await client.search_ads(**common, cursor="cursor-next")

    first_vars = _assert_search_variables(payloads[0], cursor=None)
    assert "cursor" not in first_vars
    _assert_search_variables(payloads[1], cursor="cursor-next")
    client._close_client = AsyncMock()
    await client.close()


def test_sync_collector_reuses_session_and_collation_for_pagination() -> None:
    collector = _sync_collector(
        _page(CAPTURED_ADS[0]["ad_archive_id"], cursor="cursor-next"),
        _page(CAPTURED_ADS[1]["ad_archive_id"]),
    )

    expected = [CAPTURED_ADS[0]["ad_archive_id"], CAPTURED_ADS[1]["ad_archive_id"]]
    assert [ad.id for ad in collector.search(query="audit")] == expected

    first, second = [call.kwargs for call in collector.client.search_ads.call_args_list]
    assert first["cursor"] is None
    assert second["cursor"] == "cursor-next"
    assert first["session_id"] == second["session_id"]
    assert first["collation_token"] == second["collation_token"]


@pytest.mark.asyncio
async def test_async_collector_reuses_session_and_collation_for_pagination() -> None:
    collector = _async_collector(
        _page(CAPTURED_ADS[0]["ad_archive_id"], cursor="cursor-next"),
        _page(CAPTURED_ADS[1]["ad_archive_id"]),
    )

    ads = [ad async for ad in collector.search(query="audit")]

    assert [ad.id for ad in ads] == [CAPTURED_ADS[0]["ad_archive_id"], CAPTURED_ADS[1]["ad_archive_id"]]
    first, second = [call.kwargs for call in collector.client.search_ads.await_args_list]
    assert first["cursor"] is None
    assert second["cursor"] == "cursor-next"
    assert first["session_id"] == second["session_id"]
    assert first["collation_token"] == second["collation_token"]


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_collection_handles_a_thousand_ads_without_losing_results(async_mode: bool) -> None:
    captured_ad = CAPTURED_ADS[0]
    stress_ads = [
        {**captured_ad, "ad_archive_id": f"stress-{index}"}
        for index in range(1000)
    ]
    response = ({"ads": stress_ads}, None)
    if async_mode:
        collector = _async_collector(response)

        async def collect() -> list[Ad]:
            return [ad async for ad in collector.search(query="stress", page_size=1000)]

        import asyncio
        ads = asyncio.run(collect())
    else:
        collector = _sync_collector(response)
        ads = list(collector.search(query="stress", page_size=1000))

    assert len(ads) == 1000
    assert ads[0].id == "stress-0"
    assert ads[-1].id == "stress-999"
    assert collector.stats["ads_collected"] == 1000


def test_sync_stale_session_refresh_failure_is_not_used_for_a_search() -> None:
    client = MetaAdsClient.__new__(MetaAdsClient)
    client._initialized = True
    client._init_time = 1.0
    client._max_session_age = 0.0
    client._refresh_session = MagicMock(return_value=False)

    with pytest.raises(SessionExpiredError, match="stale session"):
        client.search_ads(query="audit")

    client._refresh_session.assert_called_once()


@pytest.mark.asyncio
async def test_async_stale_session_refresh_failure_is_not_used_for_a_search() -> None:
    from meta_ads_collector.async_client import AsyncMetaAdsClient

    with pytest.MonkeyPatch.context() as monkeypatch:
        import time
        monkeypatch.setattr(time, "time", lambda: 100.0)
        client = AsyncMetaAdsClient()
    client._initialized = True
    client._init_time = 1.0
    client._logic._max_session_age = 0.0
    client._async_refresh_session = AsyncMock(return_value=False)

    with pytest.raises(SessionExpiredError, match="stale async session"):
        await client.search_ads(query="audit")

    client._async_refresh_session.assert_awaited_once()
    client._close_client = AsyncMock()
    await client.close()


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_client_meta_error_is_counted_emitted_and_preserves_checkpoint(
    async_mode: bool,
) -> None:
    tracker = DeduplicationTracker(mode="memory")
    error_events = []
    if async_mode:
        collector = _async_collector()
        collector.event_emitter.on(ERROR_OCCURRED, error_events.append)
        collector.client.search_ads.side_effect = MetaAdsError("client failed")

        async def collect() -> None:
            [ad async for ad in collector.search(query="audit", dedup_tracker=tracker)]

        with pytest.raises(MetaAdsError, match="client failed"):
            import asyncio
            asyncio.run(collect())
    else:
        collector = _sync_collector()
        collector.event_emitter.on(ERROR_OCCURRED, error_events.append)
        collector.client.search_ads.side_effect = MetaAdsError("client failed")
        with pytest.raises(MetaAdsError, match="client failed"):
            list(collector.search(query="audit", dedup_tracker=tracker))

    assert collector.stats["errors"] == 1
    assert len(error_events) == 1
    assert error_events[0].data["context"] == "Search client raised an error"
    assert tracker.get_last_collection_time() is None


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_terminal_empty_page_does_not_emit_page_fetched(async_mode: bool) -> None:
    responses = (
        _page(CAPTURED_ADS[0]["ad_archive_id"], cursor="cursor-terminal"),
        _page(),
    )
    collector = _async_collector(*responses) if async_mode else _sync_collector(*responses)
    page_events = []
    collector.event_emitter.on(PAGE_FETCHED, page_events.append)

    if async_mode:
        async def collect() -> list[Ad]:
            return [ad async for ad in collector.search(query="audit")]

        import asyncio
        ads = asyncio.run(collect())
        assert collector.client.search_ads.await_count == 2
    else:
        ads = list(collector.search(query="audit"))
        assert collector.client.search_ads.call_count == 2

    assert [ad.id for ad in ads] == [CAPTURED_ADS[0]["ad_archive_id"]]
    assert len(page_events) == 1
    assert page_events[0].data["has_next_page"] is True
    assert collector.stats["pages_fetched"] == 2


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_unique_empty_cursor_pages_are_bounded_without_checkpoint(async_mode: bool) -> None:
    """More than 25 empty pages with distinct cursors fails as incomplete."""
    responses = tuple(_page(cursor=f"empty-cursor-{index}") for index in range(26))
    collector = _async_collector(*responses) if async_mode else _sync_collector(*responses)
    tracker = DeduplicationTracker(mode="memory")
    error_events = []
    collector.event_emitter.on(ERROR_OCCURRED, error_events.append)

    if async_mode:
        async def collect() -> None:
            [ad async for ad in collector.search(query="audit", dedup_tracker=tracker)]

        with pytest.raises(MetaAdsError, match="25 consecutive empty pages"):
            import asyncio
            asyncio.run(collect())
        assert collector.client.search_ads.await_count == 26
    else:
        with pytest.raises(MetaAdsError, match="25 consecutive empty pages"):
            list(collector.search(query="audit", dedup_tracker=tracker))
        assert collector.client.search_ads.call_count == 26

    assert collector.stats["errors"] == 1
    assert len(error_events) == 1
    assert tracker.get_last_collection_time() is None
