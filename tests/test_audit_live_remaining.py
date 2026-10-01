"""Remaining live Meta collection surfaces for the audit.

Enable with ``pytest --run-integration tests/test_audit_live_remaining.py``.
Queries are capped at three results and page names/IDs come from real ads.
"""

from __future__ import annotations

import csv
import json

import pytest

from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.events import AD_COLLECTED, COLLECTION_FINISHED
from meta_ads_collector.models import Ad

pytestmark = pytest.mark.integration


def _live_sync_collector() -> MetaAdsCollector:
    return MetaAdsCollector(rate_limit_delay=0.5, jitter=0, timeout=30, max_retries=2)


def test_live_sync_stream_emits_three_actual_ads_and_lifecycle_events() -> None:
    collector = _live_sync_collector()
    try:
        events = list(collector.stream(
            query="coca cola", country="US", max_results=3, page_size=10
        ))
    finally:
        collector.close()

    event_types = [event_type for event_type, _ in events]
    ad_events = [data["ad"] for event_type, data in events if event_type == AD_COLLECTED]
    assert len(ad_events) == 3
    assert all(isinstance(ad, Ad) and ad.id and ad.page and ad.page.id for ad in ad_events)
    assert event_types[0] == "collection_started"
    assert event_types[-1] == COLLECTION_FINISHED
    finished = next(data for event_type, data in events if event_type == COLLECTION_FINISHED)
    assert finished["total_ads"] == len(ad_events)


def test_live_progress_callback_reports_actual_yield_count_and_limit() -> None:
    progress: list[tuple[int, int]] = []
    collector = _live_sync_collector()
    try:
        ads = list(collector.search(
            query="coca cola",
            country="US",
            max_results=3,
            page_size=10,
            progress_callback=lambda count, total: progress.append((count, total)),
        ))
    finally:
        collector.close()

    assert len(ads) == 3
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert collector.get_stats()["ads_collected"] == 3


@pytest.mark.asyncio
async def test_live_async_json_and_csv_exports_report_their_actual_two_rows(
    tmp_path,
) -> None:
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    json_path = tmp_path / "meta-ads.json"
    csv_path = tmp_path / "meta-ads.csv"
    async with AsyncMetaAdsCollector(
        rate_limit_delay=0.5, jitter=0, timeout=30, max_retries=2
    ) as collector:
        json_count = await collector.collect_to_json(
            str(json_path), query="coca cola", country="US", max_results=2, page_size=2
        )
        csv_count = await collector.collect_to_csv(
            str(csv_path), query="coca cola", country="US", max_results=2, page_size=2
        )

    assert json_count == 2
    assert csv_count == 2
    output = json.loads(json_path.read_text(encoding="utf-8"))
    assert output["metadata"]["total_count"] == 2
    assert len(output["ads"]) == 2
    assert all(ad["id"] and ad["page"]["id"] for ad in output["ads"])
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert {"id", "page_id", "page_name", "creative_body"}.issubset(rows[0])
    assert all(row["id"] and row["page_id"] for row in rows)


@pytest.mark.asyncio
async def test_live_async_page_typeahead_finds_a_page_from_a_real_ad(
    collected_ads: list[Ad],
) -> None:
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    source_page_name = next(
        ad.page.name for ad in collected_ads if ad.page and ad.page.name
    )
    async with AsyncMetaAdsCollector(
        rate_limit_delay=0.5, jitter=0, timeout=30, max_retries=2
    ) as collector:
        pages = await collector.search_pages(source_page_name, country="US")

    assert pages
    assert all(page.page_id and page.page_name for page in pages)
    assert any(page.page_name.casefold() == source_page_name.casefold() for page in pages)


@pytest.mark.asyncio
async def test_live_async_details_return_meaningful_data_for_an_actual_ad_id(
    collected_ads: list[Ad],
) -> None:
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    source = next(ad for ad in collected_ads if ad.page and ad.page.id)
    async with AsyncMetaAdsCollector(
        rate_limit_delay=0.5, jitter=0, timeout=30, max_retries=2
    ) as collector:
        detail = await collector.client.get_ad_details(
            ad_archive_id=source.id,
            page_id=source.page.id,
        )

    detail_id = (
        detail.get("ad_archive_id")
        or detail.get("adArchiveID")
        or detail.get("id")
    )
    assert str(detail_id) == source.id
    assert any(detail.get(key) for key in ("page_id", "body", "snapshot", "cards", "images", "videos")), (
        "Meta returned only an identifier, so useful ad details were not verified"
    )
