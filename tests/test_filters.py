"""Tests for meta_ads_collector.filters."""

import sys
from datetime import datetime
from unittest.mock import patch

from meta_ads_collector.cli import build_filter_config, parse_args
from meta_ads_collector.filters import FilterConfig, passes_filter
from meta_ads_collector.models import (
    Ad,
    AdCreative,
    ImpressionRange,
    SpendRange,
)

# ---------------------------------------------------------------------------
# Helper: build a minimal Ad for filter testing
# ---------------------------------------------------------------------------

def _make_ad(
    impressions_lower=None,
    impressions_upper=None,
    spend_lower=None,
    spend_upper=None,
    delivery_start=None,
    delivery_stop=None,
    platforms=None,
    languages=None,
    has_video=False,
    has_image=False,
):
    """Build a minimal Ad with specific fields for filter testing."""
    creatives = []
    if has_video or has_image:
        creative = AdCreative(
            image_url="https://example.com/img.jpg" if has_image else None,
            video_url="https://example.com/vid.mp4" if has_video else None,
        )
        creatives.append(creative)

    impressions = None
    if impressions_lower is not None or impressions_upper is not None:
        impressions = ImpressionRange(
            lower_bound=impressions_lower,
            upper_bound=impressions_upper,
        )

    spend = None
    if spend_lower is not None or spend_upper is not None:
        spend = SpendRange(
            lower_bound=spend_lower,
            upper_bound=spend_upper,
        )

    return Ad(
        id="test-ad",
        impressions=impressions,
        spend=spend,
        delivery_start_time=delivery_start,
        delivery_stop_time=delivery_stop,
        publisher_platforms=platforms or [],
        languages=languages or [],
        creatives=creatives,
    )


# ---------------------------------------------------------------------------
# FilterConfig
# ---------------------------------------------------------------------------

class TestFilterConfig:
    def test_default_is_empty(self):
        fc = FilterConfig()
        assert fc.is_empty() is True

    def test_non_empty_with_min_impressions(self):
        fc = FilterConfig(min_impressions=100)
        assert fc.is_empty() is False

    def test_non_empty_with_start_date(self):
        fc = FilterConfig(start_date=datetime(2024, 1, 1))
        assert fc.is_empty() is False


# ---------------------------------------------------------------------------
# Impression filters
# ---------------------------------------------------------------------------

class TestImpressionFilters:
    def test_min_impressions_passes(self):
        ad = _make_ad(impressions_lower=500, impressions_upper=2000)
        fc = FilterConfig(min_impressions=1000)
        # upper_bound (2000) >= 1000 -> pass
        assert passes_filter(ad, fc) is True

    def test_min_impressions_fails(self):
        ad = _make_ad(impressions_lower=100, impressions_upper=500)
        fc = FilterConfig(min_impressions=1000)
        # upper_bound (500) < 1000 -> fail
        assert passes_filter(ad, fc) is False

    def test_min_impressions_exact_boundary(self):
        ad = _make_ad(impressions_lower=500, impressions_upper=1000)
        fc = FilterConfig(min_impressions=1000)
        # upper_bound (1000) >= 1000 -> pass
        assert passes_filter(ad, fc) is True

    def test_max_impressions_passes(self):
        ad = _make_ad(impressions_lower=100, impressions_upper=500)
        fc = FilterConfig(max_impressions=1000)
        # lower_bound (100) <= 1000 -> pass
        assert passes_filter(ad, fc) is True

    def test_max_impressions_fails(self):
        ad = _make_ad(impressions_lower=2000, impressions_upper=5000)
        fc = FilterConfig(max_impressions=1000)
        # lower_bound (2000) > 1000 -> fail
        assert passes_filter(ad, fc) is False

    def test_max_impressions_exact_boundary(self):
        ad = _make_ad(impressions_lower=1000, impressions_upper=5000)
        fc = FilterConfig(max_impressions=1000)
        # lower_bound (1000) <= 1000 -> pass
        assert passes_filter(ad, fc) is True

    def test_no_impressions_data_passes_min(self):
        """Ads with missing impressions data pass the filter (inclusion policy)."""
        ad = _make_ad()  # no impressions
        fc = FilterConfig(min_impressions=1000)
        assert passes_filter(ad, fc) is True

    def test_no_impressions_data_passes_max(self):
        ad = _make_ad()
        fc = FilterConfig(max_impressions=1000)
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# Spend filters
# ---------------------------------------------------------------------------

class TestSpendFilters:
    def test_min_spend_passes(self):
        ad = _make_ad(spend_lower=500, spend_upper=2000)
        fc = FilterConfig(min_spend=1000)
        assert passes_filter(ad, fc) is True

    def test_min_spend_fails(self):
        ad = _make_ad(spend_lower=100, spend_upper=500)
        fc = FilterConfig(min_spend=1000)
        assert passes_filter(ad, fc) is False

    def test_max_spend_passes(self):
        ad = _make_ad(spend_lower=100, spend_upper=500)
        fc = FilterConfig(max_spend=1000)
        assert passes_filter(ad, fc) is True

    def test_max_spend_fails(self):
        ad = _make_ad(spend_lower=2000, spend_upper=5000)
        fc = FilterConfig(max_spend=1000)
        assert passes_filter(ad, fc) is False

    def test_no_spend_data_passes_min(self):
        ad = _make_ad()
        fc = FilterConfig(min_spend=1000)
        assert passes_filter(ad, fc) is True

    def test_no_spend_data_passes_max(self):
        ad = _make_ad()
        fc = FilterConfig(max_spend=1000)
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# Date filters
# ---------------------------------------------------------------------------

class TestDateFilters:
    def test_start_date_passes(self):
        ad = _make_ad(delivery_start=datetime(2024, 6, 15))
        fc = FilterConfig(start_date=datetime(2024, 1, 1))
        assert passes_filter(ad, fc) is True

    def test_start_date_fails(self):
        ad = _make_ad(delivery_start=datetime(2023, 6, 15))
        fc = FilterConfig(start_date=datetime(2024, 1, 1))
        assert passes_filter(ad, fc) is False

    def test_start_date_exact_boundary(self):
        ad = _make_ad(delivery_start=datetime(2024, 1, 1))
        fc = FilterConfig(start_date=datetime(2024, 1, 1))
        assert passes_filter(ad, fc) is True

    def test_end_date_passes(self):
        ad = _make_ad(delivery_start=datetime(2024, 6, 15))
        fc = FilterConfig(end_date=datetime(2024, 12, 31))
        assert passes_filter(ad, fc) is True

    def test_end_date_fails(self):
        ad = _make_ad(delivery_start=datetime(2025, 6, 15))
        fc = FilterConfig(end_date=datetime(2024, 12, 31))
        assert passes_filter(ad, fc) is False

    def test_no_date_data_passes_start(self):
        ad = _make_ad()
        fc = FilterConfig(start_date=datetime(2024, 1, 1))
        assert passes_filter(ad, fc) is True

    def test_no_date_data_passes_end(self):
        ad = _make_ad()
        fc = FilterConfig(end_date=datetime(2024, 12, 31))
        assert passes_filter(ad, fc) is True

    def test_date_range_filter(self):
        ad = _make_ad(delivery_start=datetime(2024, 6, 15))
        fc = FilterConfig(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
        assert passes_filter(ad, fc) is True

    def test_date_range_filter_outside(self):
        ad = _make_ad(delivery_start=datetime(2025, 3, 1))
        fc = FilterConfig(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
        assert passes_filter(ad, fc) is False


# ---------------------------------------------------------------------------
# Media type filter
# ---------------------------------------------------------------------------

class TestMediaTypeFilter:
    def test_video_filter_passes_with_video(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(media_type="VIDEO")
        assert passes_filter(ad, fc) is True

    def test_video_filter_fails_without_video(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(media_type="VIDEO")
        assert passes_filter(ad, fc) is False

    def test_image_filter_passes_with_image(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(media_type="IMAGE")
        assert passes_filter(ad, fc) is True

    def test_image_filter_fails_without_image(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(media_type="IMAGE")
        assert passes_filter(ad, fc) is False

    def test_all_media_type_passes_everything(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(media_type="ALL")
        assert passes_filter(ad, fc) is True

    def test_none_media_type_passes_no_media(self):
        ad = _make_ad()
        fc = FilterConfig(media_type="NONE")
        assert passes_filter(ad, fc) is True

    def test_none_media_type_fails_with_media(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(media_type="NONE")
        assert passes_filter(ad, fc) is False

    def test_media_type_case_insensitive(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(media_type="video")
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# Publisher platform filter
# ---------------------------------------------------------------------------

class TestPublisherPlatformFilter:
    def test_matching_platform(self):
        ad = _make_ad(platforms=["facebook", "instagram"])
        fc = FilterConfig(publisher_platforms=["facebook"])
        assert passes_filter(ad, fc) is True

    def test_non_matching_platform(self):
        ad = _make_ad(platforms=["facebook"])
        fc = FilterConfig(publisher_platforms=["instagram"])
        assert passes_filter(ad, fc) is False

    def test_multiple_platforms_one_match(self):
        ad = _make_ad(platforms=["facebook"])
        fc = FilterConfig(publisher_platforms=["instagram", "facebook"])
        assert passes_filter(ad, fc) is True

    def test_missing_platform_data_passes(self):
        ad = _make_ad(platforms=[])
        fc = FilterConfig(publisher_platforms=["facebook"])
        # Empty platforms -> include (missing data policy)
        assert passes_filter(ad, fc) is True

    def test_platform_case_insensitive(self):
        ad = _make_ad(platforms=["Facebook"])
        fc = FilterConfig(publisher_platforms=["facebook"])
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# Language filter
# ---------------------------------------------------------------------------

class TestLanguageFilter:
    def test_matching_language(self):
        ad = _make_ad(languages=["en"])
        fc = FilterConfig(languages=["en"])
        assert passes_filter(ad, fc) is True

    def test_non_matching_language(self):
        ad = _make_ad(languages=["en"])
        fc = FilterConfig(languages=["es"])
        assert passes_filter(ad, fc) is False

    def test_multiple_languages_one_match(self):
        ad = _make_ad(languages=["en", "fr"])
        fc = FilterConfig(languages=["fr"])
        assert passes_filter(ad, fc) is True

    def test_missing_language_data_passes(self):
        ad = _make_ad(languages=[])
        fc = FilterConfig(languages=["en"])
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# has_video / has_image filters
# ---------------------------------------------------------------------------

class TestContentTypeFilters:
    def test_has_video_true_passes(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(has_video=True)
        assert passes_filter(ad, fc) is True

    def test_has_video_true_fails(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(has_video=True)
        assert passes_filter(ad, fc) is False

    def test_has_video_false_excludes_video(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(has_video=False)
        assert passes_filter(ad, fc) is False

    def test_has_video_false_passes_no_video(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(has_video=False)
        assert passes_filter(ad, fc) is True

    def test_has_image_true_passes(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(has_image=True)
        assert passes_filter(ad, fc) is True

    def test_has_image_true_fails(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(has_image=True)
        assert passes_filter(ad, fc) is False

    def test_has_image_false_excludes_image(self):
        ad = _make_ad(has_image=True)
        fc = FilterConfig(has_image=False)
        assert passes_filter(ad, fc) is False

    def test_has_image_false_passes_no_image(self):
        ad = _make_ad(has_video=True)
        fc = FilterConfig(has_image=False)
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# Combined filters (AND logic)
# ---------------------------------------------------------------------------

class TestCombinedFilters:
    def test_all_pass(self):
        ad = _make_ad(
            impressions_lower=1000,
            impressions_upper=5000,
            spend_lower=500,
            spend_upper=2000,
            delivery_start=datetime(2024, 6, 15),
            platforms=["facebook"],
            languages=["en"],
            has_video=True,
        )
        fc = FilterConfig(
            min_impressions=1000,
            max_spend=3000,
            start_date=datetime(2024, 1, 1),
            publisher_platforms=["facebook"],
            languages=["en"],
            has_video=True,
        )
        assert passes_filter(ad, fc) is True

    def test_one_fails_rest_pass(self):
        ad = _make_ad(
            impressions_lower=1000,
            impressions_upper=5000,
            spend_lower=500,
            spend_upper=700,  # fails min_spend=1000
            delivery_start=datetime(2024, 6, 15),
            platforms=["facebook"],
        )
        fc = FilterConfig(
            min_impressions=1000,
            min_spend=1000,
            start_date=datetime(2024, 1, 1),
            publisher_platforms=["facebook"],
        )
        assert passes_filter(ad, fc) is False


# ---------------------------------------------------------------------------
# Empty / no-filter fast path
# ---------------------------------------------------------------------------

class TestNoFilters:
    def test_empty_filter_config_passes_all(self):
        ad = _make_ad()
        fc = FilterConfig()
        assert passes_filter(ad, fc) is True

    def test_empty_filter_config_passes_complex_ad(self):
        ad = _make_ad(
            impressions_lower=100,
            impressions_upper=500,
            spend_lower=50,
            spend_upper=200,
            has_video=True,
            has_image=True,
        )
        fc = FilterConfig()
        assert passes_filter(ad, fc) is True


# ---------------------------------------------------------------------------
# CLI filter flags
# ---------------------------------------------------------------------------

class TestFilterCLIFlags:
    def test_min_impressions_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--min-impressions", "1000"
        ]):
            args = parse_args()
            assert args.min_impressions == 1000

    def test_max_impressions_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--max-impressions", "5000"
        ]):
            args = parse_args()
            assert args.max_impressions == 5000

    def test_min_spend_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--min-spend", "100"
        ]):
            args = parse_args()
            assert args.min_spend == 100

    def test_max_spend_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--max-spend", "500"
        ]):
            args = parse_args()
            assert args.max_spend == 500

    def test_start_date_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--start-date", "2024-01-01"
        ]):
            args = parse_args()
            assert args.start_date == "2024-01-01"

    def test_end_date_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--end-date", "2024-12-31"
        ]):
            args = parse_args()
            assert args.end_date == "2024-12-31"

    def test_media_type_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--media-type", "video"
        ]):
            args = parse_args()
            assert args.media_type == "video"

    def test_publisher_platform_flag_repeatable(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--publisher-platform", "facebook",
            "--publisher-platform", "instagram",
        ]):
            args = parse_args()
            assert args.publisher_platforms == ["facebook", "instagram"]

    def test_language_flag_repeatable(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--language", "en",
            "--language", "es",
        ]):
            args = parse_args()
            assert args.filter_languages == ["en", "es"]

    def test_has_video_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--has-video"
        ]):
            args = parse_args()
            assert args.has_video is True

    def test_has_image_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--has-image"
        ]):
            args = parse_args()
            assert args.has_image is True

    def test_filter_defaults_none(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.min_impressions is None
            assert args.max_impressions is None
            assert args.min_spend is None
            assert args.max_spend is None
            assert args.start_date is None
            assert args.end_date is None
            assert args.media_type is None
            assert args.publisher_platforms is None
            assert args.filter_languages is None


# ---------------------------------------------------------------------------
# build_filter_config
# ---------------------------------------------------------------------------

class TestBuildFilterConfig:
    def test_no_filters_returns_none(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            fc = build_filter_config(args)
            assert fc is None

    def test_with_min_impressions(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--min-impressions", "1000"
        ]):
            args = parse_args()
            fc = build_filter_config(args)
            assert fc is not None
            assert fc.min_impressions == 1000

    def test_with_date_range(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--start-date", "2024-01-01",
            "--end-date", "2024-12-31",
        ]):
            args = parse_args()
            fc = build_filter_config(args)
            assert fc is not None
            assert fc.start_date == datetime(2024, 1, 1)
            assert fc.end_date == datetime(2024, 12, 31)

    def test_invalid_date_format_ignored(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--start-date", "not-a-date",
        ]):
            args = parse_args()
            fc = build_filter_config(args)
            # Invalid date should be None; if no other filters, returns None
            assert fc is None

    def test_media_type_uppercased(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--media-type", "video"
        ]):
            args = parse_args()
            fc = build_filter_config(args)
            assert fc is not None
            assert fc.media_type == "VIDEO"
