"""Tests for Wave 2 bug fixes.

Covers:
- Issue C3: SpendRange/ImpressionRange.__str__ with 0 bounds
- Issue S3: sort_by=None (relevancy) should not be overridden
- Issue S8: Export methods forward filter_config and dedup_tracker
- Issue N1: SEARCH_KEYWORD != SEARCH_EXACT (distinct values)
- Issue N2: _ad_has_video/_ad_has_image check raw_data arrays
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from meta_ads_collector.constants import (
    SEARCH_EXACT,
    SEARCH_KEYWORD,
    SEARCH_UNORDERED,
    SORT_IMPRESSIONS,
    SORT_RELEVANCY,
    VALID_SEARCH_TYPES,
)
from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.filters import FilterConfig, _ad_has_image, _ad_has_video
from meta_ads_collector.models import (
    Ad,
    AdCreative,
    ImpressionRange,
    SpendRange,
)

# ---------------------------------------------------------------------------
# Issue C3: SpendRange / ImpressionRange with 0 bounds
# ---------------------------------------------------------------------------

class TestC3ZeroBounds:
    """Verify that 0 is treated as a valid bound, not as falsy/missing."""

    def test_spend_range_zero_lower(self):
        sr = SpendRange(lower_bound=0, upper_bound=500, currency="USD")
        assert str(sr) == "USD 0 - 500"

    def test_spend_range_zero_upper(self):
        sr = SpendRange(lower_bound=0, upper_bound=0, currency="EUR")
        assert str(sr) == "EUR 0 - 0"

    def test_spend_range_zero_both(self):
        sr = SpendRange(lower_bound=0, upper_bound=0, currency="GBP")
        assert str(sr) == "GBP 0 - 0"

    def test_spend_range_none_still_na(self):
        sr = SpendRange(lower_bound=None, upper_bound=500, currency="USD")
        assert str(sr) == "N/A"

    def test_spend_range_both_none_still_na(self):
        sr = SpendRange()
        assert str(sr) == "N/A"

    def test_impression_range_zero_lower(self):
        ir = ImpressionRange(lower_bound=0, upper_bound=1000)
        assert str(ir) == "0 - 1,000"

    def test_impression_range_zero_upper(self):
        ir = ImpressionRange(lower_bound=0, upper_bound=0)
        assert str(ir) == "0 - 0"

    def test_impression_range_none_still_na(self):
        ir = ImpressionRange(lower_bound=None, upper_bound=1000)
        assert str(ir) == "N/A"

    def test_impression_range_both_none_still_na(self):
        ir = ImpressionRange()
        assert str(ir) == "N/A"

    def test_spend_range_normal_values_unchanged(self):
        """Non-zero values still work as before."""
        sr = SpendRange(lower_bound=100, upper_bound=500, currency="USD")
        assert str(sr) == "USD 100 - 500"

    def test_impression_range_normal_values_unchanged(self):
        ir = ImpressionRange(lower_bound=1000, upper_bound=5000)
        assert str(ir) == "1,000 - 5,000"


# ---------------------------------------------------------------------------
# Issue S3: sort_by=None (relevancy) should not be overridden
# ---------------------------------------------------------------------------

class TestS3SortByRelevancy:
    """Verify sort_by=None passes through to client.search_ads as None."""

    def test_sort_relevancy_constant_is_none(self):
        assert SORT_RELEVANCY is None

    def test_sort_impressions_constant_is_not_none(self):
        assert SORT_IMPRESSIONS is not None

    def test_sync_collector_sort_none_not_overridden(self):
        """When sort_by=None (relevancy), sort_mode should be None, not SORT_IMPRESSIONS."""
        from meta_ads_collector.collector import MetaAdsCollector

        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.stats = {
            "requests_made": 0,
            "ads_collected": 0,
            "pages_fetched": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

        mock_client = MagicMock()
        mock_client.search_ads.return_value = ({"ads": []}, None)
        collector.client = mock_client

        from meta_ads_collector.events import EventEmitter
        collector.event_emitter = EventEmitter()

        # Consume the generator to trigger the search_ads call
        list(collector.search(query="test", sort_by=None))

        # Verify sort_mode was passed as None, not as SORT_IMPRESSIONS
        mock_client.search_ads.assert_called_once()
        call_kwargs = mock_client.search_ads.call_args
        assert call_kwargs.kwargs.get("sort_mode") is None

    def test_sync_collector_sort_default_uses_impressions(self):
        """When sort_by is the default (SORT_IMPRESSIONS), sort_mode should be SORT_IMPRESSIONS."""
        from meta_ads_collector.collector import MetaAdsCollector

        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.stats = {
            "requests_made": 0,
            "ads_collected": 0,
            "pages_fetched": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

        mock_client = MagicMock()
        mock_client.search_ads.return_value = ({"ads": []}, None)
        collector.client = mock_client

        from meta_ads_collector.events import EventEmitter
        collector.event_emitter = EventEmitter()

        list(collector.search(query="test"))

        call_kwargs = mock_client.search_ads.call_args
        assert call_kwargs.kwargs.get("sort_mode") == SORT_IMPRESSIONS


# ---------------------------------------------------------------------------
# Issue S8: Export methods forward filter_config and dedup_tracker
# ---------------------------------------------------------------------------

class TestS8ExportForwarding:
    """Export methods must forward filter_config and dedup_tracker to search()."""

    def _make_collector_with_mock_search(self):
        """Create a MetaAdsCollector with search() mocked to yield one ad."""
        from meta_ads_collector.collector import MetaAdsCollector

        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.stats = {
            "requests_made": 0,
            "ads_collected": 0,
            "pages_fetched": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

        from meta_ads_collector.events import EventEmitter
        collector.event_emitter = EventEmitter()
        collector.client = MagicMock()

        return collector

    def test_collect_forwards_filter_and_dedup(self):
        collector = self._make_collector_with_mock_search()
        fc = FilterConfig(min_impressions=100)
        tracker = DeduplicationTracker(mode="memory")

        with patch.object(collector, "search", return_value=iter([])) as mock_search:
            collector.collect(
                query="test",
                filter_config=fc,
                dedup_tracker=tracker,
            )
            mock_search.assert_called_once()
            kwargs = mock_search.call_args.kwargs
            assert kwargs["filter_config"] is fc
            assert kwargs["dedup_tracker"] is tracker

    def test_collect_to_json_forwards_filter_and_dedup(self):
        import os
        import tempfile

        collector = self._make_collector_with_mock_search()
        fc = FilterConfig(min_spend=50)
        tracker = DeduplicationTracker(mode="memory")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "out.json")
            with patch.object(collector, "search", return_value=iter([])) as mock_search:
                collector.collect_to_json(
                    output_path=output,
                    query="test",
                    filter_config=fc,
                    dedup_tracker=tracker,
                )
                mock_search.assert_called_once()
                kwargs = mock_search.call_args.kwargs
                assert kwargs["filter_config"] is fc
                assert kwargs["dedup_tracker"] is tracker

    def test_collect_to_csv_forwards_filter_and_dedup(self):
        import os
        import tempfile

        collector = self._make_collector_with_mock_search()
        fc = FilterConfig(max_impressions=5000)
        tracker = DeduplicationTracker(mode="memory")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "out.csv")
            with patch.object(collector, "search", return_value=iter([])) as mock_search:
                collector.collect_to_csv(
                    output_path=output,
                    query="test",
                    filter_config=fc,
                    dedup_tracker=tracker,
                )
                mock_search.assert_called_once()
                kwargs = mock_search.call_args.kwargs
                assert kwargs["filter_config"] is fc
                assert kwargs["dedup_tracker"] is tracker

    def test_collect_to_jsonl_forwards_filter_and_dedup(self):
        import os
        import tempfile

        collector = self._make_collector_with_mock_search()
        fc = FilterConfig(has_video=True)
        tracker = DeduplicationTracker(mode="memory")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "out.jsonl")
            with patch.object(collector, "search", return_value=iter([])) as mock_search:
                collector.collect_to_jsonl(
                    output_path=output,
                    query="test",
                    filter_config=fc,
                    dedup_tracker=tracker,
                )
                mock_search.assert_called_once()
                kwargs = mock_search.call_args.kwargs
                assert kwargs["filter_config"] is fc
                assert kwargs["dedup_tracker"] is tracker

    def test_collect_defaults_none_for_filter_and_dedup(self):
        """When not provided, filter_config and dedup_tracker default to None."""
        collector = self._make_collector_with_mock_search()

        with patch.object(collector, "search", return_value=iter([])) as mock_search:
            collector.collect(query="test")
            kwargs = mock_search.call_args.kwargs
            assert kwargs["filter_config"] is None
            assert kwargs["dedup_tracker"] is None


# ---------------------------------------------------------------------------
# Issue N1: SEARCH_KEYWORD != SEARCH_EXACT
# ---------------------------------------------------------------------------

class TestN1SearchConstants:
    """After the fix, SEARCH_KEYWORD and SEARCH_EXACT must have distinct values."""

    def test_search_keyword_is_unordered(self):
        assert SEARCH_KEYWORD == "KEYWORD_UNORDERED"

    def test_search_exact_is_exact_phrase(self):
        assert SEARCH_EXACT == "KEYWORD_EXACT_PHRASE"

    def test_search_keyword_and_exact_differ(self):
        assert SEARCH_KEYWORD != SEARCH_EXACT

    def test_search_keyword_equals_unordered(self):
        assert SEARCH_KEYWORD == SEARCH_UNORDERED

    def test_valid_search_types_contains_all_four(self):
        assert "KEYWORD_UNORDERED" in VALID_SEARCH_TYPES
        assert "KEYWORD_EXACT_PHRASE" in VALID_SEARCH_TYPES
        assert "PAGE" in VALID_SEARCH_TYPES
        # The set should have 3 unique values since KEYWORD and UNORDERED
        # are now both KEYWORD_UNORDERED
        assert len(VALID_SEARCH_TYPES) == 3

    def test_cli_keyword_maps_to_unordered(self):
        from meta_ads_collector.cli import map_search_type

        assert map_search_type("keyword") == "KEYWORD_UNORDERED"

    def test_cli_exact_maps_to_exact_phrase(self):
        from meta_ads_collector.cli import map_search_type

        assert map_search_type("exact") == "KEYWORD_EXACT_PHRASE"

    def test_cli_keyword_and_exact_differ(self):
        from meta_ads_collector.cli import map_search_type

        assert map_search_type("keyword") != map_search_type("exact")

    def test_validation_accepts_keyword_exact_phrase(self):
        """KEYWORD_EXACT_PHRASE (SEARCH_EXACT) must be a valid search type."""
        from meta_ads_collector.collector import MetaAdsCollector

        # Should not raise
        MetaAdsCollector._validate_params(
            ad_type="ALL",
            status="ACTIVE",
            search_type="KEYWORD_EXACT_PHRASE",
            sort_by=None,
            country="US",
        )

    def test_validation_accepts_keyword_unordered(self):
        """KEYWORD_UNORDERED (SEARCH_KEYWORD) must be a valid search type."""
        from meta_ads_collector.collector import MetaAdsCollector

        MetaAdsCollector._validate_params(
            ad_type="ALL",
            status="ACTIVE",
            search_type="KEYWORD_UNORDERED",
            sort_by=None,
            country="US",
        )


# ---------------------------------------------------------------------------
# Issue N2: _ad_has_video / _ad_has_image check raw_data
# ---------------------------------------------------------------------------

class TestN2RawDataMediaCheck:
    """_ad_has_video and _ad_has_image should check raw_data arrays."""

    def test_ad_has_video_via_creative(self):
        ad = Ad(
            id="1",
            creatives=[AdCreative(video_url="https://example.com/v.mp4")],
        )
        assert _ad_has_video(ad) is True

    def test_ad_has_video_via_raw_data(self):
        ad = Ad(
            id="2",
            creatives=[],
            raw_data={"videos": [{"video_hd_url": "https://example.com/v.mp4"}]},
        )
        assert _ad_has_video(ad) is True

    def test_ad_has_video_false_when_no_media(self):
        ad = Ad(id="3", creatives=[], raw_data={})
        assert _ad_has_video(ad) is False

    def test_ad_has_video_false_with_empty_videos_list(self):
        ad = Ad(id="4", creatives=[], raw_data={"videos": []})
        assert _ad_has_video(ad) is False

    def test_ad_has_video_false_with_no_raw_data(self):
        ad = Ad(id="5", creatives=[], raw_data=None)
        assert _ad_has_video(ad) is False

    def test_ad_has_image_via_creative(self):
        ad = Ad(
            id="6",
            creatives=[AdCreative(image_url="https://example.com/img.jpg")],
        )
        assert _ad_has_image(ad) is True

    def test_ad_has_image_via_raw_data(self):
        ad = Ad(
            id="7",
            creatives=[],
            raw_data={"images": [{"original_image_url": "https://example.com/img.jpg"}]},
        )
        assert _ad_has_image(ad) is True

    def test_ad_has_image_false_when_no_media(self):
        ad = Ad(id="8", creatives=[], raw_data={})
        assert _ad_has_image(ad) is False

    def test_ad_has_image_false_with_empty_images_list(self):
        ad = Ad(id="9", creatives=[], raw_data={"images": []})
        assert _ad_has_image(ad) is False

    def test_ad_has_image_false_with_no_raw_data(self):
        ad = Ad(id="10", creatives=[], raw_data=None)
        assert _ad_has_image(ad) is False

    def test_ad_has_video_prefers_creative_over_raw_data(self):
        """When both creative and raw_data have video, it should still return True."""
        ad = Ad(
            id="11",
            creatives=[AdCreative(video_hd_url="https://example.com/v_hd.mp4")],
            raw_data={"videos": [{"video_hd_url": "https://example.com/v_hd.mp4"}]},
        )
        assert _ad_has_video(ad) is True

    def test_ad_has_image_via_thumbnail(self):
        ad = Ad(
            id="12",
            creatives=[AdCreative(thumbnail_url="https://example.com/thumb.jpg")],
        )
        assert _ad_has_image(ad) is True

    def test_filter_has_video_uses_raw_data(self):
        """The passes_filter function should use the updated _ad_has_video."""
        from meta_ads_collector.filters import passes_filter

        ad = Ad(
            id="13",
            creatives=[],
            raw_data={"videos": [{"video_hd_url": "https://example.com/v.mp4"}]},
        )
        fc = FilterConfig(has_video=True)
        assert passes_filter(ad, fc) is True

    def test_filter_has_image_uses_raw_data(self):
        """The passes_filter function should use the updated _ad_has_image."""
        from meta_ads_collector.filters import passes_filter

        ad = Ad(
            id="14",
            creatives=[],
            raw_data={"images": [{"original_image_url": "https://example.com/img.jpg"}]},
        )
        fc = FilterConfig(has_image=True)
        assert passes_filter(ad, fc) is True

    def test_filter_media_type_video_uses_raw_data(self):
        """media_type=VIDEO should detect video in raw_data."""
        from meta_ads_collector.filters import passes_filter

        ad = Ad(
            id="15",
            creatives=[],
            raw_data={"videos": [{"video_sd_url": "https://example.com/v.mp4"}]},
        )
        fc = FilterConfig(media_type="VIDEO")
        assert passes_filter(ad, fc) is True

    def test_filter_media_type_image_uses_raw_data(self):
        """media_type=IMAGE should detect image in raw_data."""
        from meta_ads_collector.filters import passes_filter

        ad = Ad(
            id="16",
            creatives=[],
            raw_data={"images": [{"resized_image_url": "https://example.com/img.jpg"}]},
        )
        fc = FilterConfig(media_type="IMAGE")
        assert passes_filter(ad, fc) is True
