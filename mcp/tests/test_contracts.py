"""Input and filtering contracts, using real captured Meta records where relevant."""

from __future__ import annotations

import copy

import pytest
from meta_ads_collector_mcp.engine import matches, restore
from meta_ads_collector_mcp.schemas import Filters, ProxyProfile, Schedule, Search
from pydantic import ValidationError


@pytest.mark.parametrize(
    "changes",
    [
        {"country": "ALL"},
        {"country": "12"},
        {"country": "éé"},
        {"ad_type": "fake"},
        {"status": "fake"},
        {"search_type": "fake"},
        {"sort_by": "date"},
        {"page_ids": ["bad"]},
        {"page_ids": []},
        {"page_size": 0},
        {"page_size": 31},
        {"max_results": 0},
        {"max_requests": 0},
        {"max_seconds": 0},
        {"timeout": 121},
        {"max_retries": 0},
        {"rate_limit_delay": -1},
        {"jitter": -1},
        {"unknown": True},
    ],
)
def test_invalid_search_is_rejected(changes):
    with pytest.raises(ValidationError):
        Search.model_validate({"query": "nike", **changes})


def test_query_or_page_required():
    with pytest.raises(ValidationError):
        Search()
    with pytest.raises(ValidationError):
        Search(query="nike", search_type="PAGE")
    assert Search(page_ids=["89516513179"], country="eg").search_type == "PAGE"
    assert Search(query="nike", country="eg").country == "EG"


@pytest.mark.parametrize(
    "changes",
    [
        {"min_spend": -1},
        {"min_impressions": 10, "max_impressions": 9},
        {"min_spend": 10, "max_spend": 9},
        {"start_date": "2026-10-02", "end_date": "2026-10-01"},
        {"media_type": "FAKE"},
        {"missing_data": "FAKE"},
        {"unknown": True},
    ],
)
def test_invalid_filters_are_rejected(changes):
    with pytest.raises(ValidationError):
        Filters.model_validate(changes)


def test_filter_dates_are_utc():
    config = Filters(start_date="2026-10-01T05:00:00+03:00", end_date="2026-10-02")
    assert config.start_date.hour == 2
    assert config.end_date.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"environment": "A", "secret_file": "B"},
        {"environment": "bad name"},
        {"environment": "A", "max_failures": 0},
    ],
)
def test_proxy_requires_one_valid_reference(changes):
    with pytest.raises(ValidationError):
        ProxyProfile(name="research", **changes)


def test_schedule_validation():
    with pytest.raises(ValidationError):
        Schedule(name="research", search=Search(query="nike"), interval_seconds=59)
    with pytest.raises(ValidationError):
        Schedule(name="research", search=Search(query="nike"), retention_days=0)


def test_raw_record_round_trip(real_records):
    for record in real_records:
        assert restore(record).api_fields == record["api_fields"]
        assert restore(record).id == record["id"]


def test_missing_metrics_are_explicit(real_records):
    ad = restore(real_records[0])
    assert ad.impressions is None or (ad.impressions.lower_bound is None and ad.impressions.upper_bound is None)
    assert matches(ad, Filters(min_impressions=10000))
    assert not matches(ad, Filters(min_impressions=10000, missing_data="exclude"))


def test_range_overlap_and_missing_bounds(real_records):
    from meta_ads_collector import ImpressionRange

    ad = restore(real_records[0])
    ad.impressions = ImpressionRange(lower_bound=100, upper_bound=200)
    assert matches(ad, Filters(min_impressions=150, missing_data="exclude"))
    assert not matches(ad, Filters(min_impressions=201))
    ad.impressions.upper_bound = None
    assert not matches(ad, Filters(min_impressions=150, missing_data="exclude"))


def test_filtering_does_not_mutate_source(real_records):
    record = copy.deepcopy(real_records[0])
    matches(restore(record), Filters(publisher_platforms=["instagram"]))
    assert record == real_records[0]
