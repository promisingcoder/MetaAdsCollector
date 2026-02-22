"""Edge-case and coverage-gap tests for core modules.

Targets coverage gaps identified during the Step 6 audit:
- client.py: token extraction edge cases, doc_id extraction, session
  lifecycle, GraphQL payload building, response parsing
- collector.py: search loop edge cases, collect_by_page_*, enrich_ad,
  get_stats, context manager
- models.py: old-format parsing, date parsing, camelCase fields,
  missing/malformed data, TargetingInfo, to_dict edge cases
- filters.py: MEME media type, timezone-aware date comparisons
- media.py: empty download result, extension fallback from response
- url_parser.py: parse exception path, bare numeric IDs
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from curl_cffi.requests import Session as CffiSession

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.exceptions import (
    SessionExpiredError,
)
from meta_ads_collector.filters import FilterConfig, _strip_tz, passes_filter
from meta_ads_collector.media import MediaDownloader
from meta_ads_collector.models import (
    Ad,
    AdCreative,
    AudienceDistribution,
    ImpressionRange,
    PageInfo,
    PageSearchResult,
    SpendRange,
    TargetingInfo,
)
from meta_ads_collector.url_parser import extract_page_id_from_url

# =========================================================================
# client.py edge cases
# =========================================================================


class TestClientTokenExtraction:
    """Cover additional token extraction patterns in _extract_tokens."""

    def _client(self) -> MetaAdsClient:
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_extract_dtsg_token(self):
        """DTSGInitialData token extraction."""
        client = self._client()
        html = '"DTSGInitialData",[],{"token":"dtsg_abc123"}'
        tokens = client._extract_tokens(html)
        assert tokens["fb_dtsg"] == "dtsg_abc123"

    def test_extract_hs_token(self):
        """__hs token extraction."""
        client = self._client()
        html = '"__hs":"hs_value_123"'
        tokens = client._extract_tokens(html)
        assert tokens["__hs"] == "hs_value_123"

    def test_extract_hsdp_token(self):
        """__hsdp token extraction."""
        client = self._client()
        html = '"__hsdp":"hsdp_value"'
        tokens = client._extract_tokens(html)
        assert tokens["__hsdp"] == "hsdp_value"

    def test_extract_hblp_token(self):
        """__hblp token extraction."""
        client = self._client()
        html = '"__hblp":"hblp_value"'
        tokens = client._extract_tokens(html)
        assert tokens["__hblp"] == "hblp_value"

    def test_extract_comet_req(self):
        """__comet_req numeric token extraction."""
        client = self._client()
        html = '"__comet_req":99'
        tokens = client._extract_tokens(html)
        assert tokens["__comet_req"] == "99"

    def test_extract_jazoest_from_html(self):
        """jazoest extraction from HTML page."""
        client = self._client()
        html = '"jazoest":28459'
        tokens = client._extract_tokens(html)
        assert tokens["jazoest"] == "28459"

    def test_extract_lsd_third_pattern(self):
        """LSD token via 'lsd' JSON key pattern."""
        client = self._client()
        html = '"lsd":"lsd_json_value"'
        tokens = client._extract_tokens(html)
        assert tokens["lsd"] == "lsd_json_value"

    def test_extract_rev_server_revision_pattern(self):
        """__rev via 'server_revision' pattern."""
        client = self._client()
        html = '"server_revision":9876543'
        tokens = client._extract_tokens(html)
        assert tokens["__rev"] == "9876543"

    def test_extract_rev_revision_pattern(self):
        """__rev via 'revision' pattern."""
        client = self._client()
        html = '"revision":1111111'
        tokens = client._extract_tokens(html)
        assert tokens["__rev"] == "1111111"


class TestClientDocIdExtraction:
    """Cover _extract_doc_ids with various patterns."""

    def _client(self) -> MetaAdsClient:
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_none_html_returns_empty(self):
        """None HTML returns empty dict."""
        client = self._client()
        result = client._extract_doc_ids(None)
        assert result == {}

    def test_empty_html_returns_empty(self):
        """Empty HTML returns empty dict."""
        client = self._client()
        result = client._extract_doc_ids("")
        assert result == {}

    def test_pattern2_extraction(self):
        """Pattern 2: name/queryID near each other."""
        client = self._client()
        html = '"name":"AdLibrarySearchPaginationQuery","extra":"data","queryID":"1234567890123"'
        result = client._extract_doc_ids(html)
        assert result.get("AdLibrarySearchPaginationQuery") == "1234567890123"

    def test_pattern3_extraction(self):
        """Pattern 3: queryID before name."""
        client = self._client()
        html = '"queryID":"9876543210123","extra":"data","name":"AdLibrarySearchPaginationQuery"'
        result = client._extract_doc_ids(html)
        assert result.get("AdLibrarySearchPaginationQuery") == "9876543210123"

    def test_no_match_returns_empty(self):
        """HTML with no matching patterns returns empty dict."""
        client = self._client()
        html = '<html><body>No GraphQL doc_ids here</body></html>'
        result = client._extract_doc_ids(html)
        assert result == {}


class TestClientVerifyTokens:
    """Cover _verify_tokens edge cases."""

    def _client(self) -> MetaAdsClient:
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_missing_lsd_generates_fallback(self):
        """Missing LSD token should be auto-generated."""
        client = self._client()
        client._tokens = {}
        client._verify_tokens()
        assert "lsd" in client._tokens
        assert len(client._tokens["lsd"]) >= 8

    def test_empty_lsd_generates_fallback(self):
        """Empty string LSD token should be auto-generated."""
        client = self._client()
        client._tokens = {"lsd": ""}
        client._verify_tokens()
        assert client._tokens["lsd"]
        assert len(client._tokens["lsd"]) >= 8

    def test_valid_lsd_no_optional_tokens(self):
        """Valid LSD token with missing optional tokens should not raise."""
        client = self._client()
        client._tokens = {"lsd": "valid_token_12345"}
        # Should log warnings about fb_dtsg/jazoest but not raise
        client._verify_tokens()

    def test_valid_lsd_with_optional_tokens(self):
        """Valid LSD and optional tokens should pass cleanly."""
        client = self._client()
        client._tokens = {
            "lsd": "valid_token_12345",
            "fb_dtsg": "dtsg_value",
            "jazoest": "28459",
        }
        client._verify_tokens()


class TestClientHelpers:
    """Cover helper methods: generate_session_id, collation_token, datr."""

    def _client(self) -> MetaAdsClient:
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_generate_session_id_format(self):
        """Session ID should be a valid UUID format."""
        client = self._client()
        sid = client._generate_session_id()
        assert len(sid) == 36
        assert sid.count("-") == 4

    def test_generate_collation_token_format(self):
        """Collation token should be a valid UUID format."""
        client = self._client()
        ct = client._generate_collation_token()
        assert len(ct) == 36
        assert ct.count("-") == 4

    def test_generate_datr_length(self):
        """datr cookie value should be 24 characters."""
        client = self._client()
        datr = client._generate_datr()
        assert len(datr) == 24

    def test_generate_short_id_format(self):
        """Short ID should be in format xxx:xxx:xxx."""
        client = self._client()
        sid = client._generate_short_id()
        parts = sid.split(":")
        assert len(parts) == 3
        for part in parts:
            assert len(part) == 6

    def test_is_session_stale_no_init_time(self):
        """Session should be stale when _init_time is None."""
        client = self._client()
        client._init_time = None
        assert client._is_session_stale() is True

    def test_is_session_stale_fresh(self):
        """Session should not be stale immediately after init."""
        client = self._client()
        client._init_time = time.time()
        client._max_session_age = 1800
        assert client._is_session_stale() is False

    def test_is_session_stale_expired(self):
        """Session should be stale when age exceeds max."""
        client = self._client()
        client._init_time = time.time() - 2000
        client._max_session_age = 1800
        assert client._is_session_stale() is True


class TestClientContextManager:
    """Cover __enter__/__exit__."""

    def test_enter_returns_self(self):
        """__enter__ should return the client instance."""
        client = MetaAdsClient.__new__(MetaAdsClient)
        client.session = CffiSession(impersonate="chrome")
        client._initialized = False
        result = client.__enter__()
        assert result is client
        client.session.close()

    def test_exit_closes_session(self):
        """__exit__ should close the session and mark as uninitialized."""
        client = MetaAdsClient.__new__(MetaAdsClient)
        client.session = CffiSession(impersonate="chrome")
        client._initialized = True
        client.__exit__(None, None, None)
        assert client._initialized is False


class TestClientBuildGraphqlPayload:
    """Cover _build_graphql_payload construction."""

    def test_payload_has_required_keys(self):
        """Payload should contain all required GraphQL form fields."""
        client = MetaAdsClient.__new__(MetaAdsClient)
        client._tokens = {
            "lsd": "test_lsd",
            "__rev": "12345",
            "__spin_r": "12345",
            "__spin_t": "1700000000",
            "__spin_b": "trunk",
            "__hsi": "99999",
            "__dyn": "dyn_val",
            "__csr": "csr_val",
            "__hs": "hs_val",
            "__comet_req": "1",
        }
        client._request_counter = 0
        client._fingerprint = MagicMock()

        payload = client._build_graphql_payload(
            doc_id="12345",
            variables={"queryString": "test"},
            friendly_name="TestQuery",
        )

        assert payload["lsd"] == "test_lsd"
        assert payload["doc_id"] == "12345"
        assert payload["fb_api_req_friendly_name"] == "TestQuery"
        assert payload["fb_api_caller_class"] == "RelayModern"
        assert "variables" in payload
        assert payload["__dyn"] == "dyn_val"
        assert payload["__csr"] == "csr_val"

    def test_payload_includes_hsdp_hblp_when_present(self):
        """Optional __hsdp/__hblp tokens should be included when available."""
        client = MetaAdsClient.__new__(MetaAdsClient)
        client._tokens = {
            "lsd": "test_lsd",
            "__hsdp": "hsdp_val",
            "__hblp": "hblp_val",
        }
        client._request_counter = 0
        client._fingerprint = MagicMock()

        payload = client._build_graphql_payload(
            doc_id="12345",
            variables={},
            friendly_name="TestQuery",
        )

        assert payload["__hsdp"] == "hsdp_val"
        assert payload["__hblp"] == "hblp_val"


class TestClientParseSearchResponse:
    """Cover _parse_search_response edge cases."""

    def _client(self) -> MetaAdsClient:
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_empty_data_returns_empty(self):
        """Empty data should return empty ads list."""
        client = self._client()
        result, cursor = client._parse_search_response({})
        assert result["ads"] == []
        assert cursor is None

    def test_camelcase_alternative_structure(self):
        """Should handle camelCase response structure."""
        client = self._client()
        data = {
            "data": {
                "adLibraryMain": {
                    "searchResultsConnection": {
                        "edges": [],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                }
            }
        }
        result, cursor = client._parse_search_response(data)
        assert result["ads"] == []
        assert cursor is None

    def test_has_next_page_returns_cursor(self):
        """When has_next_page is true, should return end_cursor."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "search_results_connection": {
                        "edges": [],
                        "page_info": {
                            "has_next_page": True,
                            "end_cursor": "cursor_abc",
                        },
                    }
                }
            }
        }
        result, cursor = client._parse_search_response(data)
        assert cursor == "cursor_abc"

    def test_exception_returns_empty(self):
        """Exceptions during parsing should return empty result."""
        client = self._client()
        # Force an exception by passing a non-dict
        result, cursor = client._parse_search_response({"data": "not_a_dict"})
        assert result["ads"] == []
        assert cursor is None


class TestClientParseTypeaheadResponse:
    """Cover _parse_typeahead_response edge cases."""

    def _client(self) -> MetaAdsClient:
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_empty_data_returns_empty(self):
        """Empty data should return empty page list."""
        client = self._client()
        result = client._parse_typeahead_response({})
        assert result == []

    def test_camelcase_structure(self):
        """Should handle camelCase typeahead structure."""
        client = self._client()
        data = {
            "data": {
                "adLibraryMain": {
                    "typeaheadSuggestions": [
                        {"pageID": "123", "pageName": "Test"},
                    ]
                }
            }
        }
        result = client._parse_typeahead_response(data)
        assert len(result) == 1
        assert result[0]["page_id"] == "123"

    def test_edge_node_structure(self):
        """Should handle edges/node wrapped typeahead structure."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions_connection": {
                        "edges": [
                            {
                                "node": {
                                    "page_id": "456",
                                    "page_name": "Edge Page",
                                }
                            }
                        ]
                    }
                }
            }
        }
        result = client._parse_typeahead_response(data)
        assert len(result) == 1
        assert result[0]["page_id"] == "456"

    def test_missing_page_id_skipped(self):
        """Pages without a page_id should be skipped."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": [
                        {"page_name": "No ID Page"},
                    ]
                }
            }
        }
        result = client._parse_typeahead_response(data)
        assert len(result) == 0


class TestClientRefreshSession:
    """Cover _refresh_session edge cases."""

    def test_max_refresh_failures_raises(self):
        """Should raise SessionExpiredError when max failures exceeded."""
        client = MetaAdsClient.__new__(MetaAdsClient)
        client._consecutive_refresh_failures = 3
        client.max_refresh_attempts = 3
        with pytest.raises(SessionExpiredError, match="refresh failed"):
            client._refresh_session()


# =========================================================================
# collector.py edge cases
# =========================================================================


class TestCollectorContextManager:
    """Cover __enter__/__exit__ for MetaAdsCollector."""

    def test_enter_returns_self(self):
        """__enter__ should return the collector instance."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        result = collector.__enter__()
        assert result is collector

    def test_exit_closes_client(self):
        """__exit__ should close the underlying client."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.__exit__(None, None, None)
        collector.client.close.assert_called_once()


class TestCollectorGetStats:
    """Cover get_stats method."""

    def test_stats_with_no_times(self):
        """get_stats should work with no start/end times."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.stats = {
            "requests_made": 5,
            "ads_collected": 10,
            "pages_fetched": 2,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }
        stats = collector.get_stats()
        assert stats["requests_made"] == 5
        assert "duration_seconds" not in stats

    def test_stats_with_times_includes_duration(self):
        """get_stats should compute duration when times are present."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 30)
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.stats = {
            "requests_made": 5,
            "ads_collected": 10,
            "pages_fetched": 2,
            "errors": 0,
            "start_time": start,
            "end_time": end,
        }
        stats = collector.get_stats()
        assert stats["duration_seconds"] == 30.0
        assert stats["ads_per_second"] == pytest.approx(10 / 30.0)


class TestCollectorSearchPages:
    """Cover search_pages method."""

    def test_search_pages_returns_page_search_results(self):
        """search_pages should return PageSearchResult objects."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_pages.return_value = [
            {
                "page_id": "12345",
                "page_name": "Test Brand",
                "page_profile_uri": "https://facebook.com/testbrand",
                "page_alias": "testbrand",
                "page_logo_url": "https://example.com/logo.jpg",
                "page_verified": True,
                "page_like_count": 50000,
                "category": "Brand",
            }
        ]
        results = collector.search_pages("test")
        assert len(results) == 1
        assert isinstance(results[0], PageSearchResult)
        assert results[0].page_id == "12345"
        assert results[0].page_name == "Test Brand"

    def test_search_pages_skips_empty_page_id(self):
        """Pages with empty page_id should be skipped."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_pages.return_value = [
            {"page_id": "", "page_name": "No ID"},
        ]
        results = collector.search_pages("test")
        assert len(results) == 0

    def test_search_pages_handles_parse_error(self):
        """Parsing errors should be logged and skipped."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        # This will cause a parse error because required field page_id is missing
        collector.client.search_pages.return_value = [
            {"page_name": "No ID Field"},
        ]
        results = collector.search_pages("test")
        # Should either skip (empty page_id) or return with empty id
        assert all(r.page_id for r in results)


class TestCollectorCollectByPageUrl:
    """Cover collect_by_page_url method."""

    def test_invalid_url_returns_empty(self):
        """Invalid URL should log warning and return empty iterator."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        ads = list(collector.collect_by_page_url("https://notfacebook.com/page"))
        assert ads == []

    def test_valid_url_delegates_to_search(self):
        """Valid URL should extract page ID and call search."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()

        # Mock the search method
        sample_ad = Ad(id="test-ad-1")
        with (
            patch.object(collector, "search", return_value=iter([sample_ad])),
            patch.object(collector, "collect_by_page_id", return_value=iter([sample_ad])),
        ):
            url = "https://www.facebook.com/ads/library/?view_all_page_id=12345"
            ads = list(collector.collect_by_page_url(url))
            assert len(ads) == 1


class TestCollectorCollectByPageName:
    """Cover collect_by_page_name method."""

    def test_no_pages_found_returns_empty(self):
        """When no pages match, should return empty iterator."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_pages.return_value = []
        ads = list(collector.collect_by_page_name("nonexistent_page_xyz"))
        assert ads == []


class TestCollectorEnrichAd:
    """Cover enrich_ad method."""

    def test_enrich_returns_original_on_not_implemented(self):
        """When detail fetch raises NotImplementedError, return original ad."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.get_ad_details.side_effect = NotImplementedError("no data")

        ad = Ad(id="test-1", page=PageInfo(id="pg-1", name="Test"))
        result = collector.enrich_ad(ad)
        assert result is ad  # same object returned

    def test_enrich_returns_original_on_exception(self):
        """When detail fetch raises any exception, return original ad."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.get_ad_details.side_effect = Exception("network error")

        ad = Ad(id="test-1", page=PageInfo(id="pg-1", name="Test"))
        result = collector.enrich_ad(ad)
        assert result is ad

    def test_enrich_merges_new_fields(self):
        """Enrichment should fill in missing fields from detail data."""
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.get_ad_details.return_value = {
            "ad_archive_id": "test-1",
            "page_id": "pg-1",
            "page_name": "Test",
            "funding_entity": "Test Corp",
            "disclaimer": "Paid for by Test Corp",
            "publisher_platforms": ["facebook", "instagram"],
        }

        ad = Ad(id="test-1", page=PageInfo(id="pg-1", name="Test"))
        result = collector.enrich_ad(ad)
        assert result.funding_entity == "Test Corp"
        assert result.disclaimer == "Paid for by Test Corp"
        assert result.publisher_platforms == ["facebook", "instagram"]


# =========================================================================
# models.py edge cases
# =========================================================================


class TestTargetingInfo:
    """Cover TargetingInfo.to_dict method (line 111)."""

    def test_to_dict(self):
        """TargetingInfo should serialize all fields."""
        ti = TargetingInfo(
            age_min=18,
            age_max=65,
            genders=["male", "female"],
            locations=["US", "UK"],
        )
        d = ti.to_dict()
        assert d["age_min"] == 18
        assert d["age_max"] == 65
        assert "male" in d["genders"]


class TestAdFromGraphqlOldFormat:
    """Cover old-format creative parsing in from_graphql_response."""

    def test_old_format_with_link_captions_and_descriptions(self):
        """Old format with ad_creative_link_captions and link_descriptions."""
        data = {
            "ad_archive_id": "OLD-001",
            "page_id": "pg-old",
            "page_name": "Old Format Page",
            "ad_creative_bodies": ["Body 1", "Body 2"],
            "ad_creative_link_captions": ["Caption 1"],
            "ad_creative_link_descriptions": ["Desc 1"],
            "ad_creative_link_titles": ["Title 1"],
        }
        ad = Ad.from_graphql_response(data)
        assert len(ad.creatives) == 2
        assert ad.creatives[0].body == "Body 1"
        assert ad.creatives[0].caption == "Caption 1"
        assert ad.creatives[0].description == "Desc 1"
        assert ad.creatives[0].title == "Title 1"
        assert ad.creatives[1].body == "Body 2"
        # Second creative lacks caption/desc/title (index out of range)
        assert ad.creatives[1].caption is None

    def test_old_format_with_snapshot_cards(self):
        """Old format where media comes from snapshot.cards."""
        data = {
            "ad_archive_id": "SNAP-001",
            "page_id": "pg-snap",
            "page_name": "Snapshot Page",
            "ad_creative_bodies": ["Body text"],
            "snapshot": {
                "cards": [
                    {
                        "resized_image_url": "https://example.com/resized.jpg",
                        "video_hd_url": "https://example.com/hd.mp4",
                        "video_sd_url": "https://example.com/sd.mp4",
                        "link_url": "https://example.com/landing",
                        "cta_text": "Learn More",
                        "cta_type": "LEARN_MORE",
                    }
                ]
            },
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].image_url == "https://example.com/resized.jpg"
        assert ad.creatives[0].video_hd_url == "https://example.com/hd.mp4"
        assert ad.creatives[0].video_sd_url == "https://example.com/sd.mp4"
        assert ad.creatives[0].link_url == "https://example.com/landing"
        assert ad.creatives[0].cta_text == "Learn More"
        assert ad.creatives[0].cta_type == "LEARN_MORE"


class TestAdDateParsing:
    """Cover date parsing edge cases in from_graphql_response."""

    def test_iso_string_date(self):
        """Date as ISO 8601 string."""
        data = {
            "ad_archive_id": "DATE-001",
            "ad_delivery_start_time": "2024-06-15T10:30:00",
        }
        ad = Ad.from_graphql_response(data)
        assert ad.delivery_start_time == datetime(2024, 6, 15, 10, 30, 0)

    def test_iso_string_with_z_suffix(self):
        """Date as ISO 8601 string with Z suffix."""
        data = {
            "ad_archive_id": "DATE-002",
            "ad_delivery_start_time": "2024-06-15T10:30:00Z",
        }
        ad = Ad.from_graphql_response(data)
        assert ad.delivery_start_time is not None

    def test_invalid_date_returns_none(self):
        """Invalid date string should be silently handled."""
        data = {
            "ad_archive_id": "DATE-003",
            "ad_delivery_start_time": "not-a-date",
        }
        ad = Ad.from_graphql_response(data)
        assert ad.delivery_start_time is None

    def test_stop_time_integer(self):
        """Stop time as integer timestamp."""
        data = {
            "ad_archive_id": "DATE-004",
            "ad_delivery_stop_time": 1700000000,
        }
        ad = Ad.from_graphql_response(data)
        assert ad.delivery_stop_time is not None
        assert isinstance(ad.delivery_stop_time, datetime)

    def test_stop_time_iso_string(self):
        """Stop time as ISO string."""
        data = {
            "ad_archive_id": "DATE-005",
            "ad_delivery_stop_time": "2024-12-31T23:59:59",
        }
        ad = Ad.from_graphql_response(data)
        assert ad.delivery_stop_time == datetime(2024, 12, 31, 23, 59, 59)


class TestAdCamelCaseFields:
    """Cover camelCase alternative field names."""

    def test_camelcase_creative_bodies(self):
        """Should parse adCreativeBodies field."""
        data = {
            "adArchiveID": "CAMEL-001",
            "adCreativeBodies": ["Camel body"],
            "adCreativeLinkTitles": ["Camel title"],
            "adCreativeLinkCaptions": ["Camel caption"],
            "adCreativeLinkDescriptions": ["Camel desc"],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.id == "CAMEL-001"
        assert ad.creatives[0].body == "Camel body"
        assert ad.creatives[0].title == "Camel title"

    def test_camelcase_impressions(self):
        """Should parse impressionsWithIndex field."""
        data = {
            "ad_archive_id": "CAMEL-002",
            "impressionsWithIndex": {
                "lowerBound": 100,
                "upperBound": 500,
            },
        }
        ad = Ad.from_graphql_response(data)
        assert ad.impressions is not None
        assert ad.impressions.lower_bound == 100
        assert ad.impressions.upper_bound == 500

    def test_camelcase_spend(self):
        """Should parse spendWithIndex field."""
        data = {
            "ad_archive_id": "CAMEL-003",
            "spendWithIndex": {
                "lowerBound": 50,
                "upperBound": 200,
            },
        }
        ad = Ad.from_graphql_response(data)
        assert ad.spend is not None
        assert ad.spend.lower_bound == 50

    def test_camelcase_publisher_platforms(self):
        """Should parse publisherPlatforms field."""
        data = {
            "ad_archive_id": "CAMEL-004",
            "publisherPlatforms": ["facebook"],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.publisher_platforms == ["facebook"]

    def test_publisher_platforms_as_string(self):
        """Publisher platforms as a string should be wrapped in list."""
        data = {
            "ad_archive_id": "PLAT-001",
            "publisher_platforms": "facebook",
        }
        ad = Ad.from_graphql_response(data)
        assert ad.publisher_platforms == ["facebook"]


class TestAdActiveStatus:
    """Cover is_active determination logic."""

    def test_is_active_from_field(self):
        """is_active directly from the data."""
        data = {"ad_archive_id": "ACT-001", "is_active": True}
        ad = Ad.from_graphql_response(data)
        assert ad.is_active is True

    def test_is_active_from_ad_status(self):
        """is_active inferred from ad_status field."""
        data = {"ad_archive_id": "ACT-002", "ad_status": "ACTIVE"}
        ad = Ad.from_graphql_response(data)
        assert ad.is_active is True

    def test_is_active_inactive_from_ad_status(self):
        """is_active=False inferred from non-ACTIVE ad_status."""
        data = {"ad_archive_id": "ACT-003", "ad_status": "INACTIVE"}
        ad = Ad.from_graphql_response(data)
        assert ad.is_active is False


class TestAdEstimatedAudienceSize:
    """Cover estimated_audience_size parsing."""

    def test_estimated_audience_size(self):
        """Should parse estimated_audience_size with bounds."""
        data = {
            "ad_archive_id": "AUD-001",
            "estimated_audience_size": {
                "lower_bound": 1000,
                "upper_bound": 5000,
            },
        }
        ad = Ad.from_graphql_response(data)
        assert ad.estimated_audience_size_lower == 1000
        assert ad.estimated_audience_size_upper == 5000

    def test_no_estimated_audience_size(self):
        """Missing audience size should default to None."""
        data = {"ad_archive_id": "AUD-002"}
        ad = Ad.from_graphql_response(data)
        assert ad.estimated_audience_size_lower is None
        assert ad.estimated_audience_size_upper is None


class TestAdToDict:
    """Cover to_dict edge cases."""

    def test_to_dict_with_targeting(self):
        """Ad with targeting info should include it in dict."""
        ad = Ad(
            id="TARG-001",
            targeting=TargetingInfo(age_min=18, age_max=65),
        )
        d = ad.to_dict()
        assert d["targeting"]["age_min"] == 18

    def test_to_dict_with_estimated_audience_size(self):
        """Ad with estimated audience should include it."""
        ad = Ad(
            id="AUD-001",
            estimated_audience_size_lower=1000,
            estimated_audience_size_upper=5000,
        )
        d = ad.to_dict()
        assert d["estimated_audience_size"]["lower_bound"] == 1000

    def test_to_dict_with_reach(self):
        """Ad with reach data should include it."""
        ad = Ad(
            id="REACH-001",
            reach=ImpressionRange(lower_bound=500, upper_bound=1000),
        )
        d = ad.to_dict()
        assert d["reach"]["lower_bound"] == 500

    def test_to_dict_no_page(self):
        """Ad without page should have None page in dict."""
        ad = Ad(id="NOPG-001", page=None)
        d = ad.to_dict()
        assert d["page"] is None

    def test_to_dict_with_raw_data_excluded_when_none(self):
        """raw_data=None + include_raw=True should not include raw_data."""
        ad = Ad(id="RAW-001", raw_data=None)
        d = ad.to_dict(include_raw=True)
        assert "raw_data" not in d


class TestPageSearchResultToDict:
    """Cover PageSearchResult.to_dict."""

    def test_to_dict_full(self):
        """Full PageSearchResult should serialize all fields."""
        psr = PageSearchResult(
            page_id="123",
            page_name="Test",
            page_profile_uri="https://facebook.com/test",
            page_alias="test",
            page_logo_url="https://example.com/logo.jpg",
            page_verified=True,
            page_like_count=50000,
            category="Brand",
        )
        d = psr.to_dict()
        assert d["page_id"] == "123"
        assert d["page_like_count"] == 50000


class TestAudienceDistributionToDict:
    """Cover AudienceDistribution.to_dict."""

    def test_to_dict(self):
        """AudienceDistribution should serialize correctly."""
        ad = AudienceDistribution(category="25-34_male", percentage=0.35)
        d = ad.to_dict()
        assert d["category"] == "25-34_male"
        assert d["percentage"] == 0.35


# =========================================================================
# filters.py edge cases
# =========================================================================


class TestFiltersMemeType:
    """Cover MEME media type filter (line 144)."""

    def test_meme_filter_passes_with_image(self):
        """MEME filter should pass when ad has image."""
        ad = Ad(
            id="MEME-001",
            creatives=[AdCreative(image_url="https://example.com/meme.jpg")],
        )
        fc = FilterConfig(media_type="MEME")
        assert passes_filter(ad, fc) is True

    def test_meme_filter_fails_without_image(self):
        """MEME filter should fail when ad has no image."""
        ad = Ad(
            id="MEME-002",
            creatives=[AdCreative(body="text only")],
        )
        fc = FilterConfig(media_type="MEME")
        assert passes_filter(ad, fc) is False


class TestFiltersStripTz:
    """Cover _strip_tz helper (line 190)."""

    def test_strip_tz_aware_datetime(self):
        """Should strip timezone from aware datetime."""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = _strip_tz(dt)
        assert result.tzinfo is None
        assert result == datetime(2024, 1, 1, 12, 0, 0)

    def test_strip_tz_naive_datetime(self):
        """Should return naive datetime unchanged."""
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = _strip_tz(dt)
        assert result is dt

    def test_date_filter_with_timezone_aware_ad(self):
        """Date filter with timezone-aware ad delivery time."""
        ad = Ad(
            id="TZ-001",
            delivery_start_time=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )
        fc = FilterConfig(start_date=datetime(2024, 1, 1))
        assert passes_filter(ad, fc) is True


# =========================================================================
# url_parser.py edge cases
# =========================================================================


class TestUrlParserEdgeCases:
    """Cover url_parser.py edge cases."""

    def test_bare_numeric_id(self):
        """Bare numeric string should return as-is."""
        assert extract_page_id_from_url("12345678") == "12345678"

    def test_none_input(self):
        """None should return None."""
        assert extract_page_id_from_url(None) is None  # type: ignore[arg-type]

    def test_non_string_input(self):
        """Non-string should return None."""
        assert extract_page_id_from_url(12345) is None  # type: ignore[arg-type]

    def test_empty_string(self):
        """Empty string should return None."""
        assert extract_page_id_from_url("") is None

    def test_whitespace_only(self):
        """Whitespace string should return None."""
        assert extract_page_id_from_url("   ") is None

    def test_non_facebook_url(self):
        """Non-Facebook URL should return None."""
        assert extract_page_id_from_url("https://www.google.com/12345") is None

    def test_facebook_url_no_path(self):
        """Facebook URL with no path should return None."""
        assert extract_page_id_from_url("https://www.facebook.com/") is None

    def test_vanity_url(self):
        """Vanity URL (non-numeric username) should return None."""
        assert extract_page_id_from_url("https://www.facebook.com/CocaCola") is None

    def test_url_without_scheme(self):
        """URL without scheme should be handled."""
        result = extract_page_id_from_url("www.facebook.com/ads/library/?view_all_page_id=12345")
        assert result == "12345"

    def test_mobile_facebook(self):
        """Mobile Facebook URL should work."""
        result = extract_page_id_from_url("https://m.facebook.com/12345678")
        assert result == "12345678"

    def test_profile_php_url(self):
        """Profile URL with id parameter should work."""
        result = extract_page_id_from_url("https://www.facebook.com/profile.php?id=12345678")
        assert result == "12345678"

    def test_pages_path_with_trailing_numeric(self):
        """Pages path with trailing numeric ID should extract ID."""
        result = extract_page_id_from_url("https://www.facebook.com/pages/Test-Page/12345678")
        assert result == "12345678"

    def test_short_numeric_segment_ignored(self):
        """Numeric segments shorter than 5 digits should be ignored."""
        result = extract_page_id_from_url("https://www.facebook.com/1234")
        assert result is None


# =========================================================================
# media.py edge cases
# =========================================================================


class TestMediaEdgeCases:
    """Cover media.py edge cases."""

    def test_download_file_empty_response_retries(self, tmp_path):
        """Empty download (0 bytes) should retry."""
        session = MagicMock()
        downloader = MediaDownloader(output_dir=tmp_path, session=session, max_retries=2)

        # Both attempts return empty content
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b""]  # Empty chunk
        mock_response.raise_for_status.return_value = None
        session.get.return_value = mock_response

        filepath = tmp_path / "empty.jpg"
        with patch("meta_ads_collector.media.time.sleep"):
            success, error, size = downloader._download_file(
                "https://example.com/empty.jpg",
                filepath,
            )
        assert success is False
        assert "empty" in error.lower() or "0 bytes" in error.lower()

    def test_resolve_extension_no_url_ext_no_response(self):
        """Fallback to .bin when no extension is detectable."""
        downloader = MediaDownloader(output_dir="/tmp/test")
        ext = downloader._resolve_extension("https://example.com/file")
        assert ext == ".bin"


# =========================================================================
# SpendRange / ImpressionRange str edge cases
# =========================================================================


class TestRangeStrEdgeCases:
    """Cover __str__ methods for ranges with zero bounds."""

    def test_spend_range_with_zero_lower(self):
        """SpendRange with 0 lower_bound should display correctly (0 is a valid bound)."""
        sr = SpendRange(lower_bound=0, upper_bound=500, currency="USD")
        result = str(sr)
        assert result == "USD 0 - 500"

    def test_impression_range_with_zero_lower(self):
        """ImpressionRange with 0 lower_bound should display correctly."""
        ir = ImpressionRange(lower_bound=0, upper_bound=500)
        result = str(ir)
        assert result == "0 - 500"

    def test_spend_range_with_only_lower(self):
        """SpendRange with only lower_bound should show N/A."""
        sr = SpendRange(lower_bound=100)
        result = str(sr)
        assert result == "N/A"

    def test_impression_range_with_only_upper(self):
        """ImpressionRange with only upper_bound should show N/A."""
        ir = ImpressionRange(upper_bound=500)
        result = str(ir)
        assert result == "N/A"
