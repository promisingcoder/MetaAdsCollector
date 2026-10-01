"""Transactions, cross-process leases, scheduling and retention."""

from __future__ import annotations

import concurrent.futures
import time

import pytest
from meta_ads_collector_mcp.schemas import MCPError, Schedule, Search
from meta_ads_collector_mcp.storage import Store


def test_storage_survives_reopening(service, stored, real_records):
    reopened = Store(service.store.directory)
    assert reopened.records(stored) == real_records
    assert reopened.job(stored)["count"] == len(real_records)


def test_only_one_owner_can_claim(service):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))

    def claim(index):
        return Store(service.store.directory).claim(job_id, str(index))

    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        assert sum(executor.map(claim, range(8))) == 1


def test_live_lease_cannot_be_stolen_and_expired_lease_can(service):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    assert service.store.claim(job_id, "first", seconds=30)
    assert not service.store.claim(job_id, "second")
    assert service.store.heartbeat(job_id, "first")
    with service.store.db() as db:
        db.execute("UPDATE jobs SET lease=0 WHERE id=?", (job_id,))
    assert service.store.claim(job_id, "second")
    with pytest.raises(MCPError, match="lease"):
        service.store.update(job_id, "first", stats={})


def test_paused_native_generator_retains_exclusive_lease(service):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    service.store.claim(job_id, "first")
    service.store.update(job_id, "first", state="PAUSED")
    assert service.store.heartbeat(job_id, "first")
    assert not service.store.claim(job_id, "second")
    service.store.release(job_id, "first", "PAUSED")
    assert service.store.claim(job_id, "second")


def test_committed_results_are_unique_and_checkpoint_survives(service, real_records):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    service.store.claim(job_id, service.owner)
    checkpoint = {"cursor": "opaque-test-state", "session_id": "session"}
    service.store.update(job_id, service.owner, checkpoint=checkpoint)
    assert service.store.save_ad(job_id, service.owner, real_records[0])
    assert not service.store.save_ad(job_id, service.owner, real_records[0])
    assert Store(service.store.directory).job(job_id)["checkpoint"] == checkpoint
    assert service.store.job(job_id)["count"] == 1


def test_transaction_rolls_back_results(service, stored, real_records):
    before = service.store.job(stored)["count"]
    with pytest.raises(RuntimeError), service.store.db() as db:
        db.execute("DELETE FROM ads WHERE job_id=?", (stored,))
        raise RuntimeError("Simulated transaction interruption")
    assert service.store.job(stored)["count"] == before


def test_events_have_incremental_sequence(service, stored):
    service.store.event(stored, "checkpoint", {"count": 1})
    service.store.event(stored, "checkpoint", {"count": 2})
    first = service.store.events(stored, limit=1)[0]
    assert [e["data"]["count"] for e in service.store.events(stored, after=first["seq"])] == [2]


def test_cancel_and_resume_state_machine(service):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    service.store.control(job_id, "cancel")
    assert service.store.job(job_id)["state"] == "CANCELLED"
    service.store.control(job_id, "resume")
    assert service.store.job(job_id)["state"] == "QUEUED"
    with pytest.raises(MCPError):
        service.store.control(job_id, "resume")


def test_active_results_cannot_be_deleted(service):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    with pytest.raises(MCPError):
        service.store.delete(job_id)
    service.store.control(job_id, "cancel")
    service.store.delete(job_id)
    with pytest.raises(MCPError):
        service.store.job(job_id)


def test_schedule_due_is_atomic_across_connections(service):
    schedule_id = service.monitoring("create", Schedule(name="research", search=Search(query="nike")))["schedule_id"]
    with concurrent.futures.ThreadPoolExecutor(4) as executor:
        outcomes = list(executor.map(lambda _: Store(service.store.directory).due(), range(4)))
    assert sum(len(result) for result in outcomes) == 1
    assert service.store.schedules()[0]["id"] == schedule_id
    assert not service.store.due()


def test_monitor_does_not_overlap_and_coalesces_missed_runs(service):
    service.monitoring("create", Schedule(name="research", search=Search(query="nike")))
    first = service.store.due()[0]
    with service.store.db() as db:
        db.execute("UPDATE schedules SET next_run=0")
    assert not service.store.due()
    service.store.control(first, "cancel")
    assert len(service.store.due()) == 1
    assert service.store.schedules()[0]["next_run"] > time.time()


def test_newly_observed_is_atomic_and_persistent(service, real_records):
    schedule_id = service.monitoring("create", Schedule(name="research", search=Search(query="nike")))["schedule_id"]
    jobs = []
    for _ in range(2):
        job_id = service.store.create_job(service.freeze(Search(query="nike")), schedule_id)
        service.store.claim(job_id, service.owner)
        service.store.save_ad(job_id, service.owner, real_records[0])
        service.store.release(job_id, service.owner, "COMPLETED")
        jobs.append(job_id)
    assert len(service.store.records(jobs[0], newly_only=True)) == 1
    assert service.store.records(jobs[1], newly_only=True) == []


def test_retention_removes_old_terminal_jobs_but_keeps_seen_ids(service, real_records):
    schedule_id = service.monitoring(
        "create", Schedule(name="research", search=Search(query="nike"), retention_days=1)
    )["schedule_id"]
    old = service.store.due()[0]
    service.store.claim(old, service.owner)
    service.store.save_ad(old, service.owner, real_records[0])
    service.store.release(old, service.owner, "COMPLETED")
    with service.store.db() as db:
        db.execute("UPDATE jobs SET updated=? WHERE id=?", (time.time() - 172800, old))
        db.execute("UPDATE schedules SET next_run=0")
    assert service.store.due()
    with pytest.raises(MCPError):
        service.store.job(old)
    with service.store.db() as db:
        assert db.execute("SELECT count(*) FROM observed WHERE schedule_id=?", (schedule_id,)).fetchone()[0] == 1


def test_worker_liveness_is_explicit(service):
    assert not service.store.worker_alive()
    service.store.worker_heartbeat("worker")
    assert service.capabilities()["persistent_worker_alive"]
    service.store.worker_heartbeat("worker", remove=True)
    assert not service.store.worker_alive()
