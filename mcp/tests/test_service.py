"""Saved-data tools, private configuration and export contracts."""

from __future__ import annotations

import csv
import json
import logging

import pytest
from meta_ads_collector_mcp.config import RedactLogs, private_value, redact, safe_path
from meta_ads_collector_mcp.schemas import Filters, MCPError, ProxyProfile, Schedule, Search


def test_discovery_covers_core_and_new_capabilities(service):
    capabilities = service.capabilities()
    assert set(capabilities["operations"]) == {
        "discover",
        "advertisers",
        "search",
        "continue_search",
        "inspect_ads",
        "results",
        "export_results",
        "jobs",
        "monitoring",
        "proxy",
    }
    assert "api_fields" in capabilities["supported"]["fields"]
    assert "enrich_ad" in capabilities["coverage"]
    assert "missing_data" in capabilities["filter_schema"]["properties"]
    assert capabilities["limits"]["maximum_meta_page"] == 30


@pytest.mark.parametrize("view", ["summary", "detailed", "raw"])
def test_saved_views_preserve_identity_and_provenance(service, stored, real_records, view):
    result = service.results(stored, view=view)
    assert [row["id"] for row in result["ads"]] == [row["id"] for row in real_records]
    for row in result["ads"]:
        assert row["source_url"].startswith("https://www.facebook.com/ads/library/?id=")
    if view == "raw":
        assert result["ads"][0]["api_fields"] == real_records[0]["api_fields"]
    else:
        assert "api_fields" not in result["ads"][0]


def test_saved_pagination_field_selection_and_sort(service, stored, real_records):
    first = service.results(stored, limit=1, fields=["is_active"])
    assert first["next_offset"] == 1
    second = service.results(stored, offset=1, limit=1)
    assert second["ads"][0]["id"] == real_records[1]["id"]
    assert "api_fields" not in first["ads"][0]
    ids = [row["id"] for row in service.results(stored, sort="id", descending=True)["ads"]]
    assert ids == sorted(ids, reverse=True)


def test_saved_strict_filters_do_not_requery_meta(service, stored, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved filtering must not access Meta")

    monkeypatch.setattr(service, "collector", forbidden)
    result = service.results(stored, filters=Filters(min_impressions=10000, missing_data="exclude"))
    assert result["ads"] == []


@pytest.mark.parametrize("format", ["json", "jsonl", "csv"])
def test_exports_preserve_full_records(service, stored, real_records, format):
    from pathlib import Path

    result = service.export(stored, format)
    path = Path(result["path"])
    if format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload["ads"]
        assert payload["metadata"]["id"] == stored
    elif format == "jsonl":
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    else:
        with path.open(encoding="utf-8", newline="") as stream:
            records = list(csv.DictReader(stream))
        for record in records:
            record["api_fields"] = json.loads(record["api_fields"])
    assert [r["api_fields"] for r in records] == [r["api_fields"] for r in real_records]
    assert result["count"] == len(real_records)
    with pytest.raises(MCPError, match="filename"):
        service.export(stored, format)


@pytest.mark.parametrize("name", ["../outside.json", "nested/../../outside.json", "", "\x00"])
def test_paths_cannot_escape_workspace(service, name):
    with pytest.raises(MCPError):
        safe_path(service.output_dir, name)


def test_inspection_without_network_and_batch_report(service, stored, real_records):
    ids = [row["id"] for row in real_records]
    result = service.inspect_ads(stored, ids, view="raw")
    assert result["items"][0]["ad"]["api_fields"] == real_records[0]["api_fields"]
    report = service.jobs("report", [stored])["reports"][0]
    assert report["report"]["total_collected"] == len(ids)
    assert service.jobs("status", [stored])["jobs"][0]["state"] == "COMPLETED"


@pytest.mark.parametrize(
    "operation",
    [
        lambda s, j: s.results(j, limit=0),
        lambda s, j: s.results(j, fields=["fake"]),
        lambda s, j: s.results(j, sort="fake"),
        lambda s, j: s.inspect_ads(j, []),
        lambda s, j: s.inspect_ads(j, ["unknown"]),
        lambda s, j: s.export(j, "xlsx"),
        lambda s, j: s.jobs("fake", [j]),
        lambda s, j: s.jobs("status", []),
    ],
)
def test_invalid_operations_are_explicit_errors(service, stored, operation):
    with pytest.raises(MCPError):
        operation(service, stored)


def test_profile_sources_are_private_and_job_settings_are_frozen(service, monkeypatch):
    # Syntax-only private configuration, not evidence of network connectivity.
    value = "http://private-user:private-password@proxy.apify.com:8000"
    monkeypatch.setenv("MCP_TEST_PRIVATE_PROXY", value)
    profile = ProxyProfile(name="research", environment="MCP_TEST_PRIVATE_PROXY")
    response = service.proxy("configure", profile)
    service.proxy("default", name="research")
    frozen = service.freeze(Search(query="nike"))
    service.proxy("configure", ProxyProfile(name="research", environment="MCP_TEST_PRIVATE_PROXY", max_failures=8))
    assert frozen["proxy"]["max_failures"] == 3
    assert "private-password" not in json.dumps(response)
    assert value not in service.store.path.read_bytes().decode("utf-8", errors="ignore")
    assert "private-password" not in json.dumps(service.proxy())


def test_private_file_and_log_redaction(service, monkeypatch):
    path = service.private_dir / "proxy.secret"
    path.write_text("sensitive-test-value", encoding="utf-8")
    assert private_value(None, "proxy.secret", service.private_dir) == "sensitive-test-value"
    assert redact("failure sensitive-test-value") == "failure [redacted]"
    record = logging.LogRecord("test", logging.WARNING, "", 0, "failure %s", ("sensitive-test-value",), None)
    assert RedactLogs().filter(record)
    assert record.getMessage() == "failure [redacted]"
    with pytest.raises(MCPError):
        private_value(None, "../outside.secret", service.private_dir)
    with pytest.raises(MCPError):
        private_value("MCP_MISSING_SECRET", None, service.private_dir)


def test_monitor_configuration_controls(service):
    schedule = Schedule(name="research", search=Search(query="nike"))
    schedule_id = service.monitoring("create", schedule)["schedule_id"]
    service.monitoring("disable", schedule_id=schedule_id)
    assert service.monitoring()["schedules"][0]["enabled"] == 0
    service.monitoring("enable", schedule_id=schedule_id)
    assert service.monitoring()["schedules"][0]["enabled"] == 1
    service.monitoring("delete", schedule_id=schedule_id)
    assert service.monitoring()["schedules"] == []


def test_large_response_requires_field_selection(service, stored, real_records):
    record = dict(real_records[0])
    record["api_fields"] = dict(record["api_fields"], controlled_large_payload="x" * 200001)
    service.store.replace_record(stored, record)
    with pytest.raises(MCPError, match="fewer fields"):
        service.results(stored, view="raw")
    assert service.results(stored, fields=["id"])["ads"]
