"""Controlled failures supplement (and never replace) live Meta verification.

Transport responses replay genuine captured Meta rows. Faults are explicitly
injected to exercise recovery paths that cannot be requested from live Meta.
"""

from __future__ import annotations

from meta_ads_collector_mcp.engine import Run
from meta_ads_collector_mcp.schemas import Search
from meta_ads_collector_mcp.service import Service

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.exceptions import RateLimitError


def captured_transport(monkeypatch, real_records):
    calls = []
    rows = [record["api_fields"] for record in real_records]

    def search(self, **kwargs):
        calls.append(kwargs.copy())
        index = int(kwargs["cursor"] or 0)
        page = rows[index : index + 2]
        return {"ads": page}, str(index + 2) if index + 2 < len(rows) else None

    monkeypatch.setattr(MetaAdsClient, "search_ads", search)
    return calls


def test_native_continuation_reuses_buffer_and_session(service, real_records, monkeypatch):
    calls = captured_transport(monkeypatch, real_records)
    first = service.search(Search(query="nike", max_results=20, rate_limit_delay=0, jitter=0), batch_size=1)
    job_id = first["result_set_id"]
    assert first["continuation"] == job_id
    second = service.continue_search(job_id, 1)
    assert len(calls) == 1, "The second ad is already buffered; do not repeat the Meta request"
    assert first["ads"][0]["id"] != second["ads"][0]["id"]
    service.continue_search(job_id, 20)
    assert service.store.job(job_id)["state"] == "COMPLETED"
    assert len({call["session_id"] for call in calls}) == 1
    assert len({call["collation_token"] for call in calls}) == 1
    assert service.store.job(job_id)["count"] == len(real_records)


def test_restart_replays_partially_consumed_page_without_loss(service, real_records, monkeypatch):
    calls = captured_transport(monkeypatch, real_records)
    first = service.search(Search(query="nike", max_results=20, rate_limit_delay=0, jitter=0), 1)
    job_id = first["result_set_id"]
    service.close()
    reopened = Service(service.store.directory)
    try:
        reopened.continue_search(job_id, 20)
        records = reopened.store.records(job_id)
        assert [row["api_fields"] for row in records] == [row["api_fields"] for row in real_records]
        assert len(records) == len({row["id"] for row in records})
        assert calls[1]["cursor"] is None
        assert calls[1]["session_id"] == calls[0]["session_id"]
    finally:
        reopened.close()


def test_crashed_owner_resumes_noninitial_page(service, real_records, monkeypatch):
    calls = captured_transport(monkeypatch, real_records)
    first = service.search(Search(query="nike", max_results=20, rate_limit_delay=0, jitter=0), 3)
    job_id = first["result_set_id"]
    assert service.store.job(job_id)["checkpoint"]["cursor"] == "2"
    service.close()
    reopened = Service(service.store.directory)
    try:
        reopened.continue_search(job_id, 20)
        assert calls[-1]["cursor"] == "2"
        assert reopened.store.job(job_id)["count"] == len(real_records)
    finally:
        reopened.close()


def test_expired_cursor_restarts_with_deduplication(service, real_records, monkeypatch):
    calls = captured_transport(monkeypatch, real_records)
    first = service.search(Search(query="nike", max_results=20, rate_limit_delay=0, jitter=0), 3)
    job_id = first["result_set_id"]
    service.close()
    original = MetaAdsClient.search_ads
    expired = False

    def expire(self, **kwargs):
        nonlocal expired
        if kwargs["cursor"] and not expired:
            expired = True
            return {"error": "Invalid expired cursor"}, None
        return original(self, **kwargs)

    monkeypatch.setattr(MetaAdsClient, "search_ads", expire)
    reopened = Service(service.store.directory)
    try:
        reopened.continue_search(job_id, 20)
        job = reopened.store.job(job_id)
        assert job["state"] == "COMPLETED"
        assert job["recovery"] == "restart_search_with_dedup"
        assert job["count"] == len(real_records)
        assert calls[-2]["cursor"] is None
    finally:
        reopened.close()


def test_partial_failure_is_not_empty_success(service, real_records, monkeypatch):
    original = captured_transport(monkeypatch, real_records)
    transport = MetaAdsClient.search_ads

    def fail(self, **kwargs):
        if kwargs["cursor"]:
            raise RateLimitError("Observed rate limit", retry_after=30)
        return transport(self, **kwargs)

    monkeypatch.setattr(MetaAdsClient, "search_ads", fail)
    result = service.search(Search(query="nike", max_results=20, rate_limit_delay=0, jitter=0), 20)
    assert result["job"]["state"] == "FAILED"
    assert result["job"]["error"]["code"] == "rate_limited"
    assert result["job"]["error"]["retry_after"] == 30
    assert len(result["ads"]) == 2
    assert len(original) == 1


def test_cancellation_releases_paused_session(service, real_records, monkeypatch):
    captured_transport(monkeypatch, real_records)
    result = service.search(Search(query="nike", max_results=20), 1)
    job_id = result["result_set_id"]
    service.jobs("cancel", [job_id])
    assert service.store.job(job_id)["state"] == "CANCELLED"
    assert job_id not in service.runs


def test_request_budget_does_not_issue_an_extra_request(service, real_records, monkeypatch):
    calls = captured_transport(monkeypatch, real_records)
    result = service.search(Search(query="nike", max_results=20, max_requests=1, rate_limit_delay=0, jitter=0), 20)
    assert len(calls) == 1
    assert result["job"]["state"] == "LIMIT_REACHED"
    assert len(result["ads"]) == 2


def test_result_budget_does_not_requery(service, real_records, monkeypatch):
    calls = captured_transport(monkeypatch, real_records)
    result = service.search(Search(query="nike", max_results=1), 20)
    assert result["job"]["state"] == "LIMIT_REACHED"
    assert len(calls) == 1
    assert len(result["ads"]) == 1


def test_duration_budget_is_enforced_before_network(service, monkeypatch):
    job_id = service.store.create_job(service.freeze(Search(query="nike", max_seconds=1)))
    service.store.claim(job_id, service.owner)
    run = Run(service.store, job_id, service.owner, service.private_dir)

    def forbidden(*args, **kwargs):
        raise AssertionError("Expired job must not access Meta")

    monkeypatch.setattr(run.collector.client, "search_ads", forbidden)
    run.elapsed_before = 2
    assert run.step(1) == "LIMIT_REACHED"


def test_background_job_reaches_terminal_state(service, real_records, monkeypatch):
    captured_transport(monkeypatch, real_records)
    result = service.search(Search(query="nike", max_results=20, rate_limit_delay=0, jitter=0), background=True)
    future = service.futures[result["result_set_id"]]
    future.result(timeout=10)
    assert service.store.job(result["result_set_id"])["state"] == "COMPLETED"
