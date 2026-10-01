"""Live collection audit using only ads/pages returned by Meta.

Run explicitly with ``pytest --run-integration tests/test_audit_live_collection.py``.
Every selector used here comes from the shared real ``collected_ads`` fixture
or a live typeahead response; the request limits keep the calls small.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.events import AD_COLLECTED, COLLECTION_FINISHED, COLLECTION_STARTED
from meta_ads_collector.models import Ad

pytestmark = pytest.mark.integration


def _live_sync_collector() -> MetaAdsCollector:
    return MetaAdsCollector(rate_limit_delay=0.25, jitter=0, timeout=45, max_retries=2)


@pytest.mark.asyncio
async def test_live_async_search_returns_real_ads() -> None:
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    async with AsyncMetaAdsCollector(
        rate_limit_delay=0.25, jitter=0, timeout=45, max_retries=2
    ) as collector:
        ads = await collector.collect(
            query="coca cola", country="US", max_results=3, page_size=10
        )

    assert 1 <= len(ads) <= 3
    assert all(isinstance(ad, Ad) and ad.id and ad.page and ad.page.id for ad in ads)


@pytest.mark.asyncio
async def test_live_async_page_scoped_search_uses_a_page_from_a_real_ad(
    collected_ads: list[Ad],
) -> None:
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    source_page_id = next(ad.page.id for ad in collected_ads if ad.page and ad.page.id)
    async with AsyncMetaAdsCollector(
        rate_limit_delay=0.25, jitter=0, timeout=45, max_retries=2
    ) as collector:
        ads = await collector.collect(
            query="",
            country="US",
            status="ALL",
            search_type=collector.SEARCH_PAGE,
            page_ids=[source_page_id],
            max_results=3,
            page_size=10,
        )

    assert ads
    assert all(ad.page is not None and ad.page.id == source_page_id for ad in ads)


@pytest.mark.asyncio
async def test_live_async_early_close_records_yielded_ad_and_finishes_events() -> None:
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    events: list[str] = []
    tracker = DeduplicationTracker(mode="memory")
    async with AsyncMetaAdsCollector(
        rate_limit_delay=0.25, jitter=0, timeout=45, max_retries=2
    ) as collector:
        for event_name in (COLLECTION_STARTED, AD_COLLECTED, COLLECTION_FINISHED):
            collector.event_emitter.on(
                event_name, lambda event: events.append(event.event_type)
            )
        iterator = collector.search(
            query="coca cola",
            country="US",
            max_results=3,
            page_size=10,
            dedup_tracker=tracker,
        )
        first = await iterator.__anext__()
        await iterator.aclose()

    assert first.id
    assert tracker.has_seen(first.id)
    assert tracker.get_last_collection_time() is None
    assert events[0] == COLLECTION_STARTED
    assert AD_COLLECTED in events
    assert events[-1] == COLLECTION_FINISHED


def test_live_page_id_url_and_name_flows_resolve_to_returned_meta_pages(
    collected_ads: list[Ad],
) -> None:
    """Exercise all sync page entry points against live page/ad identifiers."""
    from urllib.parse import quote

    from meta_ads_collector.url_parser import extract_page_id_from_url

    source_ad = next(ad for ad in collected_ads if ad.page and ad.page.id and ad.page.name)
    page_id = source_ad.page.id
    page_name = source_ad.page.name
    # A real Meta Ad Library URL carrying the observed page ID, rather than a
    # fabricated numeric page or unrelated sample link.
    page_url = (
        "https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
        f"&country=US&view_all_page_id={quote(page_id)}"
    )
    assert extract_page_id_from_url(page_url) == page_id

    collector = _live_sync_collector()
    try:
        by_id = list(collector.collect_by_page_id(
            page_id, country="US", status="ALL", max_results=2, page_size=10
        ))
        by_url = list(collector.collect_by_page_url(
            page_url, country="US", status="ALL", max_results=2, page_size=10
        ))
        matches = collector.search_pages(page_name, country="US")
        assert matches
        by_name = list(collector.collect_by_page_name(
            page_name, country="US", status="ALL", max_results=2, page_size=10
        ))
    finally:
        collector.close()

    assert by_id and all(ad.page and ad.page.id == page_id for ad in by_id)
    assert by_url and all(ad.page and ad.page.id == page_id for ad in by_url)
    resolved_page_ids = {page.page_id for page in matches}
    assert by_name and all(ad.page and ad.page.id in resolved_page_ids for ad in by_name)


def test_live_enrichment_preserves_identity_for_an_actually_returned_ad(
    collected_ads: list[Ad],
) -> None:
    source = next(ad for ad in collected_ads if ad.page and ad.page.id)
    original = copy.deepcopy(source)
    collector = _live_sync_collector()
    try:
        detail_data = collector.client.get_ad_details(
            ad_archive_id=source.id, page_id=source.page.id
        )

        details = Ad.from_graphql_response(detail_data)
        candidates: dict[str, Any] = {}
        scalar_fields = (
            "ad_library_id", "is_active", "ad_status", "delivery_start_time",
            "delivery_stop_time", "snapshot_url", "ad_snapshot_url", "impressions",
            "spend", "reach", "currency", "estimated_audience_size_lower",
            "estimated_audience_size_upper", "funding_entity", "disclaimer", "ad_type",
            "targeting",
        )
        list_fields = (
            "publisher_platforms", "languages", "categories", "bylines",
            "beneficiary_payers", "age_gender_distribution", "region_distribution",
        )
        for field_name in scalar_fields:
            detail_value = getattr(details, field_name)
            if getattr(source, field_name) is None and detail_value is not None:
                candidates[field_name] = detail_value
        for field_name in list_fields:
            detail_value = getattr(details, field_name)
            if not getattr(source, field_name) and detail_value:
                candidates[field_name] = detail_value
        if source.page is None and details.page and details.page.id:
            candidates["page"] = details.page
        elif source.page and details.page:
            for field_name in ("profile_picture_url", "page_url", "likes"):
                detail_value = getattr(details.page, field_name)
                if getattr(source.page, field_name) in (None, "", 0) and detail_value:
                    candidates[f"page.{field_name}"] = detail_value

        # Compare creative media only where both responses have corresponding
        # creatives and the original is missing a value.
        creative_media: list[tuple[int, str, Any]] = []
        media_fields = ("image_url", "video_url", "video_hd_url", "video_sd_url", "thumbnail_url")
        for index, detail_creative in enumerate(details.creatives):
            if index >= len(source.creatives):
                continue
            for field_name in media_fields:
                detail_value = getattr(detail_creative, field_name)
                if not getattr(source.creatives[index], field_name) and detail_value:
                    creative_media.append((index, field_name, detail_value))

        if not candidates and not creative_media:
            pytest.skip(
                f"Meta returned no additional enrichable fields for live ad {source.id}"
            )

        # Use the actual response fetched above, avoiding a second detail call.
        collector.client.get_ad_details = lambda **_kwargs: detail_data
        enriched = collector.enrich_ad(source)
    finally:
        collector.close()

    assert enriched.id == source.id
    assert enriched is not source
    assert source == original
    for field_name, expected in candidates.items():
        if field_name.startswith("page."):
            assert enriched.page is not None
            assert getattr(enriched.page, field_name.split(".", 1)[1]) == expected
        else:
            assert getattr(enriched, field_name) == expected
    for index, field_name, expected in creative_media:
        assert getattr(enriched.creatives[index], field_name) == expected


def test_live_search_lifecycle_events_match_yielded_ads() -> None:
    events: list[str] = []

    def record(event: Any) -> None:
        events.append(event.event_type)

    collector = _live_sync_collector()
    for event_name in (COLLECTION_STARTED, AD_COLLECTED, COLLECTION_FINISHED):
        collector.event_emitter.on(event_name, record)
    try:
        ads = list(collector.search(
            query="coca cola", country="US", max_results=3, page_size=10
        ))
    finally:
        collector.close()

    assert 1 <= len(ads) <= 3
    assert events[0] == COLLECTION_STARTED
    assert events.count(AD_COLLECTED) == len(ads)
    assert events[-1] == COLLECTION_FINISHED


def test_live_early_close_keeps_yielded_ad_dedup_record_without_completion() -> None:
    tracker = DeduplicationTracker(mode="memory")
    collector = _live_sync_collector()
    iterator = collector.search(
        query="coca cola", country="US", max_results=3,
        page_size=10, dedup_tracker=tracker,
    )
    try:
        first = next(iterator)
        iterator.close()
    finally:
        collector.close()

    assert first.id
    assert tracker.has_seen(first.id)
    assert tracker.get_last_collection_time() is None
