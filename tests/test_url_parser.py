"""Tests for meta_ads_collector.url_parser."""

import sys
from unittest.mock import MagicMock, patch

from meta_ads_collector.cli import parse_args
from meta_ads_collector.events import EventEmitter
from meta_ads_collector.url_parser import extract_page_id_from_url

# ---------------------------------------------------------------------------
# extract_page_id_from_url
# ---------------------------------------------------------------------------

class TestExtractPageIdFromUrl:
    """URL parsing: all formats including edge cases."""

    # -- Ad Library URLs --

    def test_ad_library_url_with_view_all_page_id(self):
        url = "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_ad_library_url_view_all_page_id_only_param(self):
        url = "https://www.facebook.com/ads/library/?view_all_page_id=9876543210"
        assert extract_page_id_from_url(url) == "9876543210"

    def test_ad_library_url_with_extra_params(self):
        url = (
            "https://www.facebook.com/ads/library/"
            "?active_status=all&ad_type=all&country=US"
            "&view_all_page_id=555555&q=test&media_type=all"
        )
        assert extract_page_id_from_url(url) == "555555"

    # -- Profile URLs --

    def test_profile_url_with_id(self):
        url = "https://www.facebook.com/profile.php?id=123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_profile_url_with_extra_params(self):
        url = "https://www.facebook.com/profile.php?id=999999&ref=ts"
        assert extract_page_id_from_url(url) == "999999"

    # -- Direct numeric page URLs --

    def test_direct_numeric_url(self):
        url = "https://www.facebook.com/123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_direct_numeric_url_trailing_slash(self):
        url = "https://www.facebook.com/123456/"
        assert extract_page_id_from_url(url) == "123456"

    def test_mobile_numeric_url(self):
        url = "https://m.facebook.com/123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_http_numeric_url(self):
        url = "http://www.facebook.com/123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_numeric_url_long_id(self):
        url = "https://www.facebook.com/100044567890123"
        assert extract_page_id_from_url(url) == "100044567890123"

    # -- Pages path with numeric ID --

    def test_pages_path_with_numeric_id(self):
        url = "https://www.facebook.com/pages/SomeName/123456"
        assert extract_page_id_from_url(url) == "123456"

    # -- Vanity URLs (cannot resolve without network) --

    def test_vanity_url_returns_none(self):
        url = "https://www.facebook.com/CocaCola"
        assert extract_page_id_from_url(url) is None

    def test_vanity_url_with_trailing_slash(self):
        url = "https://www.facebook.com/CocaCola/"
        assert extract_page_id_from_url(url) is None

    def test_vanity_url_mobile(self):
        url = "https://m.facebook.com/CocaCola"
        assert extract_page_id_from_url(url) is None

    # -- Edge cases --

    def test_empty_string(self):
        assert extract_page_id_from_url("") is None

    def test_none_input(self):
        assert extract_page_id_from_url(None) is None

    def test_whitespace_only(self):
        assert extract_page_id_from_url("   ") is None

    def test_non_facebook_url(self):
        assert extract_page_id_from_url("https://www.google.com/123456") is None

    def test_bare_numeric_id(self):
        """A bare numeric string should be returned as-is."""
        assert extract_page_id_from_url("123456") == "123456"

    def test_non_url_text(self):
        assert extract_page_id_from_url("not a url at all") is None

    def test_facebook_root_url(self):
        assert extract_page_id_from_url("https://www.facebook.com/") is None

    def test_facebook_url_without_scheme(self):
        """URL without http/https should still work."""
        assert extract_page_id_from_url("www.facebook.com/123456") == "123456"

    def test_web_facebook_domain(self):
        url = "https://web.facebook.com/123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_business_facebook_domain(self):
        url = "https://business.facebook.com/123456"
        assert extract_page_id_from_url(url) == "123456"

    def test_short_numeric_path_ignored(self):
        """Very short numeric paths (< 5 digits) are not page IDs."""
        url = "https://www.facebook.com/123"
        assert extract_page_id_from_url(url) is None

    def test_non_string_input(self):
        assert extract_page_id_from_url(12345) is None

    def test_url_with_fragment(self):
        url = "https://www.facebook.com/123456#section"
        assert extract_page_id_from_url(url) == "123456"


# ---------------------------------------------------------------------------
# Collector: collect_by_page_id, collect_by_page_url
# ---------------------------------------------------------------------------

class TestCollectorPageMethods:
    def test_collect_by_page_id_delegates_to_search(self):
        from meta_ads_collector.collector import MetaAdsCollector
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.event_emitter = EventEmitter()
        collector.stats = {
            "requests_made": 0, "ads_collected": 0, "pages_fetched": 0,
            "errors": 0, "start_time": None, "end_time": None,
        }

        # Mock search_ads to return empty results and no cursor
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}},
            None,
        )
        collector.client._initialized = True

        ads = list(collector.collect_by_page_id("12345", country="US"))
        assert ads == []

        # Verify search_ads was called with page_ids=["12345"]
        call_kwargs = collector.client.search_ads.call_args
        assert call_kwargs is not None
        assert call_kwargs[1]["page_ids"] == ["12345"]

    def test_collect_by_page_url_with_valid_url(self):
        from meta_ads_collector.collector import MetaAdsCollector
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.event_emitter = EventEmitter()
        collector.stats = {
            "requests_made": 0, "ads_collected": 0, "pages_fetched": 0,
            "errors": 0, "start_time": None, "end_time": None,
        }
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}},
            None,
        )

        url = "https://www.facebook.com/ads/library/?view_all_page_id=99999"
        ads = list(collector.collect_by_page_url(url, country="US"))
        assert ads == []

        call_kwargs = collector.client.search_ads.call_args
        assert call_kwargs is not None
        assert call_kwargs[1]["page_ids"] == ["99999"]

    def test_collect_by_page_url_vanity_returns_empty(self):
        from meta_ads_collector.collector import MetaAdsCollector
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()

        url = "https://www.facebook.com/CocaCola"
        ads = list(collector.collect_by_page_url(url, country="US"))
        assert ads == []
        # search_ads should NOT have been called
        collector.client.search_ads.assert_not_called()


# ---------------------------------------------------------------------------
# CLI: --page-url and --page-name flags
# ---------------------------------------------------------------------------

class TestPageCollectionCLI:
    def test_page_url_flag_parsed(self):
        with patch.object(sys, "argv", [
            "prog", "--page-url", "https://www.facebook.com/123456", "-o", "out.json"
        ]):
            args = parse_args()
            assert args.page_url == "https://www.facebook.com/123456"

    def test_page_name_flag_parsed(self):
        with patch.object(sys, "argv", [
            "prog", "--page-name", "Coca-Cola", "-o", "out.json"
        ]):
            args = parse_args()
            assert args.page_name == "Coca-Cola"

    def test_page_url_default_none(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.page_url is None

    def test_page_name_default_none(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.page_name is None
