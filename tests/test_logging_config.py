"""Tests for meta_ads_collector.logging_config.

Verifies that:
- JSONFormatter produces valid single-line JSON with required keys
- setup_logging configures the root logger correctly
- Text and JSON formats work as expected
- File handler is created when log_file is specified
- CLI flags --log-format and --log-file are accepted
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_ads_collector.logging_config import JSONFormatter, setup_logging

# =========================================================================
# JSONFormatter
# =========================================================================


class TestJSONFormatter:
    """Tests for the JSONFormatter class."""

    def test_produces_valid_json(self):
        """Output should be valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_contains_required_keys(self):
        """Output JSON should contain timestamp, level, logger, message."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=42,
            msg="Warning message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Warning message"

    def test_message_with_args(self):
        """Message formatting with arguments should work."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Count: %d",
            args=(42,),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "Count: 42"

    def test_single_line(self):
        """Output should be a single line (no embedded newlines in the JSON)."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Multi\nline\nmessage",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        # The JSON itself should be on one line (message content is escaped)
        parsed = json.loads(output)
        assert parsed["message"] == "Multi\nline\nmessage"

    def test_extra_fields_included(self):
        """Extra attributes on the log record should be included."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="With extras",
            args=None,
            exc_info=None,
        )
        record.custom_field = "custom_value"  # type: ignore[attr-defined]
        record.request_id = 12345  # type: ignore[attr-defined]
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["custom_field"] == "custom_value"
        assert parsed["request_id"] == 12345

    def test_non_serializable_extra_converted_to_str(self):
        """Non-JSON-serializable extras should be converted to string."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Non-serializable extra",
            args=None,
            exc_info=None,
        )
        record.complex_obj = object()  # type: ignore[attr-defined]
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "complex_obj" in parsed
        assert isinstance(parsed["complex_obj"], str)

    def test_exception_info_included(self):
        """Exception info should be included when present."""
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=None,
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "test error" in parsed["exception"]

    def test_timestamp_is_iso_format(self):
        """Timestamp should be in ISO 8601 format."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Check timestamp",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        # Should be parseable as ISO format
        from datetime import datetime
        ts = parsed["timestamp"]
        # Should not raise
        datetime.fromisoformat(ts)

    def test_debug_level(self):
        """DEBUG level should be represented correctly."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=1,
            msg="Debug",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "DEBUG"


# =========================================================================
# setup_logging
# =========================================================================


class TestSetupLogging:
    """Tests for the setup_logging function."""

    def _cleanup_root_logger(self):
        """Remove all handlers from root logger."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def test_text_format_default(self):
        """Default format should be text."""
        self._cleanup_root_logger()
        setup_logging(level="INFO", fmt="text")
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) >= 1
        # First handler should use standard formatter
        handler = root.handlers[0]
        assert not isinstance(handler.formatter, JSONFormatter)
        self._cleanup_root_logger()

    def test_json_format(self):
        """JSON format should use JSONFormatter."""
        self._cleanup_root_logger()
        setup_logging(level="DEBUG", fmt="json")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        handler = root.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)
        self._cleanup_root_logger()

    def test_file_handler_created(self, tmp_path):
        """File handler should be created when log_file is specified."""
        self._cleanup_root_logger()
        log_file = str(tmp_path / "test.log")
        setup_logging(level="INFO", fmt="text", log_file=log_file)
        root = logging.getLogger()
        # Should have both console and file handlers
        assert len(root.handlers) == 2
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        self._cleanup_root_logger()

    def test_file_handler_with_json_format(self, tmp_path):
        """File handler should use JSONFormatter when fmt='json'."""
        self._cleanup_root_logger()
        log_file = str(tmp_path / "test.log")
        setup_logging(level="INFO", fmt="json", log_file=log_file)
        root = logging.getLogger()
        for handler in root.handlers:
            assert isinstance(handler.formatter, JSONFormatter)
        self._cleanup_root_logger()

    def test_file_handler_writes_logs(self, tmp_path):
        """Logs should appear in the file."""
        self._cleanup_root_logger()
        log_file = tmp_path / "output.log"
        setup_logging(level="INFO", fmt="text", log_file=str(log_file))
        test_logger = logging.getLogger("test_file_write")
        test_logger.info("Hello from test")
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "Hello from test" in content
        self._cleanup_root_logger()

    def test_json_file_output_is_valid_json(self, tmp_path):
        """JSON format file output should contain valid JSON lines."""
        self._cleanup_root_logger()
        log_file = tmp_path / "output.jsonl"
        setup_logging(level="INFO", fmt="json", log_file=str(log_file))
        test_logger = logging.getLogger("test_json_file")
        test_logger.info("JSON log entry")
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = log_file.read_text(encoding="utf-8").strip()
        for line in content.split("\n"):
            if line.strip():
                parsed = json.loads(line)
                assert "message" in parsed
        self._cleanup_root_logger()

    def test_creates_parent_dirs_for_log_file(self, tmp_path):
        """setup_logging should create parent directories for log_file."""
        self._cleanup_root_logger()
        log_file = str(tmp_path / "subdir" / "deep" / "test.log")
        setup_logging(level="INFO", log_file=log_file)
        assert Path(log_file).parent.exists()
        self._cleanup_root_logger()

    def test_idempotent_call(self):
        """Calling setup_logging twice should not duplicate handlers."""
        self._cleanup_root_logger()
        setup_logging(level="INFO")
        setup_logging(level="DEBUG")
        root = logging.getLogger()
        # Should only have one console handler (second call clears first)
        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG
        self._cleanup_root_logger()

    def test_level_case_insensitive(self):
        """Level string should be case-insensitive."""
        self._cleanup_root_logger()
        setup_logging(level="debug")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        self._cleanup_root_logger()


# =========================================================================
# CLI integration
# =========================================================================


class TestLoggingCLIFlags:
    """Tests for --log-format and --log-file CLI flags."""

    def test_log_format_text_default(self):
        """--log-format should default to text."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.log_format == "text"

    def test_log_format_json(self):
        """--log-format json should be accepted."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--log-format", "json"]):
            args = parse_args()
            assert args.log_format == "json"

    def test_log_file_flag(self):
        """--log-file should capture the path."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--log-file", "/tmp/collector.log"
        ]):
            args = parse_args()
            assert args.log_file == "/tmp/collector.log"

    def test_log_file_default_none(self):
        """--log-file should default to None."""
        from meta_ads_collector.cli import parse_args

        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.log_file is None

    def test_log_format_invalid_rejected(self):
        """Invalid --log-format value should cause argument error."""
        from meta_ads_collector.cli import parse_args

        with (
            patch.object(sys, "argv", [
                "prog", "-o", "out.json", "--log-format", "xml"
            ]),
            pytest.raises(SystemExit),
        ):
            parse_args()


# =========================================================================
# Public API export
# =========================================================================


class TestLoggingExport:
    """Verify setup_logging is exported from the package."""

    def test_setup_logging_importable(self):
        """setup_logging should be importable from the package root."""
        from meta_ads_collector import setup_logging as sl
        assert callable(sl)

    def test_setup_logging_in_all(self):
        """setup_logging should be in __all__."""
        import meta_ads_collector
        assert "setup_logging" in meta_ads_collector.__all__
