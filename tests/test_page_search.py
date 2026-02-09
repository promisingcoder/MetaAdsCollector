"""Tests for page search (typeahead) functionality."""

import json
import sys
from unittest.mock import MagicMock, patch

from meta_ads_collector.cli import parse_args
from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.models import PageSearchResult

# ---------------------------------------------------------------------------
# PageSearchResult model
# ---------------------------------------------------------------------------

class TestPageSearchResultModel:
    def test_create_minimal(self):
        result = PageSearchResult(page_id="12345", page_name="Test Page")
        assert result.page_id == "12345"
        assert result.page_name == "Test Page"
        assert result.page_profile_uri is None
        assert result.page_alias is None
        assert result.page_logo_url is None

    def test_create_full(self):
        result = PageSearchResult(
            page_id="12345",
            page_name="Coca-Cola",
            page_profile_uri="https://www.facebook.com/CocaCola",
            page_alias="CocaCola",
            page_logo_url="https://example.com/logo.png",
            page_verified=True,
            page_like_count=100000,
            category="Beverage company",
        )
        assert result.page_id == "12345"
        assert result.page_name == "Coca-Cola"
        assert result.page_verified is True
        assert result.page_like_count == 100000

    def test_to_dict(self):
        result = PageSearchResult(
            page_id="12345",
            page_name="Test",
            page_profile_uri="https://example.com",
        )
        d = result.to_dict()
        assert d["page_id"] == "12345"
        assert d["page_name"] == "Test"
        assert d["page_profile_uri"] == "https://example.com"
        assert d["page_alias"] is None


# ---------------------------------------------------------------------------
# Client: _parse_typeahead_response
# ---------------------------------------------------------------------------

class TestParseTypeaheadResponse:
    def _client(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        return client

    def test_standard_response_structure(self):
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": [
                        {
                            "page_id": "111",
                            "page_name": "Coca-Cola",
                            "page_profile_uri": "https://www.facebook.com/CocaCola",
                            "page_alias": "CocaCola",
                            "page_profile_picture_url": "https://example.com/logo.png",
                            "is_verified": True,
                            "page_like_count": 100000,
                            "category": "Beverage company",
                        },
                        {
                            "page_id": "222",
                            "page_name": "Coca-Cola Light",
                            "page_profile_uri": "https://www.facebook.com/CocaColaLight",
                        },
                    ]
                }
            }
        }
        pages = client._parse_typeahead_response(data)
        assert len(pages) == 2
        assert pages[0]["page_id"] == "111"
        assert pages[0]["page_name"] == "Coca-Cola"
        assert pages[0]["page_logo_url"] == "https://example.com/logo.png"
        assert pages[0]["page_verified"] is True
        assert pages[1]["page_id"] == "222"

    def test_camelcase_response_structure(self):
        client = self._client()
        data = {
            "data": {
                "adLibraryMain": {
                    "typeaheadSuggestions": [
                        {
                            "pageID": "333",
                            "pageName": "TestPage",
                            "pageProfileURI": "https://www.facebook.com/testpage",
                        }
                    ]
                }
            }
        }
        pages = client._parse_typeahead_response(data)
        assert len(pages) == 1
        assert pages[0]["page_id"] == "333"
        assert pages[0]["page_name"] == "TestPage"

    def test_edges_response_structure(self):
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions_connection": {
                        "edges": [
                            {
                                "node": {
                                    "page_id": "444",
                                    "page_name": "EdgePage",
                                }
                            }
                        ]
                    }
                }
            }
        }
        pages = client._parse_typeahead_response(data)
        assert len(pages) == 1
        assert pages[0]["page_id"] == "444"

    def test_empty_suggestions(self):
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": []
                }
            }
        }
        pages = client._parse_typeahead_response(data)
        assert pages == []

    def test_no_data(self):
        client = self._client()
        data = {}
        pages = client._parse_typeahead_response(data)
        assert pages == []

    def test_missing_page_id_filtered_out(self):
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": [
                        {"page_name": "No ID Page"},
                        {"page_id": "555", "page_name": "Has ID"},
                    ]
                }
            }
        }
        pages = client._parse_typeahead_response(data)
        assert len(pages) == 1
        assert pages[0]["page_id"] == "555"

    def test_gibberish_query_returns_empty(self):
        """Simulate a response for gibberish that returns no suggestions."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": []
                }
            }
        }
        pages = client._parse_typeahead_response(data)
        assert pages == []

    def test_malformed_response_returns_empty(self):
        client = self._client()
        data = {"data": None}
        pages = client._parse_typeahead_response(data)
        assert pages == []


# ---------------------------------------------------------------------------
# Client: search_pages (integration with mock network)
# ---------------------------------------------------------------------------

class TestClientSearchPages:
    def _build_mock_client(self):
        """Build a client with mocked network calls."""
        client = MetaAdsClient.__new__(MetaAdsClient)
        client._initialized = True
        client._init_time = __import__("time").time()
        client._max_session_age = 9999
        client._tokens = {"lsd": "testtoken"}
        client._doc_ids = {}
        client._request_counter = 0
        client._fingerprint = MagicMock()
        client._fingerprint.get_graphql_headers.return_value = {
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": "test-agent",
        }
        client._fingerprint.sec_ch_ua = '"Test"'
        client._fingerprint.sec_ch_ua_mobile = "?0"
        client._fingerprint.sec_ch_ua_platform = '"Windows"'
        client.session = MagicMock()
        client.timeout = 30
        client.max_retries = 1
        client.retry_delay = 0
        client._proxy_pool = None
        client._proxy_string = None
        client._consecutive_errors = 0
        client._consecutive_refresh_failures = 0
        client.max_refresh_attempts = 3
        return client

    def test_search_pages_returns_parsed_results(self):
        client = self._build_mock_client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": [
                        {"page_id": "111", "page_name": "Test Page"},
                    ]
                }
            }
        })
        client.session.request.return_value = mock_response

        pages = client.search_pages("Test", "US")
        assert len(pages) == 1
        assert pages[0]["page_id"] == "111"

    def test_search_pages_handles_network_error(self):
        import requests as req
        client = self._build_mock_client()
        client.session.request.side_effect = req.exceptions.ConnectionError("Network error")

        pages = client.search_pages("Test", "US")
        assert pages == []

    def test_search_pages_handles_json_error(self):
        client = self._build_mock_client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not valid json"
        client.session.request.return_value = mock_response

        pages = client.search_pages("Test", "US")
        assert pages == []

    def test_search_pages_handles_http_error(self):
        client = self._build_mock_client()
        mock_response = MagicMock()
        mock_response.status_code = 500
        client.session.request.return_value = mock_response

        pages = client.search_pages("Test", "US")
        assert pages == []

    def test_search_pages_strips_for_prefix(self):
        """Facebook responses often start with for(;;); anti-XSSI prefix."""
        client = self._build_mock_client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'for (;;);' + json.dumps({
            "data": {
                "ad_library_main": {
                    "typeahead_suggestions": [
                        {"page_id": "999", "page_name": "Prefixed"},
                    ]
                }
            }
        })
        client.session.request.return_value = mock_response

        pages = client.search_pages("Prefixed", "US")
        assert len(pages) == 1
        assert pages[0]["page_id"] == "999"


# ---------------------------------------------------------------------------
# Collector: search_pages
# ---------------------------------------------------------------------------

class TestCollectorSearchPages:
    def test_search_pages_returns_page_search_results(self):
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_pages.return_value = [
            {
                "page_id": "111",
                "page_name": "Test Page",
                "page_profile_uri": "https://www.facebook.com/testpage",
                "page_alias": "testpage",
                "page_logo_url": None,
                "page_verified": True,
                "page_like_count": 5000,
                "category": "Business",
            }
        ]
        results = collector.search_pages("Test")
        assert len(results) == 1
        assert isinstance(results[0], PageSearchResult)
        assert results[0].page_id == "111"
        assert results[0].page_name == "Test Page"
        assert results[0].page_verified is True

    def test_search_pages_empty_result(self):
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_pages.return_value = []
        results = collector.search_pages("xyznonexistent")
        assert results == []

    def test_search_pages_filters_empty_ids(self):
        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.client.search_pages.return_value = [
            {"page_id": "", "page_name": "Bad"},
            {"page_id": "222", "page_name": "Good"},
        ]
        results = collector.search_pages("test")
        assert len(results) == 1
        assert results[0].page_id == "222"


# ---------------------------------------------------------------------------
# CLI: --search-pages flag
# ---------------------------------------------------------------------------

class TestSearchPagesCLI:
    def test_search_pages_flag_parsed(self):
        with patch.object(sys, "argv", ["prog", "--search-pages", "Coca-Cola"]):
            args = parse_args()
            assert args.search_pages == "Coca-Cola"

    def test_search_pages_flag_default_is_none(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.search_pages is None

    def test_search_pages_with_country(self):
        with patch.object(sys, "argv", [
            "prog", "--search-pages", "Coca-Cola", "-c", "EG"
        ]):
            args = parse_args()
            assert args.search_pages == "Coca-Cola"
            assert args.country == "EG"
