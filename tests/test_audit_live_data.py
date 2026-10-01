"""Live-data audit checks against real Meta ads, gated as integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.filters import FilterConfig, passes_filter
from meta_ads_collector.models import Ad
from meta_ads_collector.url_parser import extract_page_id_from_url
from tests.audit_meta_samples import CAPTURED_ADS


@pytest.fixture(scope="session")
def nike_all_status_ads() -> list[Ad]:
    """Sample an actual active/inactive-capable US brand result set."""
    from meta_ads_collector.collector import MetaAdsCollector

    collector = MetaAdsCollector(rate_limit_delay=0, jitter=0, timeout=45)
    try:
        ads = list(collector.search(
            query="nike", country="US", status="ALL", max_results=10, page_size=10,
        ))
    finally:
        collector.close()
    if not ads:
        pytest.skip("The live Nike/US ALL-status search returned no ads")
    return ads


@pytest.fixture(scope="session")
def political_us_ads() -> list[Ad]:
    """Sample real US political ads, which commonly include spend ranges."""
    from meta_ads_collector.collector import MetaAdsCollector

    collector = MetaAdsCollector(rate_limit_delay=0, jitter=0, timeout=45)
    try:
        ads = list(collector.search(
            query="trump", country="US", ad_type="POLITICAL_AND_ISSUE_ADS",
            status="ALL", max_results=10, page_size=10,
        ))
    finally:
        collector.close()
    if not ads:
        pytest.skip("The live US political search returned no ads")
    return ads


@pytest.fixture(scope="session")
def germany_ads() -> list[Ad]:
    """Sample real Germany ads to cover an EU-market response shape."""
    from meta_ads_collector.collector import MetaAdsCollector

    collector = MetaAdsCollector(rate_limit_delay=0, jitter=0, timeout=45)
    try:
        ads = list(collector.search(
            query="nike", country="DE", status="ALL", max_results=5, page_size=10,
        ))
    finally:
        collector.close()
    if not ads:
        pytest.skip("The live Germany search returned no ads")
    return ads


def _raw(ad: Ad) -> dict[str, Any]:
    assert isinstance(ad.raw_data, dict), f"Ad {ad.id} has no raw API payload"
    return ad.raw_data


def _range_bounds(raw: Any) -> tuple[Any, Any] | None:
    if not isinstance(raw, dict):
        return None
    lower = raw.get("lower_bound", raw.get("lowerBound"))
    upper = raw.get("upper_bound", raw.get("upperBound"))
    return (lower, upper) if lower is not None or upper is not None else None


@pytest.mark.integration
def test_live_ads_keep_core_fields_and_metric_bounds(
    collected_ads: list[Ad], political_us_ads: list[Ad], germany_ads: list[Ad],
) -> None:
    """Compare normalized fields to the exact raw rows returned by Meta."""
    ads = collected_ads + political_us_ads + germany_ads
    assert ads
    for ad in ads:
        raw = _raw(ad)
        assert ad.id == str(raw.get("id") or raw.get("adArchiveID") or raw.get("ad_archive_id"))

        page_id = raw.get("page_id")
        page_name = raw.get("page_name")
        if page_id is not None:
            assert ad.page is not None
            assert ad.page.id == page_id
        if page_name is not None:
            assert ad.page is not None
            assert ad.page.name == page_name

        for raw_keys, attr_name in (
            (("impressions", "impressionsWithIndex", "impressions_with_index"), "impressions"),
            (("spend", "spendWithIndex"), "spend"),
            (("reach", "reach_estimate"), "reach"),
        ):
            raw_range = next((raw[key] for key in raw_keys if raw.get(key) is not None), None)
            bounds = _range_bounds(raw_range)
            parsed_range = getattr(ad, attr_name)
            if bounds is not None:
                assert parsed_range is not None, f"{ad.id} lost raw {raw_keys[0]} bounds"
                assert (parsed_range.lower_bound, parsed_range.upper_bound) == bounds


@pytest.mark.integration
def test_live_boolean_statuses_are_not_collapsed_to_unknown(
    collected_ads: list[Ad], nike_all_status_ads: list[Ad], political_us_ads: list[Ad],
) -> None:
    """In particular, preserve actual false values supplied by the API."""
    checked = 0
    for ad in collected_ads + nike_all_status_ads + political_us_ads:
        raw = _raw(ad)
        if "is_active" in raw:
            checked += 1
            assert ad.is_active == raw["is_active"], f"is_active mismatch for {ad.id}"
        elif "isActive" in raw:
            checked += 1
            assert ad.is_active == raw["isActive"], f"isActive mismatch for {ad.id}"
        else:
            status = raw.get("ad_status") or raw.get("adStatus")
            if status is not None:
                checked += 1
                assert ad.is_active is (status == "ACTIVE"), f"status mismatch for {ad.id}: {status}"
    assert checked, "The live sample did not include any status fields"


@pytest.mark.integration
def test_live_raw_shape_with_controlled_false_status_preserves_false(
    political_us_ads: list[Ad],
) -> None:
    """Flip an observed status field to false to cover the falsey raw value."""
    import copy

    raw = copy.deepcopy(_raw(political_us_ads[0]))
    raw["is_active"] = False
    reparsed = Ad.from_graphql_response(raw)

    assert reparsed.is_active is False


@pytest.mark.integration
def test_live_integer_delivery_times_retain_utc_instant(
    collected_ads: list[Ad], political_us_ads: list[Ad], germany_ads: list[Ad],
) -> None:
    """Unix delivery timestamps are UTC instants regardless of host timezone."""
    checked = 0
    for ad in collected_ads + political_us_ads + germany_ads:
        raw = _raw(ad)
        for keys, parsed in (
            (("ad_delivery_start_time", "startDate", "start_date"), ad.delivery_start_time),
            (("ad_delivery_stop_time", "endDate", "end_date"), ad.delivery_stop_time),
        ):
            timestamp = next((raw[key] for key in keys if key in raw and raw[key] is not None), None)
            if isinstance(timestamp, int) and not isinstance(timestamp, bool):
                checked += 1
                assert parsed == datetime.fromtimestamp(timestamp, timezone.utc), (
                    f"{ad.id} parsed {keys[0]} as {parsed!r}, expected UTC timestamp"
                )
    if not checked:
        pytest.skip("The live sample did not contain integer delivery timestamps")


@pytest.mark.integration
def test_live_iso_delivery_dates_match_selected_raw_aliases(
    collected_ads: list[Ad], nike_all_status_ads: list[Ad],
) -> None:
    checked = 0
    for ad in collected_ads + nike_all_status_ads:
        raw = _raw(ad)
        for keys, parsed in (
            (("ad_delivery_start_time", "startDate", "start_date"), ad.delivery_start_time),
            (("ad_delivery_stop_time", "endDate", "end_date"), ad.delivery_stop_time),
        ):
            value = next((raw[key] for key in keys if key in raw and raw[key] is not None), None)
            if isinstance(value, str):
                checked += 1
                expected = datetime.fromisoformat(value.replace("Z", "+00:00"))
                assert parsed == expected, f"{ad.id} parsed date alias {keys} incorrectly"
    if not checked:
        pytest.skip("The live sample did not contain ISO delivery dates")


@pytest.mark.integration
def test_live_date_filters_use_real_delivery_dates_and_and_logic(
    collected_ads: list[Ad], nike_all_status_ads: list[Ad],
) -> None:
    """Exercise inclusive and rejecting date boundaries on real API dates."""
    ad = next(
        (ad for ad in collected_ads + nike_all_status_ads if ad.delivery_start_time is not None),
        None,
    )
    if ad is None:
        pytest.skip("The live sample has no parsed delivery start time")

    start = ad.delivery_start_time
    platform = (ad.publisher_platforms or ["__no_platform__"])[0]
    assert passes_filter(ad, FilterConfig(start_date=start, end_date=start))
    assert passes_filter(
        ad,
        FilterConfig(start_date=start, end_date=start, publisher_platforms=[platform]),
    )
    assert not passes_filter(ad, FilterConfig(start_date=start + timedelta(seconds=1)))
    assert not passes_filter(
        ad,
        FilterConfig(start_date=start, publisher_platforms=["__no_matching_platform__"]),
    )


def test_captured_live_row_with_controlled_performance_ranges_filters_inclusive_and_by_and():
    """Inject ranges into a captured raw row because public rows often omit metrics."""
    import copy

    raw = copy.deepcopy(CAPTURED_ADS[0])
    raw["impressions"] = {"lower_bound": 1_000, "upper_bound": 5_000}
    raw["spend"] = {"lower_bound": 100, "upper_bound": 500}
    ad = Ad.from_graphql_response(raw)
    start = ad.delivery_start_time
    assert start is not None

    assert passes_filter(
        ad,
        FilterConfig(
            min_impressions=5_000,
            max_impressions=1_000,
            min_spend=500,
            max_spend=100,
            start_date=start,
            end_date=start,
        ),
    )
    assert not passes_filter(ad, FilterConfig(min_spend=501, start_date=start))


@pytest.mark.integration
def test_live_page_urls_resolve_using_actual_page_ids(
    collected_ads: list[Ad], nike_all_status_ads: list[Ad], germany_ads: list[Ad],
) -> None:
    """Use page IDs from real ads in Meta's public Ad Library URL format."""
    checked = 0
    for ad in collected_ads + nike_all_status_ads + germany_ads:
        if not ad.page or not ad.page.id:
            continue
        url = f"https://www.facebook.com/ads/library/?view_all_page_id={ad.page.id}"
        assert extract_page_id_from_url(url) == ad.page.id
        checked += 1
    assert checked, "The live sample did not contain page IDs"


def test_captured_real_carousel_keeps_every_creative_and_media_url():
    ad = Ad.from_graphql_response(CAPTURED_ADS[1])
    cards = CAPTURED_ADS[1]["cards"]

    assert len(ad.creatives) == len(cards)
    for card, creative in zip(cards, ad.creatives):
        expected_image = card.get("resized_image_url") or card.get("original_image_url")
        assert creative.image_url == expected_image
        assert creative.link_url == card.get("link_url")


def test_multiple_flat_media_items_from_captured_rows_are_all_represented():
    """Use only distinct media URLs present in captured public Meta rows."""
    import copy

    image_urls = []
    video_urls = []
    for row in CAPTURED_ADS:
        for card in row.get("cards") or []:
            url = card.get("resized_image_url") or card.get("original_image_url")
            if url and url not in image_urls:
                image_urls.append(url)
        for video in row.get("videos") or []:
            url = video.get("video_hd_url") or video.get("video_sd_url")
            if url and url not in video_urls:
                video_urls.append(url)
    assert len(image_urls) >= 2
    assert len(video_urls) >= 2

    raw = copy.deepcopy(CAPTURED_ADS[0])
    raw["cards"] = []
    raw["images"] = [{"original_image_url": url} for url in image_urls[:2]]
    raw["videos"] = [{"video_hd_url": url} for url in video_urls[:2]]
    parsed = Ad.from_graphql_response(raw)

    parsed_images = {creative.image_url for creative in parsed.creatives if creative.image_url}
    parsed_videos = {creative.video_hd_url for creative in parsed.creatives if creative.video_hd_url}
    assert set(image_urls[:2]) <= parsed_images
    assert set(video_urls[:2]) <= parsed_videos


@pytest.mark.integration
def test_live_serialization_round_trips_the_captured_payload(
    collected_ads: list[Ad], political_us_ads: list[Ad], germany_ads: list[Ad],
) -> None:
    """Exporting a real ad retains raw data and emits valid JSON timestamps."""
    for ad in collected_ads + political_us_ads + germany_ads:
        exported = json.loads(ad.to_json(include_raw=True))
        assert exported["id"] == ad.id
        assert exported["raw_data"] == ad.raw_data
        if ad.delivery_start_time is not None:
            assert exported["delivery_start_time"] == ad.delivery_start_time.isoformat()


@pytest.mark.integration
def test_live_memory_dedup_skips_ids_from_repeated_real_searches() -> None:
    from meta_ads_collector.collector import MetaAdsCollector

    collector = MetaAdsCollector(rate_limit_delay=0, jitter=0, timeout=45)
    tracker = DeduplicationTracker(mode="memory")
    try:
        first = list(collector.search(
            query="coca cola", country="US", max_results=5, page_size=10,
            dedup_tracker=tracker,
        ))
        second = list(collector.search(
            query="coca cola", country="US", max_results=5, page_size=10,
            dedup_tracker=tracker,
        ))
    finally:
        collector.close()

    assert first
    first_ids = {ad.id for ad in first}
    assert first_ids.isdisjoint({ad.id for ad in second})


@pytest.mark.integration
def test_live_persistent_dedup_survives_reopen_between_real_searches(tmp_path: Path) -> None:
    from meta_ads_collector.collector import MetaAdsCollector

    db_path = tmp_path / "live-dedup.sqlite"
    collector = MetaAdsCollector(rate_limit_delay=0, jitter=0, timeout=45)
    try:
        with DeduplicationTracker(mode="persistent", db_path=str(db_path)) as tracker:
            first = list(collector.search(
                query="coca cola", country="US", max_results=5, page_size=10,
                dedup_tracker=tracker,
            ))
        with DeduplicationTracker(mode="persistent", db_path=str(db_path)) as tracker:
            second = list(collector.search(
                query="coca cola", country="US", max_results=5, page_size=10,
                dedup_tracker=tracker,
            ))
    finally:
        collector.close()

    assert first
    assert {ad.id for ad in first}.isdisjoint({ad.id for ad in second})


def test_null_media_fault_does_not_hide_a_real_captured_asset(
) -> None:
    """Inject a null member into a captured row while retaining its real URL."""
    import copy

    raw = copy.deepcopy(CAPTURED_ADS[0])
    real_urls = {
        value
        for item in raw["videos"]
        for value in item.values()
        if isinstance(value, str) and value.startswith("https://")
    }
    raw["videos"].insert(0, None)

    reparsed = Ad.from_graphql_response(raw)
    parsed_urls = {
        value
        for creative in reparsed.creatives
        for value in (
            creative.video_url,
            creative.video_hd_url,
            creative.video_sd_url,
            creative.thumbnail_url,
        )
        if value
    }
    assert real_urls <= parsed_urls
