"""Lossless export of every field returned in actual captured/live Meta rows."""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import pytest

from meta_ads_collector.async_collector import AsyncMetaAdsCollector
from meta_ads_collector.cli import _write_ads_to_file
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.models import Ad, PageInfo

from .audit_meta_samples import CAPTURED_ADS


@pytest.mark.parametrize("extension", [".json", ".jsonl", ".csv"])
def test_cli_exports_every_captured_meta_field_and_nested_value(tmp_path, extension):
    raw = deepcopy(CAPTURED_ADS[0])
    ad = Ad.from_graphql_response(raw)
    path = tmp_path / ("actual-meta-ad" + extension)
    assert _write_ads_to_file(iter([ad]), str(path), extension) == 1
    if extension == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))["ads"][0]["api_fields"]
    elif extension == ".jsonl":
        payload = json.loads(path.read_text(encoding="utf-8"))["api_fields"]
    else:
        with path.open(encoding="utf-8", newline="") as stream:
            payload = json.loads(next(csv.DictReader(stream))["api_fields"])
    assert payload == raw


def test_sync_csv_preserves_every_captured_meta_field(tmp_path):
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    raw = deepcopy(CAPTURED_ADS[0])
    collector.search = MagicMock(return_value=iter([Ad.from_graphql_response(raw)]))
    path = tmp_path / "sync.csv"
    assert collector.collect_to_csv(str(path)) == 1
    with path.open(encoding="utf-8", newline="") as stream:
        assert json.loads(next(csv.DictReader(stream))["api_fields"]) == raw


@pytest.mark.asyncio
async def test_async_csv_preserves_every_captured_meta_field(tmp_path):
    collector = AsyncMetaAdsCollector.__new__(AsyncMetaAdsCollector)
    raw = deepcopy(CAPTURED_ADS[0])

    async def captured_rows(**_kwargs):
        yield Ad.from_graphql_response(raw)

    collector.search = captured_rows
    path = tmp_path / "async.csv"
    assert await collector.collect_to_csv(str(path)) == 1
    with path.open(encoding="utf-8", newline="") as stream:
        assert json.loads(next(csv.DictReader(stream))["api_fields"]) == raw


@pytest.mark.integration
def test_live_every_meta_field_survives_default_json_and_csv_export(collected_ads, tmp_path):
    for ad in collected_ads:
        assert ad.raw_data
        assert json.loads(ad.to_json())["api_fields"] == ad.raw_data
    path = tmp_path / "actual-full-meta.csv"
    assert _write_ads_to_file(iter(collected_ads), str(path), ".csv") == len(collected_ads)
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [json.loads(row["api_fields"]) for row in rows] == [ad.raw_data for ad in collected_ads]


@pytest.mark.integration
def test_live_actual_detail_enrichment_fills_sparse_ad_fields(collected_ads, monkeypatch):
    """Fetch actual details once and check every missing field from that response."""
    source = next(ad for ad in collected_ads if ad.page and ad.page.id)
    sparse = Ad(id=source.id, page=PageInfo(id=source.page.id, name=""))
    with MetaAdsCollector(timeout=30, max_retries=2) as collector:
        received = []
        real_get = collector.client.get_ad_details

        def recorded_get(**kwargs):
            detail = real_get(**kwargs)
            received.append(detail)
            return detail

        monkeypatch.setattr(collector.client, "get_ad_details", recorded_get)
        enriched = collector.enrich_ad(sparse)
    assert len(received) == 1, "Enrichment did not complete a real detail lookup"
    details = Ad.from_graphql_response(received[0])
    assert details.page and details.page.id and details.page.name
    assert details.creatives
    assert enriched is not sparse
    assert sparse.page.name == ""
    for model_field in fields(details):
        name = model_field.name
        if name in {"id", "page", "collected_at", "collection_source"}:
            continue
        value = getattr(details, name)
        if value is not None and value != "" and value != [] and value != {}:
            assert getattr(enriched, name) == value, f"Actual Meta detail field {name} was not enriched"
    assert enriched.page == details.page


@pytest.mark.asyncio
async def test_async_response_error_preserves_original_meta_payload_in_failure_event():
    """Unexpected Meta client errors must remain failures with no completion stamp."""
    from meta_ads_collector.dedup import DeduplicationTracker
    from meta_ads_collector.exceptions import MetaAdsError

    collector = AsyncMetaAdsCollector(rate_limit_delay=0, jitter=0)
    collector.client.search_ads = AsyncMock(return_value=({"ads": [], "error": "Meta error"}, None))
    tracker = DeduplicationTracker()
    try:
        with pytest.raises(MetaAdsError):
            await collector.collect(query="nike", dedup_tracker=tracker)
    finally:
        await collector.close()
    assert tracker.get_last_collection_time() is None
