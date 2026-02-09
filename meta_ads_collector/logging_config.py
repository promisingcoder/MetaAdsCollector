"""Structured logging configuration for Meta Ads Collector.

Provides a :class:`JSONFormatter` that emits log records as single-line
JSON objects and a :func:`setup_logging` helper that configures the root
logger with a choice of text or JSON formatting and optional file output.

Usage::

    from meta_ads_collector.logging_config import setup_logging

    # Standard text format at INFO level
    setup_logging(level="INFO")

    # JSON format with DEBUG level, also writing to a file
    setup_logging(level="DEBUG", fmt="json", log_file="/var/log/collector.log")
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Each log line is a JSON object with the following keys:

    * ``timestamp`` -- ISO 8601 UTC timestamp
    * ``level`` -- log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    * ``logger`` -- logger name
    * ``message`` -- formatted log message

    Any extra attributes attached to the log record are merged into the
    JSON object.  Standard internal attributes (``args``, ``exc_info``,
    etc.) are excluded.
    """

    # Internal LogRecord attributes that should not be serialized as extras.
    _INTERNAL_ATTRS: frozenset[str] = frozenset({
        "args", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module",
        "msecs", "message", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        """Format *record* as a single-line JSON string."""
        # Build the core payload
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge any extra attributes the caller attached to the record.
        for key, value in record.__dict__.items():
            if key not in self._INTERNAL_ATTRS and key not in payload:
                try:
                    json.dumps(value)  # quick serialisability check
                    payload[key] = value
                except (TypeError, ValueError, OverflowError):
                    payload[key] = str(value)

        # Include exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


_TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    fmt: str = "text",
    log_file: str | None = None,
) -> None:
    """Configure the root logger.

    Args:
        level: Log level as a string (``"DEBUG"``, ``"INFO"``, etc.).
        fmt: Output format.  ``"text"`` for human-readable output,
            ``"json"`` for machine-readable JSON lines.
        log_file: Optional path to a log file.  When provided, a
            :class:`logging.FileHandler` is added **in addition** to
            the console handler.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Only remove handlers previously added by this function so that
    # host-application handlers are not disturbed.
    for handler in root.handlers[:]:
        if getattr(handler, "_meta_ads_collector", False):
            root.removeHandler(handler)

    # Choose formatter
    if fmt == "json":
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(_TEXT_FORMAT, datefmt=_TEXT_DATEFMT)

    # Console handler (stderr)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    console._meta_ads_collector = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # Optional file handler
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(path), encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        file_handler._meta_ads_collector = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
