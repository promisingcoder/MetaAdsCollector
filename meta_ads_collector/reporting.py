"""Collection reporting for Meta Ads Collector.

Provides a :class:`CollectionReport` dataclass that captures summary
statistics from a collection run and two formatting functions:

* :func:`format_report` -- human-readable summary text
* :func:`format_report_json` -- machine-readable JSON string

Usage::

    from meta_ads_collector.reporting import CollectionReport, format_report

    report = CollectionReport(
        total_collected=150,
        duplicates_skipped=12,
        filtered_out=8,
        errors=2,
        duration_seconds=45.3,
        start_time=datetime(2024, 6, 15, 10, 0, 0),
        end_time=datetime(2024, 6, 15, 10, 0, 45),
    )
    print(format_report(report))
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class CollectionReport:
    """Summary statistics from a collection run.

    Attributes:
        total_collected: Number of ads successfully collected and yielded.
        duplicates_skipped: Number of ads skipped by deduplication.
        filtered_out: Number of ads excluded by client-side filters.
        errors: Number of errors encountered during the collection.
        duration_seconds: Wall-clock duration of the collection in seconds.
        start_time: When the collection started (UTC).
        end_time: When the collection finished (UTC).
    """

    total_collected: int = 0
    duplicates_skipped: int = 0
    filtered_out: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None


def format_report(report: CollectionReport) -> str:
    """Format a :class:`CollectionReport` as a human-readable summary.

    Args:
        report: The report to format.

    Returns:
        A multi-line string suitable for printing to stdout.
    """
    lines: list[str] = [
        "=" * 50,
        "Collection Report",
        "=" * 50,
        f"  Total collected:    {report.total_collected}",
        f"  Duplicates skipped: {report.duplicates_skipped}",
        f"  Filtered out:       {report.filtered_out}",
        f"  Errors:             {report.errors}",
        f"  Duration:           {report.duration_seconds:.2f}s",
    ]

    if report.duration_seconds > 0:
        throughput = report.total_collected / report.duration_seconds
        lines.append(f"  Throughput:         {throughput:.2f} ads/s")

    if report.start_time is not None:
        lines.append(f"  Start time:         {report.start_time.isoformat()}")
    if report.end_time is not None:
        lines.append(f"  End time:           {report.end_time.isoformat()}")

    lines.append("=" * 50)
    return "\n".join(lines)


def format_report_json(report: CollectionReport) -> str:
    """Format a :class:`CollectionReport` as a JSON string.

    Args:
        report: The report to format.

    Returns:
        A JSON string with all report fields.
    """
    data = asdict(report)
    # Convert datetime objects to ISO strings for JSON serialization
    if data.get("start_time") is not None:
        data["start_time"] = data["start_time"].isoformat()
    if data.get("end_time") is not None:
        data["end_time"] = data["end_time"].isoformat()
    return json.dumps(data, indent=2, ensure_ascii=False)
