"""Export format tests for meta_ads_collector.

Tests JSON, CSV, and JSONL export roundtrips using the session-scoped
``collected_ads`` fixture.  These tests do NOT make any additional API
calls -- they only exercise the serialization and file I/O paths.

Marked as integration tests because they depend on the collected_ads
fixture which requires a live API call (done once per session).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from meta_ads_collector.models import Ad

pytestmark = pytest.mark.integration


class TestJSONExport:
    """Verify JSON export produces valid, complete output."""

    def test_json_export_roundtrip(
        self, collected_ads: list[Ad], tmp_path: Path,
    ) -> None:
        """Export ads to JSON, read back, and verify structure and count.

        Checks:
        - Output file is valid JSON
        - Contains an 'ads' array
        - Array length matches input count
        - Each ad has core fields (id, page)
        """
        output_file = tmp_path / "test_output.json"

        # Write JSON manually (matching collector.collect_to_json output structure)
        ads_dicts = [ad.to_dict() for ad in collected_ads]
        output = {
            "metadata": {
                "query": "coca cola",
                "country": "US",
                "total_count": len(ads_dicts),
            },
            "ads": ads_dicts,
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Read back and validate
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)

        assert "metadata" in data, "JSON output missing 'metadata' block"
        assert "ads" in data, "JSON output missing 'ads' array"
        assert isinstance(data["ads"], list), "'ads' should be a list"
        assert len(data["ads"]) == len(collected_ads), (
            f"Expected {len(collected_ads)} ads in JSON, got {len(data['ads'])}"
        )
        assert data["metadata"]["total_count"] == len(collected_ads), (
            "metadata.total_count does not match"
        )

        # Verify core fields in each ad
        for ad_dict in data["ads"]:
            assert "id" in ad_dict, "Ad dict missing 'id' field"
            assert ad_dict["id"], "Ad dict has empty 'id'"
            assert "page" in ad_dict, "Ad dict missing 'page' field"


class TestCSVExport:
    """Verify CSV export produces valid, complete output."""

    def test_csv_export_roundtrip(
        self, collected_ads: list[Ad], tmp_path: Path,
    ) -> None:
        """Export ads to CSV, read back, and verify headers and row count.

        Checks:
        - CSV has expected column headers
        - Row count matches input count
        - No data corruption (id field matches)
        """
        output_file = tmp_path / "test_output.csv"

        # Define expected columns (matching collector.collect_to_csv)
        columns = [
            "id", "page_id", "page_name", "page_url", "is_active",
            "ad_status", "delivery_start_time", "delivery_stop_time",
            "creative_body", "creative_title", "creative_description",
            "creative_link_url", "creative_image_url", "snapshot_url",
            "impressions_lower", "impressions_upper", "spend_lower",
            "spend_upper", "currency", "publisher_platforms", "languages",
            "funding_entity", "disclaimer", "ad_type", "collected_at",
        ]

        # Write CSV
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for ad in collected_ads:
                primary = ad.creatives[0] if ad.creatives else None
                row = {
                    "id": ad.id,
                    "page_id": ad.page.id if ad.page else "",
                    "page_name": ad.page.name if ad.page else "",
                    "page_url": ad.page.page_url if ad.page else "",
                    "is_active": ad.is_active if ad.is_active is not None else "",
                    "ad_status": ad.ad_status or "",
                    "delivery_start_time": ad.delivery_start_time.isoformat() if ad.delivery_start_time else "",
                    "delivery_stop_time": ad.delivery_stop_time.isoformat() if ad.delivery_stop_time else "",
                    "creative_body": primary.body if primary else "",
                    "creative_title": primary.title if primary else "",
                    "creative_description": primary.description if primary else "",
                    "creative_link_url": primary.link_url if primary else "",
                    "creative_image_url": primary.image_url if primary else "",
                    "snapshot_url": ad.snapshot_url or ad.ad_snapshot_url or "",
                    "impressions_lower": ad.impressions.lower_bound if ad.impressions else "",
                    "impressions_upper": ad.impressions.upper_bound if ad.impressions else "",
                    "spend_lower": ad.spend.lower_bound if ad.spend else "",
                    "spend_upper": ad.spend.upper_bound if ad.spend else "",
                    "currency": ad.currency or "",
                    "publisher_platforms": ",".join(ad.publisher_platforms),
                    "languages": ",".join(ad.languages),
                    "funding_entity": ad.funding_entity or "",
                    "disclaimer": ad.disclaimer or "",
                    "ad_type": ad.ad_type or "",
                    "collected_at": ad.collected_at.isoformat(),
                }
                writer.writerow(row)

        # Read back and validate
        with open(output_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert reader.fieldnames == columns, (
            f"CSV headers do not match expected columns: {reader.fieldnames}"
        )
        assert len(rows) == len(collected_ads), (
            f"Expected {len(collected_ads)} rows in CSV, got {len(rows)}"
        )

        # Verify no data corruption on the id field
        csv_ids = {row["id"] for row in rows}
        ad_ids = {ad.id for ad in collected_ads}
        assert csv_ids == ad_ids, "CSV ids do not match original ad ids"


class TestJSONLExport:
    """Verify JSONL export produces valid, complete output."""

    def test_jsonl_export_roundtrip(
        self, collected_ads: list[Ad], tmp_path: Path,
    ) -> None:
        """Export ads to JSONL, read back, and verify each line is valid JSON.

        Checks:
        - Each line is valid JSON
        - Line count matches input count
        - Each record has an 'id' field
        """
        output_file = tmp_path / "test_output.jsonl"

        # Write JSONL
        with open(output_file, "w", encoding="utf-8") as f:
            for ad in collected_ads:
                f.write(json.dumps(ad.to_dict(), ensure_ascii=False))
                f.write("\n")

        # Read back and validate
        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == len(collected_ads), (
            f"Expected {len(collected_ads)} lines in JSONL, got {len(lines)}"
        )

        for i, line in enumerate(lines):
            line = line.strip()
            assert line, f"Line {i} is empty"
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(f"Line {i} is not valid JSON: {exc}")
            assert "id" in record, f"Line {i} record missing 'id' field"
            assert record["id"], f"Line {i} record has empty 'id'"
