"""Tests for meta_ads_collector.cli (argument parsing and entry points).

Covers argument parsing defaults, all flag combinations, mapper functions,
help output, missing required arguments, invalid output formats, and the
``python -m meta_ads_collector`` module entry point.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from meta_ads_collector.cli import (
    main,
    map_ad_type,
    map_search_type,
    map_sort,
    map_status,
    parse_args,
)


class TestArgParsing:
    """Verify that argparse defaults and flag combinations work."""

    def test_output_defaults_to_none(self) -> None:
        """Output is validated at the application level, not argparse, so --search-pages can work without it."""
        with patch.object(sys, "argv", ["prog"]):
            args = parse_args()
            assert args.output is None

    def test_defaults(self) -> None:
        """Verify all default values when only --output is provided."""
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.output == "out.json"
            assert args.query == ""
            assert args.country == "US"
            assert args.ad_type == "all"
            assert args.status == "active"
            assert args.verbose is False
            assert args.no_proxy is False

    def test_all_flags(self) -> None:
        """Verify all flags are parsed correctly when provided."""
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


class TestHelpFlag:
    """Verify the --help flag works correctly."""

    def test_help_exits_zero_with_usage(self) -> None:
        """Running with --help should exit with code 0 and print usage text."""
        with pytest.raises(SystemExit) as exc_info, patch.object(sys, "argv", ["prog", "--help"]):
                parse_args()
        assert exc_info.value.code == 0


class TestMissingRequiredArgs:
    """Verify that missing required arguments produce clear errors."""

    def test_missing_output_returns_error(self) -> None:
        """Running main() without --output should return error code 1.

        The CLI requires --output for ad collection mode.  Without it,
        main() should print an error and return 1 (unless --search-pages
        is used).
        """
        with patch.object(sys, "argv", ["prog", "-q", "test"]):
            result = main()
            assert result == 1, (
                f"Expected exit code 1 for missing --output, got {result}"
            )


class TestInvalidOutputFormat:
    """Verify that invalid output formats produce clear errors."""

    def test_invalid_extension_returns_error(self) -> None:
        """Running with an unsupported file extension should return error code 1."""
        with patch.object(sys, "argv", ["prog", "-o", "output.xlsx", "-q", "test"]):
            result = main()
            assert result == 1, (
                f"Expected exit code 1 for unsupported format .xlsx, got {result}"
            )


class TestModuleEntryPoint:
    """Verify that python -m meta_ads_collector works."""

    def test_module_entrypoint_runs(self) -> None:
        """Running 'python -m meta_ads_collector --help' should succeed.

        This verifies the __main__.py entry point is wired correctly.
        """
        result = subprocess.run(
            [sys.executable, "-m", "meta_ads_collector", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Module entry point failed with code {result.returncode}: "
            f"{result.stderr}"
        )
        assert "usage" in result.stdout.lower() or "collect" in result.stdout.lower(), (
            f"Expected usage text in stdout, got: {result.stdout[:200]}"
        )


class TestFilterFlagsInCLI:
    """Verify that filter-related CLI flags are parsed correctly."""

    def test_filter_flags_parsed(self) -> None:
        """Verify filter flags like --min-impressions are accepted."""
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--min-impressions", "1000",
            "--max-impressions", "50000",
            "--min-spend", "100",
            "--max-spend", "10000",
            "--start-date", "2024-01-01",
            "--end-date", "2024-12-31",
            "--media-type", "video",
            "--publisher-platform", "facebook",
            "--publisher-platform", "instagram",
            "--language", "en",
            "--has-video",
        ]):
            args = parse_args()
            assert args.min_impressions == 1000
            assert args.max_impressions == 50000
            assert args.min_spend == 100
            assert args.max_spend == 10000
            assert args.start_date == "2024-01-01"
            assert args.end_date == "2024-12-31"
            assert args.media_type == "video"
            assert args.publisher_platforms == ["facebook", "instagram"]
            assert args.filter_languages == ["en"]
            assert args.has_video is True

    def test_dedup_flags_parsed(self) -> None:
        """Verify deduplication flags are accepted."""
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--deduplicate",
            "--state-file", "state.db",
            "--since-last-run",
        ]):
            args = parse_args()
            assert args.deduplicate is True
            assert args.state_file == "state.db"
            assert args.since_last_run is True

    def test_media_download_flags_parsed(self) -> None:
        """Verify media download flags are accepted."""
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--download-media",
            "--media-dir", "/tmp/my_media",
        ]):
            args = parse_args()
            assert args.download_media is True
            assert args.media_dir == "/tmp/my_media"

    def test_enrich_flag_parsed(self) -> None:
        """Verify the --enrich flag is accepted."""
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--enrich",
        ]):
            args = parse_args()
            assert args.enrich is True

    def test_webhook_url_flag_parsed(self) -> None:
        """Verify the --webhook-url flag is accepted."""
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--webhook-url", "https://hooks.example.com/ads",
        ]):
            args = parse_args()
            assert args.webhook_url == "https://hooks.example.com/ads"

    def test_page_level_flags_parsed(self) -> None:
        """Verify --page-url, --page-name, --search-pages flags are accepted."""
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--page-url", "https://facebook.com/123456",
        ]):
            args = parse_args()
            assert args.page_url == "https://facebook.com/123456"

        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--page-name", "Coca-Cola",
        ]):
            args = parse_args()
            assert args.page_name == "Coca-Cola"

        with patch.object(sys, "argv", [
            "prog",
            "--search-pages", "Nike",
        ]):
            args = parse_args()
            assert args.search_pages == "Nike"


class TestMappers:
    """Verify CLI value mapper functions."""

    def test_map_ad_type(self) -> None:
        """Verify ad type mapping from CLI strings to API constants."""
        assert map_ad_type("all") == "ALL"
        assert map_ad_type("political") == "POLITICAL_AND_ISSUE_ADS"
        assert map_ad_type("housing") == "HOUSING_ADS"
        assert map_ad_type("unknown") == "ALL"

    def test_map_status(self) -> None:
        """Verify status mapping from CLI strings to API constants."""
        assert map_status("active") == "ACTIVE"
        assert map_status("inactive") == "INACTIVE"
        assert map_status("all") == "ALL"
        assert map_status("unknown") == "ACTIVE"

    def test_map_search_type(self) -> None:
        """Verify search type mapping from CLI strings to API constants."""
        assert map_search_type("keyword") == "KEYWORD_UNORDERED"
        assert map_search_type("exact") == "KEYWORD_EXACT_PHRASE"
        assert map_search_type("page") == "PAGE"
        assert map_search_type("unknown") == "KEYWORD_UNORDERED"

    def test_map_sort(self) -> None:
        """Verify sort mapping from CLI strings to API constants."""
        assert map_sort("impressions") == "SORT_BY_TOTAL_IMPRESSIONS"
        assert map_sort("relevancy") is None
        assert map_sort("unknown") == "SORT_BY_TOTAL_IMPRESSIONS"
