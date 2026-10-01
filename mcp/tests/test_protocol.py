"""Actual SDK client/server protocol checks, including a real stdio subprocess."""

from __future__ import annotations

import json
import os
import sys

import pytest
from mcp.client.stdio import StdioServerParameters
from meta_ads_collector_mcp.server import create_server

from mcp import Client

TOOLS = {
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


@pytest.mark.asyncio
async def test_sdk_discovery_schemas_resources_and_errors(service):
    async with Client(create_server(service)) as client:
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} == TOOLS
        for tool in listing.tools:
            assert tool.input_schema["type"] == "object"
            assert tool.output_schema is not None
        discovery = await client.call_tool("discover")
        assert not discovery.is_error
        assert discovery.structured_content["transport"] == "stdio"
        resource = await client.read_resource("metaads://capabilities")
        assert json.loads(resource.contents[0].text)["operations"]
        error = await client.call_tool("results", {"result_set_id": "unknown"})
        assert error.is_error
        assert "not_found" in error.content[0].text


@pytest.mark.asyncio
async def test_sdk_saved_result_tools(service, stored, real_records):
    async with Client(create_server(service)) as client:
        result = await client.call_tool("results", {"result_set_id": stored, "view": "raw", "limit": 1})
        assert not result.is_error
        assert result.structured_content["ads"][0]["api_fields"] == real_records[0]["api_fields"]
        resource = await client.read_resource("metaads://results/" + stored)
        assert json.loads(resource.contents[0].text)["result_set_id"] == stored
        export = await client.call_tool("export_results", {"result_set_id": stored, "format": "jsonl"})
        assert not export.is_error
        assert export.structured_content["count"] == len(real_records)
        jobs = await client.call_tool("jobs", {"action": "report", "job_ids": [stored]})
        assert jobs.structured_content["reports"][0]["report"]["total_collected"] == len(real_records)


@pytest.mark.asyncio
async def test_stdio_initialization_framing_and_shutdown(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "meta_ads_collector_mcp", "--data-dir", str(tmp_path)],
        env=os.environ.copy(),
    )
    async with Client(params, read_timeout_seconds=30, mode="legacy") as client:
        assert {tool.name for tool in (await client.list_tools()).tools} == TOOLS
        result = await client.call_tool("discover")
        assert result.structured_content["collector_version"]
        await client.send_ping()
        error = await client.call_tool("search", {"search": {"query": "nike", "page_size": 31}})
        assert error.is_error
    assert (tmp_path / "state.sqlite3").exists()


@pytest.mark.asyncio
async def test_failed_search_sets_protocol_error_flag_with_structured_results(service, monkeypatch):
    from meta_ads_collector.client import MetaAdsClient
    from meta_ads_collector.exceptions import RateLimitError

    def observed_failure(self, **kwargs):
        raise RateLimitError("Controlled reproduction of a Meta rate-limit response", retry_after=30)

    monkeypatch.setattr(MetaAdsClient, "search_ads", observed_failure)
    async with Client(create_server(service)) as client:
        result = await client.call_tool("search", {"search": {"query": "nike"}, "batch_size": 1})
        assert result.is_error
        assert result.structured_content["job"]["state"] == "FAILED"
        assert result.structured_content["job"]["error"]["code"] == "rate_limited"
        assert result.structured_content["ads"] == []


@pytest.mark.asyncio
async def test_failed_webhook_sets_error_flag_and_retains_export(service, stored, receiver):
    _, status = receiver
    status[0] = 503
    async with Client(create_server(service)) as client:
        result = await client.call_tool(
            "export_results",
            {"result_set_id": stored, "filename": "protocol-delivery.json", "webhook_environment": "MCP_TEST_DELIVERY"},
        )
        assert result.is_error
        assert result.structured_content["webhook"]["failed"] > 0
        assert result.structured_content["path"]
