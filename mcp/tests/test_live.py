"""End-to-end evidence from actual Meta, never dummy advertisers or asset URLs."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp.client.stdio import StdioServerParameters
from meta_ads_collector_mcp.schemas import ProxyProfile, Schedule, Search
from meta_ads_collector_mcp.service import Service

from mcp import Client
from meta_ads_collector import Ad

pytestmark = pytest.mark.mcp_live


def setup_proxy(service):
    if os.environ.get("METAADS_CI_PROXY"):
        service.proxy("configure", ProxyProfile(name="live", environment="METAADS_CI_PROXY"))
        service.proxy("default", name="live")


@pytest.fixture(scope="module")
def live_service(tmp_path_factory):
    service = Service(tmp_path_factory.mktemp("mcp-live"))
    setup_proxy(service)
    yield service
    service.close()


@pytest.fixture(scope="module")
def live_collection(live_service):
    result = live_service.search(
        Search(query="nike", page_size=5, max_results=12, max_requests=10, timeout=45), batch_size=4
    )
    assert result["ads"], "Actual Meta query returned no evidence"
    assert result["job"]["state"] == "PAUSED", result["job"]["error"]
    return result


def test_actual_advertiser_discovery_and_proxy(live_service):
    pages = live_service.advertisers("coca cola", "US")
    assert pages["pages"]
    assert all(page["page_id"].isdigit() for page in pages["pages"])
    assert live_service.proxy("check")["connected"]


def test_actual_native_pagination_and_raw_fields(live_service, live_collection):
    job_id = live_collection["result_set_id"]
    first = {ad["id"] for ad in live_collection["ads"]}
    second = live_service.continue_search(job_id, 4)
    assert second["ads"], second["job"]["error"]
    assert first.isdisjoint(ad["id"] for ad in second["ads"])
    assert second["job"]["stats"]["requests_made"] >= 2
    rows = live_service.results(job_id, view="raw")["ads"]
    for row in rows:
        assert row["api_fields"]
        assert Ad.from_graphql_response(row["api_fields"]).id == row["id"]
    assert len(rows) == len({row["id"] for row in rows})


@pytest.mark.parametrize("format", ["json", "jsonl", "csv"])
def test_actual_evidence_exports(live_service, live_collection, format):
    job_id = live_collection["result_set_id"]
    before = live_service.store.job(job_id)["stats"]["requests_made"]
    result = live_service.export(job_id, format)
    path = Path(result["path"])
    if format == "json":
        rows = json.loads(path.read_text(encoding="utf-8"))["ads"]
    elif format == "jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    else:
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row["api_fields"] = json.loads(row["api_fields"])
    assert rows
    for row in rows:
        assert Ad.from_graphql_response(row["api_fields"]).id == row["id"]
    assert live_service.store.job(job_id)["stats"]["requests_made"] == before


def test_actual_details_and_media(live_service, live_collection):
    job_id = live_collection["result_set_id"]
    rows = live_service.store.records(job_id)
    selected = next(
        (row for row in rows if any(c.get("image_url") or c.get("thumbnail_url") for c in row["creatives"])), None
    )
    assert selected is not None, "No usable media in broad live query; media functionality was not verified"
    result = live_service.inspect_ads(
        job_id, [selected["id"]], enrich=True, download_media=True, max_file_bytes=67108864, max_total_bytes=268435456
    )
    item = result["items"][0]
    assert item["enrichment"] == "retrieved", "Actual ad details were unavailable"
    downloaded = [entry for entry in item["media"] if entry["success"]]
    assert downloaded, "No actual Meta assets downloaded"
    for entry in downloaded:
        path = Path(entry["local_path"])
        assert path.is_file() and path.stat().st_size == entry["file_size"] > 0
    assert not list(live_service.output_dir.rglob("*.part"))


def test_actual_resume_after_server_close(live_service, live_collection):
    job_id = live_collection["result_set_id"]
    before = {row["id"] for row in live_service.store.records(job_id)}
    live_service.close()
    reopened = Service(live_service.store.directory)
    try:
        result = reopened.continue_search(job_id, 4)
        assert result["ads"], result["job"]["error"]
        assert before.isdisjoint(row["id"] for row in result["ads"])
        assert result["job"]["recovery"] in ("checkpoint_replay_with_dedup", "fresh")
        rows = reopened.store.records(job_id)
        assert len(rows) == len({row["id"] for row in rows})
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_actual_stdio_workflow_and_restart(tmp_path):
    args = ["-m", "meta_ads_collector_mcp", "--data-dir", str(tmp_path)]
    if os.environ.get("METAADS_CI_PROXY"):
        args += ["--proxy-env", "METAADS_CI_PROXY"]
    params = StdioServerParameters(command=sys.executable, args=args, env=os.environ.copy())
    async with Client(params, read_timeout_seconds=180) as client:
        discovery = await client.call_tool("discover")
        assert not discovery.is_error
        pages = await client.call_tool("advertisers", {"query": "coca cola", "country": "US"})
        assert pages.structured_content["pages"]
        profiles = await client.call_tool("proxy")
        assert not profiles.is_error
        if os.environ.get("METAADS_CI_PROXY"):
            configured = await client.call_tool(
                "proxy", {"action": "configure", "profile": {"name": "protocol", "environment": "METAADS_CI_PROXY"}}
            )
            assert not configured.is_error
            selected = await client.call_tool("proxy", {"action": "default", "name": "protocol"})
            assert selected.structured_content["default"] == "protocol"
        result = await client.call_tool(
            "search",
            {"search": {"query": "coca cola", "page_size": 5, "max_results": 8, "timeout": 45}, "batch_size": 3},
        )
        assert not result.is_error
        data = result.structured_content
        assert data["ads"], data["job"]["error"]
        job_id = data["result_set_id"]
        first = {row["id"] for row in data["ads"]}
        inspected = await client.call_tool(
            "inspect_ads", {"result_set_id": job_id, "ad_ids": list(first), "view": "raw"}
        )
        assert not inspected.is_error
        assert all(item["ad"]["api_fields"] for item in inspected.structured_content["items"])
        monitor = await client.call_tool(
            "monitoring",
            {"action": "create", "schedule": {"name": "protocol", "search": {"query": "nike", "max_results": 1}}},
        )
        assert not monitor.is_error
        disabled = await client.call_tool(
            "monitoring", {"action": "disable", "schedule_id": monitor.structured_content["schedule_id"]}
        )
        assert not disabled.is_error
    async with Client(params, read_timeout_seconds=180) as client:
        saved = await client.call_tool("results", {"result_set_id": job_id})
        assert first == {row["id"] for row in saved.structured_content["ads"]}
        continued = await client.call_tool("continue_search", {"result_set_id": job_id, "batch_size": 3})
        data = continued.structured_content
        assert data["ads"], data["job"]["error"]
        assert first.isdisjoint(row["id"] for row in data["ads"])


def test_actual_background_monitoring_and_newly_observed(tmp_path):
    service = Service(tmp_path)
    setup_proxy(service)
    try:
        schedule_id = service.monitoring(
            "create", Schedule(name="nike", search=Search(query="nike", max_results=3, page_size=5, timeout=45))
        )["schedule_id"]
        first_id = service.store.due()[0]
        service.submit(first_id)
        service.futures[first_id].result(timeout=180)
        first = service.results(first_id, newly_only=True)["ads"]
        assert first
        with service.store.db() as db:
            db.execute("UPDATE schedules SET next_run=0 WHERE id=?", (schedule_id,))
        second_id = service.store.due()[0]
        service.submit(second_id)
        service.futures[second_id].result(timeout=180)
        second = service.results(second_id)["ads"]
        assert second
        new = service.results(second_id, newly_only=True)["ads"]
        assert {row["id"] for row in new} == {row["id"] for row in second} - {row["id"] for row in first}
    finally:
        service.close()


def test_actual_worker_process_crash_recovery(tmp_path):
    service = Service(tmp_path)
    setup_proxy(service)
    job_id = service.store.create_job(
        service.freeze(Search(query="nike", max_results=40, page_size=5, max_seconds=240, timeout=45))
    )
    args = [sys.executable, "-m", "meta_ads_collector_mcp", "worker", "--data-dir", str(tmp_path)]
    process = subprocess.Popen(args, env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and service.store.job(job_id)["count"] < 2:
            assert process.poll() is None, "Actual worker exited before collecting evidence"
            time.sleep(0.2)
        job = service.store.job(job_id)
        assert job["count"] >= 2, job["error"]
        assert job["state"] == "RUNNING", "Worker finished before crash recovery could be exercised"
        process.kill()
        process.wait(timeout=10)
        before = {row["id"] for row in service.store.records(job_id)}
        # Wait for the actual lease expiry; do not edit the database to pretend a crashed job is recoverable.
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and service.store.job(job_id)["lease"] >= time.time():
            time.sleep(0.2)
        result = service.continue_search(job_id, 3)
        assert result["ads"], result["job"]["error"]
        assert result["job"]["recovery"] == "checkpoint_replay_with_dedup"
        assert before.isdisjoint(row["id"] for row in result["ads"])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        service.close()
