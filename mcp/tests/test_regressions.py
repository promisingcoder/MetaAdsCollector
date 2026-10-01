"""Every issue observed during MCP implementation has a reproducible regression."""

from __future__ import annotations

import io
import logging
import time

import pytest
from meta_ads_collector_mcp.config import PrivateFormatter, private_value
from meta_ads_collector_mcp.media import MediaSession
from meta_ads_collector_mcp.schemas import MCPError, Search
from meta_ads_collector_mcp.service import Service

from meta_ads_collector.client import MetaAdsClient


def replay(monkeypatch, real_records):
    rows = [row["api_fields"] for row in real_records]
    calls = []

    def search(self, **kwargs):
        calls.append(kwargs.copy())
        start = int(kwargs["cursor"] or 0)
        return {"ads": rows[start : start + 2]}, str(start + 2) if start + 2 < len(rows) else None

    monkeypatch.setattr(MetaAdsClient, "search_ads", search)
    return calls


def test_deleting_paused_native_job_closes_it_before_cascade(service, real_records, monkeypatch):
    replay(monkeypatch, real_records)
    result = service.search(Search(query="nike"), batch_size=1)
    job_id = result["result_set_id"]
    service.jobs("delete", [job_id])
    assert job_id not in service.runs
    with pytest.raises(MCPError):
        service.store.job(job_id)
    service.close()  # Previously attempted event writes against deleted rows.


def test_remote_paused_owner_cannot_be_deleted(service):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    service.store.claim(job_id, "remote")
    service.store.update(job_id, "remote", state="PAUSED")
    with pytest.raises(MCPError):
        service.store.delete(job_id)


def test_cursor_fallback_cannot_exceed_total_request_budget(service, real_records, monkeypatch):
    calls = replay(monkeypatch, real_records)
    job_id = service.search(Search(query="nike", max_requests=3, rate_limit_delay=0, jitter=0), 3)["result_set_id"]
    service.close()

    def expired(self, **kwargs):
        calls.append(kwargs.copy())
        return {"error": "Invalid expired cursor"}, None

    monkeypatch.setattr(MetaAdsClient, "search_ads", expired)
    reopened = Service(service.store.directory)
    try:
        result = reopened.continue_search(job_id, 3)
        assert len(calls) == 3
        assert result["job"]["state"] == "LIMIT_REACHED"
    finally:
        reopened.close()


def test_time_waiting_between_tool_calls_does_not_consume_active_budget(service, real_records, monkeypatch):
    replay(monkeypatch, real_records)
    result = service.search(Search(query="nike", max_seconds=1, rate_limit_delay=0, jitter=0), 1)
    job_id = result["result_set_id"]
    run = service.runs[job_id]
    run.started -= 1000  # Simulate a long idle pause without a blocking sleep.
    second = service.continue_search(job_id, 1)
    assert second["ads"]
    assert second["job"]["stats"]["active_seconds"] < 1


def test_recovery_is_reported_after_graceful_restart(service, real_records, monkeypatch):
    replay(monkeypatch, real_records)
    job_id = service.search(Search(query="nike"), 1)["result_set_id"]
    service.close()
    reopened = Service(service.store.directory)
    try:
        result = reopened.continue_search(job_id, 1)
        assert result["job"]["recovery"] == "checkpoint_replay_with_dedup"
    finally:
        reopened.close()


def test_tracebacks_redact_private_values(service):
    path = service.private_dir / "value.secret"
    path.write_text("private-regression-value", encoding="utf-8")
    private_value(None, path.name, service.private_dir)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(PrivateFormatter())
    logger = logging.getLogger("mcp-private-regression")
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError("Failure containing private-regression-value")
        except RuntimeError:
            logger.exception("Request failed")
        assert "private-regression-value" not in stream.getvalue()
        assert "[redacted]" in stream.getvalue()
    finally:
        logger.removeHandler(handler)


def test_media_budget_aborts_stream_and_closes_response(real_records):
    # Supplemental controlled streaming fault; URL is from a real captured Meta creative.
    urls = [
        creative.get("video_hd_url") or creative.get("image_url") or creative.get("thumbnail_url")
        for row in real_records
        for creative in row["creatives"]
    ]
    url = next(url for url in urls if url)

    class Response:
        closed = False

        def iter_content(self, chunk_size):
            yield b"observed-stream-budget-test"

        def close(self):
            self.closed = True

    class Session:
        def get(self, url, **kwargs):
            return response

    response = Response()
    bounded = MediaSession(Session(), max_file_bytes=1, max_total_bytes=1).get(url)
    with pytest.raises(ValueError, match="budget"):
        list(bounded.iter_content(1))
    assert response.closed


def test_cancelled_owner_never_commits_after_lease_is_lost(service, real_records):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    service.store.claim(job_id, "first")
    with service.store.db() as db:
        db.execute("UPDATE jobs SET lease=? WHERE id=?", (time.time() - 1, job_id))
    service.store.claim(job_id, "second")
    with pytest.raises(MCPError):
        service.store.save_ad(job_id, "first", real_records[0])
    assert service.store.job(job_id)["count"] == 0


def test_cancellation_during_fetch_stops_before_committing_an_ad(service, real_records, monkeypatch):
    def cancel_in_flight(self, **kwargs):
        job_id = service.store.list_jobs()[0]["id"]
        service.store.control(job_id, "cancel")
        return {"ads": [real_records[0]["api_fields"]]}, None

    monkeypatch.setattr(MetaAdsClient, "search_ads", cancel_in_flight)
    result = service.search(Search(query="nike"), 1)
    assert result["job"]["state"] == "CANCELLED"
    assert result["ads"] == []


def test_late_cancellation_does_not_relabel_completed_evidence(service, stored):
    service.jobs("cancel", [stored])
    assert service.store.job(stored)["state"] == "COMPLETED"


def test_stale_generator_close_cannot_overwrite_replacement_state(service, real_records, monkeypatch):
    replay(monkeypatch, real_records)
    job_id = service.search(Search(query="nike"), 1)["result_set_id"]
    with service.store.db() as db:
        db.execute("UPDATE jobs SET owner='replacement',state='RUNNING',lease=0 WHERE id=?", (job_id,))
    service.close()
    assert service.store.job(job_id)["state"] == "RUNNING"
    assert service.store.job(job_id)["owner"] == "replacement"


def test_media_redirect_cannot_fetch_an_advertiser_landing_page(real_records):
    asset = next(
        c.get("video_hd_url") or c.get("image_url") or c.get("thumbnail_url")
        for row in real_records
        for c in row["creatives"]
        if c.get("video_hd_url") or c.get("image_url") or c.get("thumbnail_url")
    )
    landing = next(
        c["link_url"]
        for row in real_records
        for c in row["creatives"]
        if c.get("link_url") and "footlocker" in c["link_url"]
    )

    class Redirect:
        status_code = 302
        headers = {"Location": landing}
        closed = False

        def close(self):
            self.closed = True

    class Session:
        calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            assert kwargs["allow_redirects"] is False
            return response

    response, session = Redirect(), Session()
    with pytest.raises(ValueError, match="Meta-hosted"):
        MediaSession(session, 100, 100).get(asset)
    assert session.calls == 1 and response.closed


def test_graceful_background_shutdown_requeues_durable_job(service, monkeypatch):
    from meta_ads_collector_mcp.engine import Run

    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    service.stop.set()
    monkeypatch.setattr(Run, "step", lambda self, amount: "RUNNING")
    result = service.execute(job_id, 1, background=True)
    assert result["state"] == "QUEUED"
    assert service.store.job(job_id)["owner"] is None
