"""Actual local HTTP delivery of genuine captured Meta evidence, including failure reporting."""

from __future__ import annotations

import concurrent.futures

import pytest
from meta_ads_collector_mcp.schemas import MCPError


@pytest.mark.parametrize("batch_size", [1, 2, 50])
def test_webhook_delivers_exact_meta_records(service, stored, real_records, receiver, batch_size):
    received, _ = receiver
    result = service.export(
        stored, filename="delivered.json", webhook_environment="MCP_TEST_DELIVERY", webhook_batch_size=batch_size
    )
    records = received if batch_size == 1 else [row for batch in received for row in batch["ads"]]
    assert records == real_records
    assert result["webhook"] == {"delivered": len(real_records), "failed": 0}


def test_webhook_failure_does_not_claim_delivery(service, stored, real_records, receiver):
    _, status = receiver
    status[0] = 503
    result = service.export(stored, filename="delivery-failed.json", webhook_environment="MCP_TEST_DELIVERY")
    assert result["webhook"] == {"delivered": 0, "failed": len(real_records)}
    assert result["count"] == len(real_records)


def test_export_collision_is_atomic(service, stored):
    def export(_):
        try:
            return service.export(stored, filename="same.json")["path"]
        except MCPError as exc:
            assert exc.code == "already_exists"
            return None

    with concurrent.futures.ThreadPoolExecutor(2) as executor:
        outcomes = list(executor.map(export, range(2)))
    assert sum(path is not None for path in outcomes) == 1
    assert not list(service.output_dir.glob("*.part"))


def test_export_sidecar_cannot_overwrite_existing_file(service, stored):
    path = service.output_dir / "evidence.jsonl.metadata.json"
    path.write_text("Existing user evidence", encoding="utf-8")
    with pytest.raises(MCPError):
        service.export(stored, "jsonl", "evidence.jsonl")
    assert path.read_text(encoding="utf-8") == "Existing user evidence"
    assert not (service.output_dir / "evidence.jsonl").exists()
