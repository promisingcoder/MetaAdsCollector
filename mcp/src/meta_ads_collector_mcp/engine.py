"""Collector adapters; the core remains responsible for Meta requests and parsing."""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import suppress
from dataclasses import fields
from datetime import datetime

from meta_ads_collector import Ad, DeduplicationTracker, MetaAdsCollector, passes_filter
from meta_ads_collector.events import ALL_EVENT_TYPES
from meta_ads_collector.exceptions import AuthenticationError, ProxyError, RateLimitError, SessionExpiredError

from .config import private_value, proxy_from, redact
from .schemas import BudgetReached, Cancelled, Filters, MCPError, Search
from .storage import Store


def restore(record: dict) -> Ad:
    raw = record.get("api_fields") or record.get("raw_data")
    if not isinstance(raw, dict):
        raise MCPError("missing_source", "Stored ad does not contain its original Meta record")
    ad = Ad.from_graphql_response(raw)
    if record.get("collected_at"):
        ad.collected_at = datetime.fromisoformat(record["collected_at"])
    return ad


def matches(ad: Ad, filters: Filters) -> bool:
    if filters.missing_data == "exclude":
        required = []
        for stem in ("impressions", "spend"):
            for prefix, bound in (("min", "upper_bound"), ("max", "lower_bound")):
                if getattr(filters, f"{prefix}_{stem}") is not None:
                    metric = getattr(ad, stem)
                    required.append(metric is not None and getattr(metric, bound) is not None)
        if filters.start_date is not None or filters.end_date is not None:
            required.append(ad.delivery_start_time is not None)
        for field in ("publisher_platforms", "languages"):
            if getattr(filters, field) is not None:
                required.append(bool(getattr(ad, field)))
        if not all(required):
            return False
    return passes_filter(ad, filters.core())


def error_info(exc: Exception) -> dict:
    code = "upstream_error"
    for kind, name in (
        (RateLimitError, "rate_limited"),
        (AuthenticationError, "authentication_error"),
        (SessionExpiredError, "session_expired"),
        (ProxyError, "proxy_error"),
        (MCPError, None),
    ):
        if isinstance(exc, kind):
            code = exc.code if name is None else name
            break
    result = {"code": code, "message": redact(str(exc))[:1000]}
    if isinstance(exc, RateLimitError):
        result["retry_after"] = getattr(exc, "retry_after", None)
    return result


class Run:
    """One leased native generator. Checkpoints replay its last page safely."""

    def __init__(self, store: Store, job_id: str, owner: str, private_dir):
        self.store, self.job_id, self.owner = store, job_id, owner
        job = store.job(job_id)
        self.search = Search.model_validate(job["spec"]["search"])
        self.checkpoint = job["checkpoint"]
        self.previous = job["stats"]
        self.elapsed_before = float(self.previous.get("active_seconds", 0))
        self.requests_before = int(self.previous.get("requests_made", 0))
        self.started = time.monotonic()
        self.running = False
        self.first = True
        self.raw_checkpoint = bool(self.checkpoint)
        self.finished = False
        self.stop_heartbeat = threading.Event()
        self.thread = None
        self.collector = MetaAdsCollector(
            proxy=proxy_from(job["spec"].get("proxy"), private_dir),
            cookies=private_value(self.search.cookie_env, None, private_dir) if self.search.cookie_env else None,
            timeout=self.search.timeout,
            max_retries=self.search.max_retries,
            rate_limit_delay=self.search.rate_limit_delay,
            jitter=self.search.jitter,
        )
        self.tracker = DeduplicationTracker()
        # Seed from committed results only: the core's early mark_seen cannot lose an uncommitted ad.
        for ad_id in store.ad_ids(job_id):
            self.tracker.mark_seen(ad_id)
        for event_type in ALL_EVENT_TYPES:
            self.collector.event_emitter.on(event_type, self.on_event)
        original = self.collector.client.search_ads

        def checkpointed(**kwargs):
            self.check_budget()
            if self.first:
                if self.checkpoint:
                    kwargs["cursor"] = self.checkpoint.get("cursor")
                self.session = self.checkpoint.get("session_id", kwargs["session_id"])
                self.collation = self.checkpoint.get("collation_token", kwargs["collation_token"])
                self.first = False
            kwargs["session_id"], kwargs["collation_token"] = self.session, self.collation
            point = {"cursor": kwargs.get("cursor"), "session_id": self.session, "collation_token": self.collation}
            # Persist the requested page, not next_cursor: a crash may happen halfway through the returned page.
            self.store.update(job_id, owner, checkpoint=point)
            response = original(**kwargs)
            data, _ = response
            if self.raw_checkpoint and point["cursor"] and data.get("error"):
                text = str(data["error"]).lower()
                if "cursor" in text and any(word in text for word in ("invalid", "expired")):
                    self.check_budget()
                    if self.requests_before + self.collector.stats["requests_made"] >= self.search.max_requests:
                        raise BudgetReached("request_limit")
                    self.store.update(job_id, owner, recovery="restart_search_with_dedup")
                    kwargs["cursor"] = None
                    kwargs["session_id"], kwargs["collation_token"] = uuid.uuid4().hex, uuid.uuid4().hex
                    self.session, self.collation = kwargs["session_id"], kwargs["collation_token"]
                    self.store.update(
                        job_id,
                        owner,
                        checkpoint={"cursor": None, "session_id": self.session, "collation_token": self.collation},
                    )
                    self.collector.stats["requests_made"] += 1
                    response = original(**kwargs)
            self.raw_checkpoint = False
            return response

        self.collector.client.search_ads = checkpointed
        # Wrapper filtering supplies explicit strict-missing semantics; the core still handles parsing and pagination.
        self.iterator = self.collector.search(
            query=self.search.query,
            country=self.search.country,
            ad_type=self.search.ad_type,
            status=self.search.status,
            search_type=self.search.search_type,
            page_ids=self.search.page_ids,
            sort_by=self.search.sort_by,
            max_results=None,
            page_size=self.search.page_size,
            filter_config=self.search.filters.core(),
            dedup_tracker=self.tracker,
        )
        self.thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.thread.start()

    def heartbeat_loop(self):
        while not self.stop_heartbeat.wait(5):
            if not self.store.heartbeat(self.job_id, self.owner):
                break

    def check_budget(self):
        job = self.store.job(self.job_id)
        if job["owner"] != self.owner:
            raise MCPError("lease_lost", "Another process owns this job")
        if job["cancel"]:
            raise Cancelled()
        if self.requests_before + self.collector.stats["requests_made"] > self.search.max_requests:
            raise BudgetReached("request_limit")
        if self.elapsed() >= self.search.max_seconds:
            raise BudgetReached("duration_limit")

    def on_event(self, event):
        data = {}
        for key, value in event.data.items():
            if key == "ad":
                data["ad_id"] = value.id
            elif isinstance(value, Exception):
                data[key] = error_info(value)
            else:
                data[key] = value
        self.store.event(self.job_id, event.event_type, data, owner=self.owner)

    def stats(self):
        stats = dict(self.collector.get_stats())
        for key in ("requests_made", "ads_collected", "duplicates_skipped", "filtered_out", "pages_fetched", "errors"):
            stats[key] = stats.get(key, 0) + self.previous.get(key, 0)
        stats["ads_collected"] = self.store.job(self.job_id)["count"]
        stats["active_seconds"] = self.elapsed()
        return stats

    def elapsed(self):
        return self.elapsed_before + (time.monotonic() - self.started if self.running else 0)

    def step(self, amount: int) -> str:
        added = 0
        self.started = time.monotonic()
        self.running = True
        try:
            while added < amount:
                self.check_budget()
                if self.store.job(self.job_id)["count"] >= self.search.max_results:
                    return self.close("LIMIT_REACHED")
                ad = next(self.iterator)
                self.check_budget()
                if not matches(ad, self.search.filters):
                    self.collector.stats["filtered_out"] += 1
                    continue
                if self.store.save_ad(self.job_id, self.owner, ad.to_dict()):
                    added += 1
                self.store.update(self.job_id, self.owner, stats=self.stats())
            if self.store.job(self.job_id)["count"] >= self.search.max_results:
                return self.close("LIMIT_REACHED")
            self.store.update(self.job_id, self.owner, stats=self.stats())
            return "RUNNING"
        except StopIteration:
            state = "FAILED" if self.collector.stats["errors"] else "COMPLETED"
            if state == "FAILED":
                self.store.update(
                    self.job_id,
                    self.owner,
                    error={
                        "code": "partial_parse_failure",
                        "message": "Core reported collection errors; stored results remain available",
                    },
                )
            return self.close(state)
        except Cancelled:
            return self.close("CANCELLED")
        except BudgetReached as exc:
            self.store.event(self.job_id, "budget_reached", {"reason": str(exc)})
            return self.close("LIMIT_REACHED")
        except Exception as exc:
            with suppress(MCPError):
                self.store.update(self.job_id, self.owner, error=error_info(exc))
            return self.close("FAILED")
        finally:
            self.elapsed_before = self.elapsed()
            self.running = False

    def close(self, state: str) -> str:
        if self.finished:
            return state
        self.finished = True
        try:
            self.iterator.close()
            with suppress(MCPError):
                self.store.update(self.job_id, self.owner, stats=self.stats())
        finally:
            self.stop_heartbeat.set()
            if self.thread:
                self.thread.join(timeout=6)
            self.collector.close()
            self.tracker.close()
            self.store.release(self.job_id, self.owner, state)
        return state


def available_fields() -> list[str]:
    return [field.name for field in fields(Ad) if field.name != "raw_data"] + ["api_fields"]
