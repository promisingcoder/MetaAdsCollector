"""Tests for meta_ads_collector.cli (argument parsing)."""

import sys
from unittest.mock import patch

import pytest

from meta_ads_collector.cli import map_ad_type, map_search_type, map_sort, map_status, parse_args


class TestArgParsing:
    def test_output_required(self):
        with pytest.raises(SystemExit):
            with patch.object(sys, "argv", ["prog"]):
                parse_args()

    def test_defaults(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.output == "out.json"
            assert args.query == ""
            assert args.country == "US"
            assert args.ad_type == "all"
            assert args.status == "active"
            assert args.verbose is False
            assert args.no_proxy is False

    def test_all_flags(self):
        with patch.object(sys, "argv", [
            "prog",
            "-o", "out.csv",
            "-q", "test",
            "-c", "EG",
            "-t", "political",
            "-s", "inactive",
            "--search-type", "exact",
            "--sort-by", "relevancy",
            "--max-results", "100",
            "--page-size", "20",
            "--timeout", "60",
            "--delay", "3.5",
            "--include-raw",
            "--no-proxy",
            "-v",
        ]):
            args = parse_args()
            assert args.query == "test"
            assert args.country == "EG"
            assert args.ad_type == "political"
            assert args.status == "inactive"
            assert args.search_type == "exact"
            assert args.sort_by == "relevancy"
            assert args.max_results == 100
            assert args.page_size == 20
            assert args.timeout == 60
            assert args.delay == 3.5
            assert args.include_raw is True
            assert args.no_proxy is True
            assert args.verbose is True


class TestMappers:
    def test_map_ad_type(self):
        assert map_ad_type("all") == "ALL"
        assert map_ad_type("political") == "POLITICAL_AND_ISSUE_ADS"
        assert map_ad_type("housing") == "HOUSING_ADS"
        assert map_ad_type("unknown") == "ALL"

    def test_map_status(self):
        assert map_status("active") == "ACTIVE"
        assert map_status("inactive") == "INACTIVE"
        assert map_status("all") == "ALL"
        assert map_status("unknown") == "ACTIVE"

    def test_map_search_type(self):
        assert map_search_type("keyword") == "KEYWORD_EXACT_PHRASE"
        assert map_search_type("exact") == "KEYWORD_EXACT_PHRASE"
        assert map_search_type("page") == "PAGE"
        assert map_search_type("unknown") == "KEYWORD_EXACT_PHRASE"

    def test_map_sort(self):
        assert map_sort("impressions") == "SORT_BY_TOTAL_IMPRESSIONS"
        assert map_sort("relevancy") is None
        assert map_sort("unknown") == "SORT_BY_TOTAL_IMPRESSIONS"
