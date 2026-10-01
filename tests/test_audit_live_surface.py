"""Bounded live Meta surface checks; enable with --run-integration.

These tests make real requests, never replace the HTTP client, and use public
ads returned by Meta. Empty results alone are not considered a defect for
narrow or restricted searches. Error-shaped results must remain visible.
"""

from __future__ import annotations

import time

import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.models import Ad

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def surface_client():
    with MetaAdsClient(timeout=20, max_retries=2) as client:
        client.initialize()
        yield client


@pytest.mark.parametrize("ad_type", [
    "ALL", "POLITICAL_AND_ISSUE_ADS", "HOUSING_ADS", "EMPLOYMENT_ADS", "CREDIT_ADS",
])
@pytest.mark.parametrize("status", ["ACTIVE", "INACTIVE", "ALL"])
def test_live_supported_category_and_status_are_not_silent_errors(surface_client, ad_type, status):
    time.sleep(1)
    query = "climate" if ad_type == "POLITICAL_AND_ISSUE_ADS" else "nike"
    result, _cursor = surface_client.search_ads(
        query=query, country="US", ad_type=ad_type, active_status=status, first=2,
    )
    assert not result.get("error"), result.get("error")
    assert not result.get("rate_limited")
    assert not result.get("session_expired")
    assert isinstance(result.get("ads"), list)
    assert isinstance(result.get("raw", {}).get("data"), dict)
    for raw in result["ads"]:
        ad = Ad.from_graphql_response(raw)
        assert ad.id
        if isinstance(raw.get("is_active"), bool):
            assert ad.is_active is raw["is_active"], f"Lost actual status of Meta ad {ad.id}"
            if status != "ALL":
                assert raw["is_active"] is (status == "ACTIVE")


@pytest.mark.parametrize("country", ["US", "GB", "EG", "DE", "BR"])
def test_live_search_supports_country_parameter(surface_client, country):
    time.sleep(1)
    result, _cursor = surface_client.search_ads(query="nike", country=country, first=2)
    assert not result.get("error"), result.get("error")
    assert isinstance(result.get("ads"), list)
    assert isinstance(result.get("raw", {}).get("data"), dict)


@pytest.mark.parametrize("search_type", ["KEYWORD_EXACT_PHRASE", "KEYWORD_UNORDERED"])
@pytest.mark.parametrize("sort", [None, "SORT_BY_TOTAL_IMPRESSIONS"])
def test_live_keyword_and_sort_modes(surface_client, search_type, sort):
    time.sleep(1)
    result, _cursor = surface_client.search_ads(
        query="nike", country="US", search_type=search_type, sort_mode=sort, first=2,
    )
    assert not result.get("error"), result.get("error")
    assert result.get("ads"), "Broad live brand search returned no ads"


def test_live_stress_collection_paginates_and_deduplicates(record_property):
    """Exercise bounded real pagination while respecting request delays."""
    with MetaAdsCollector(timeout=20, max_retries=2, rate_limit_delay=1, jitter=0.3) as collector:
        tracker = DeduplicationTracker()
        ads = list(collector.search(query="nike", country="US", max_results=120,
                                    page_size=10, dedup_tracker=tracker))
        ids = [ad.id for ad in ads]
        assert len(ids) >= 50, "Not enough live results to exercise the intended stress workload"
        assert len(ids) == len(set(ids))
        assert tracker.count() == len(ids)
        stats = collector.get_stats()
        assert stats["ads_collected"] == len(ids)
        assert stats["errors"] == 0
        assert stats["pages_fetched"] >= 5
        record_property("actual_meta_ads", len(ids))
        record_property("actual_meta_pages", stats["pages_fetched"])


def test_live_proactive_session_refresh(surface_client):
    """Refresh a genuinely initialized Meta session through the public search path."""
    surface_client._init_time = 0
    result, _cursor = surface_client.search_ads(query="nike", country="US", first=2)
    assert not result.get("error"), result.get("error")
    assert result.get("ads")
    assert surface_client._init_time > 0
