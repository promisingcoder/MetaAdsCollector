"""Tests for meta_ads_collector.reporting.

Verifies that:
- CollectionReport dataclass stores all fields correctly
- format_report produces human-readable text with all fields
- format_report_json produces valid JSON with all fields
- CLI flags --report and --report-file are accepted
- CollectionReport is exported from the package
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from unittest.mock import patch

from meta_ads_collector.reporting import (
    CollectionReport,
    format_report,
    format_report_json,
)

# =========================================================================
# CollectionReport dataclass
# =========================================================================


class TestCollectionReport:
    """Tests for the CollectionReport dataclass."""

    def test_default_values(self):
        """All fields should have sensible defaults."""
        report = CollectionReport()
        assert report.total_collected == 0
        assert report.duplicates_skipped == 0
        assert report.filtered_out == 0
        assert report.errors == 0
        assert report.duration_seconds == 0.0
        assert report.start_time is None
        assert report.end_time is None

    def test_custom_values(self):
        """Fields should accept custom values."""
        start = datetime(2024, 6, 15, 10, 0, 0)
        end = datetime(2024, 6, 15, 10, 5, 30)
        report = CollectionReport(
            total_collected=150,
            duplicates_skipped=12,
            filtered_out=8,
            errors=2,
            duration_seconds=330.5,
            start_time=start,
            end_time=end,
        )
        assert report.total_collected == 150
        assert report.duplicates_skipped == 12
        assert report.filtered_out == 8
        assert report.errors == 2
        assert report.duration_seconds == 330.5
        assert report.start_time == start
        assert report.end_time == end


# =========================================================================
# format_report
# =========================================================================


class TestFormatReport:
    """Tests for the format_report function."""

    def test_contains_all_fields(self):
        """Report text should mention all numeric fields."""
        report = CollectionReport(
            total_collected=150,
            duplicates_skipped=12,
            filtered_out=8,
            errors=2,
            duration_seconds=45.3,
        )
        text = format_report(report)
        assert "150" in text
        assert "12" in text
        assert "8" in text
        assert "2" in text  # errors
        assert "45.30s" in text

    def test_contains_throughput(self):
        """Report should include throughput when duration > 0."""
        report = CollectionReport(
            total_collected=100,
            duration_seconds=10.0,
        )
        text = format_report(report)
        assert "10.00 ads/s" in text

    def test_no_throughput_when_zero_duration(self):
        """Report should omit throughput when duration is 0."""
        report = CollectionReport(
            total_collected=100,
            duration_seconds=0.0,
        )
        text = format_report(report)
        assert "ads/s" not in text

    def test_includes_start_time(self):
        """Report should include start time in ISO format."""
        start = datetime(2024, 6, 15, 10, 0, 0)
        report = CollectionReport(start_time=start)
        text = format_report(report)
        assert "2024-06-15T10:00:00" in text

    def test_includes_end_time(self):
        """Report should include end time in ISO format."""
        end = datetime(2024, 6, 15, 10, 5, 30)
        report = CollectionReport(end_time=end)
        text = format_report(report)
        assert "2024-06-15T10:05:30" in text

    def test_omits_times_when_none(self):
        """Report should not mention times when they are None."""
        report = CollectionReport()
        text = format_report(report)
        assert "Start time" not in text
        assert "End time" not in text

    def test_multiline_output(self):
        """Report should be multiple lines."""
        report = CollectionReport(total_collected=10)
        text = format_report(report)
        lines = text.strip().split("\n")
        assert len(lines) >= 5

    def test_header_and_footer(self):
        """Report should have header and footer separators."""
        report = CollectionReport()
        text = format_report(report)
        assert text.startswith("=" * 50)
        assert text.strip().endswith("=" * 50)


# =========================================================================
# format_report_json
# =========================================================================


class TestFormatReportJson:
    """Tests for the format_report_json function."""

    def test_produces_valid_json(self):
        """Output should be valid JSON."""
        report = CollectionReport(total_collected=42)
        output = format_report_json(report)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_contains_all_fields(self):
        """JSON should contain all report fields."""
        report = CollectionReport(
            total_collected=150,
            duplicates_skipped=12,
            filtered_out=8,
            errors=2,
            duration_seconds=45.3,
        )
        output = format_report_json(report)
        parsed = json.loads(output)
        assert parsed["total_collected"] == 150
        assert parsed["duplicates_skipped"] == 12
        assert parsed["filtered_out"] == 8
        assert parsed["errors"] == 2
        assert parsed["duration_seconds"] == 45.3

    def test_datetime_serialized_as_iso(self):
        """Datetime fields should be serialized as ISO 8601 strings."""
        start = datetime(2024, 6, 15, 10, 0, 0)
        end = datetime(2024, 6, 15, 10, 5, 30)
        report = CollectionReport(start_time=start, end_time=end)
        output = format_report_json(report)
        parsed = json.loads(output)
        assert parsed["start_time"] == "2024-06-15T10:00:00"
        assert parsed["end_time"] == "2024-06-15T10:05:30"

    def test_none_times_serialized_as_null(self):
        """None datetime fields should be null in JSON."""
        report = CollectionReport()
        output = format_report_json(report)
        parsed = json.loads(output)
        assert parsed["start_time"] is None
        assert parsed["end_time"] is None

    def test_json_roundtrip(self):
        """JSON should be parseable back to equivalent data."""
        report = CollectionReport(
            total_collected=100,
            errors=5,
            duration_seconds=30.0,
        )
        output = format_report_json(report)
        parsed = json.loads(output)
        assert parsed["total_collected"] == report.total_collected
        assert parsed["errors"] == report.errors
        assert parsed["duration_seconds"] == report.duration_seconds


# =========================================================================
# CLI integration
# =========================================================================


class TestReportCLIFlags:
    """Tests for --report and --report-file CLI flags."""

    def test_report_flag_default_false(self):
        """--report should default to False."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.report is False

    def test_report_flag_set(self):
        """--report should be True when specified."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--report"]):
            args = parse_args()
            assert args.report is True

    def test_report_file_default_none(self):
        """--report-file should default to None."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.report_file is None

    def test_report_file_set(self):
        """--report-file should capture the path."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--report-file", "/tmp/report.json"
        ]):
            args = parse_args()
            assert args.report_file == "/tmp/report.json"

    def test_both_flags_together(self):
        """Both --report and --report-file should work together."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--report",
            "--report-file", "/tmp/report.json",
        ]):
            args = parse_args()
            assert args.report is True
            assert args.report_file == "/tmp/report.json"


# =========================================================================
# Public API export
# =========================================================================


class TestReportingExport:
    """Verify CollectionReport is exported from the package."""

    def test_collection_report_importable(self):
        """CollectionReport should be importable from the package root."""
        from meta_ads_collector import CollectionReport as CR
        assert CR is CollectionReport

    def test_collection_report_in_all(self):
        """CollectionReport should be in __all__."""
        import meta_ads_collector
        assert "CollectionReport" in meta_ads_collector.__all__
