"""Tests for meta_ads_collector.models."""

import json
from datetime import datetime

from meta_ads_collector.models import (
    Ad,
    AdCreative,
    ImpressionRange,
    PageInfo,
    SearchResult,
    SpendRange,
)

# ---------------------------------------------------------------------------
# SpendRange / ImpressionRange
# ---------------------------------------------------------------------------

class TestSpendRange:
    def test_str_both_bounds(self):
        sr = SpendRange(lower_bound=100, upper_bound=500, currency="USD")
        assert str(sr) == "USD 100 - 500"

    def test_str_missing_bounds(self):
        sr = SpendRange()
        assert str(sr) == "N/A"


class TestImpressionRange:
    def test_str_both_bounds(self):
        ir = ImpressionRange(lower_bound=1000, upper_bound=5000)
        assert str(ir) == "1,000 - 5,000"

    def test_str_missing_bounds(self):
        ir = ImpressionRange()
        assert str(ir) == "N/A"


# ---------------------------------------------------------------------------
# AdCreative
# ---------------------------------------------------------------------------

class TestAdCreative:
    def test_to_dict_omits_none(self):
        creative = AdCreative(body="Hello", title="Title")
        d = creative.to_dict()
        assert d == {"body": "Hello", "title": "Title"}
        assert "link_url" not in d

    def test_to_dict_all_fields(self):
        creative = AdCreative(
            body="body",
            caption="cap",
            description="desc",
            title="title",
            link_url="https://example.com",
            image_url="https://example.com/img.jpg",
            video_url="https://example.com/vid.mp4",
            video_hd_url="https://example.com/vid_hd.mp4",
            video_sd_url="https://example.com/vid_sd.mp4",
            thumbnail_url="https://example.com/thumb.jpg",
            cta_text="Buy Now",
            cta_type="BUY",
        )
        d = creative.to_dict()
        assert len(d) == 12  # all fields present


# ---------------------------------------------------------------------------
# PageInfo
# ---------------------------------------------------------------------------

class TestPageInfo:
    def test_to_dict(self):
        page = PageInfo(id="1", name="Page", verified=True)
        d = page.to_dict()
        assert d["id"] == "1"
        assert d["name"] == "Page"
        assert d["verified"] is True


# ---------------------------------------------------------------------------
# Ad
# ---------------------------------------------------------------------------

class TestAd:
    def test_to_dict_roundtrip(self, sample_ad):
        d = sample_ad.to_dict()
        assert d["id"] == "12345"
        assert d["page"]["name"] == "Test Page"
        assert d["impressions"]["lower_bound"] == 1000
        assert d["spend"]["currency"] == "USD"
        assert len(d["creatives"]) == 1
        assert d["publisher_platforms"] == ["facebook", "instagram"]

    def test_to_json_returns_valid_json(self, sample_ad):
        j = sample_ad.to_json()
        parsed = json.loads(j)
        assert parsed["id"] == "12345"

    def test_to_dict_excludes_raw_by_default(self, sample_ad):
        sample_ad.raw_data = {"some": "data"}
        d = sample_ad.to_dict()
        assert "raw_data" not in d

    def test_to_dict_includes_raw_when_requested(self, sample_ad):
        sample_ad.raw_data = {"some": "data"}
        d = sample_ad.to_dict(include_raw=True)
        assert d["raw_data"] == {"some": "data"}

    def test_from_graphql_response_cards_format(self, sample_graphql_ad_data):
        ad = Ad.from_graphql_response(sample_graphql_ad_data)
        assert ad.id == "12345"
        assert ad.page.name == "Test Page"
        assert ad.page.id == "pg-99"
        assert ad.is_active is True
        assert len(ad.creatives) == 1
        assert ad.creatives[0].body == "Buy our product!"
        assert ad.creatives[0].title == "Great Deal"
        assert ad.creatives[0].cta_text == "Shop Now"
        assert ad.impressions.lower_bound == 1000
        assert ad.impressions.upper_bound == 5000
        assert ad.spend.lower_bound == 100
        assert ad.currency == "USD"
        assert ad.publisher_platforms == ["facebook", "instagram"]
        assert ad.languages == ["en"]

    def test_from_graphql_response_delivery_start(self, sample_graphql_ad_data):
        ad = Ad.from_graphql_response(sample_graphql_ad_data)
        assert ad.delivery_start_time is not None
        assert isinstance(ad.delivery_start_time, datetime)

    def test_from_graphql_response_minimal_data(self):
        data = {"ad_archive_id": "999"}
        ad = Ad.from_graphql_response(data)
        assert ad.id == "999"
        assert ad.creatives == [] or all(c.body is None for c in ad.creatives)

    def test_from_graphql_response_old_format(self):
        data = {
            "ad_archive_id": "888",
            "page_id": "pg-1",
            "page_name": "Old Format",
            "ad_creative_bodies": ["Body text"],
            "ad_creative_link_titles": ["Title text"],
            "publisher_platforms": ["facebook"],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.id == "888"
        assert ad.page.name == "Old Format"
        assert ad.creatives[0].body == "Body text"
        assert ad.creatives[0].title == "Title text"

    def test_from_graphql_response_demographics(self, sample_graphql_ad_data):
        ad = Ad.from_graphql_response(sample_graphql_ad_data)
        assert len(ad.age_gender_distribution) == 1
        assert ad.age_gender_distribution[0].category == "25-34_male"
        assert ad.age_gender_distribution[0].percentage == 0.35
        assert len(ad.region_distribution) == 1
        assert ad.region_distribution[0].category == "California"


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------

class TestSearchResult:
    def test_to_dict(self, sample_ad):
        result = SearchResult(
            ads=[sample_ad],
            total_count=1,
            has_next_page=False,
            end_cursor=None,
        )
        d = result.to_dict()
        assert len(d["ads"]) == 1
        assert d["total_count"] == 1
        assert d["has_next_page"] is False
