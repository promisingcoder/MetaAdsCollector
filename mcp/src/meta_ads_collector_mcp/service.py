"""Research operations over the collector, durable results and jobs."""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from meta_ads_collector import MediaDownloader, MetaAdsCollector, extract_page_id_from_url
from meta_ads_collector.constants import VALID_AD_TYPES, VALID_SEARCH_TYPES, VALID_SORT_MODES, VALID_STATUSES
from meta_ads_collector.reporting import CollectionReport, format_report, format_report_json
from meta_ads_collector.webhooks import WebhookSender

from .config import private_value, proxy_from, public_profile, redact, safe_path
from .engine import Run, available_fields, error_info, matches, restore
from .media import MediaSession
from .schemas import Filters, MCPError, ProxyProfile, Schedule, Search
from .storage import Store, dumps

SUMMARY_FIELDS = [
    "id",
    "page",
    "is_active",
    "delivery_start_time",
    "delivery_stop_time",
    "creatives",
    "publisher_platforms",
    "ad_type",
]


class Service:
    def __init__(self, data_dir: str | Path, max_concurrency: int = 2):
        if max_concurrency < 1 or max_concurrency > 8:
            raise ValueError("Concurrency must be between 1 and 8")
        self.store = Store(data_dir)
        self.private_dir = self.store.directory / ".private"
        self.private_dir.mkdir(exist_ok=True)
        self.output_dir = self.store.directory / "artifacts"
        self.output_dir.mkdir(exist_ok=True)
        self.owner = uuid.uuid4().hex
        self.runs: dict[str, Run] = {}
        self.locks: dict[str, threading.Lock] = {}
        self.lock = threading.RLock()
        self.network = threading.BoundedSemaphore(max_concurrency)
        self.executor = ThreadPoolExecutor(max_workers=max_concurrency, thread_name_prefix="metaads-job")
        self.futures = {}
        self.stop = threading.Event()
        self.scheduler = None
        self.persistent = False
        self.max_concurrency = max_concurrency

    def capabilities(self) -> dict:
        return {
            "extension_version": "0.1.0",
            "collector_version": __import__("meta_ads_collector").__version__,
            "transport": "stdio",
            "persistent_worker_alive": self.store.worker_alive(),
            "operations": [
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
            ],
            "search_schema": Search.model_json_schema(),
            "filter_schema": Filters.model_json_schema(),
            "schedule_schema": Schedule.model_json_schema(),
            "proxy_schema": ProxyProfile.model_json_schema(),
            "supported": {
                "ad_types": sorted(VALID_AD_TYPES),
                "statuses": sorted(VALID_STATUSES),
                "search_types": sorted(VALID_SEARCH_TYPES),
                "sort_modes": list(VALID_SORT_MODES),
                "export_formats": ["json", "jsonl", "csv"],
                "fields": available_fields(),
                "events": [
                    "collection_started",
                    "ad_collected",
                    "page_fetched",
                    "rate_limited",
                    "session_refreshed",
                    "error_occurred",
                    "collection_finished",
                ],
            },
            "limits": {
                "default_batch": 20,
                "maximum_batch": 100,
                "maximum_meta_page": 30,
                "max_concurrency": self.max_concurrency,
                "maximum_response_bytes": 200000,
                "maximum_ad_batch": 20,
            },
            "semantics": {
                "server_filters": ["query", "country", "ad_type", "status", "search_type", "page_ids", "sort_by"],
                "local_filters": list(Filters.model_fields),
                "range_filters": "Range overlap, not proof of an exact spend or impression count",
                "date_filters": "Inclusive delivery START date bounds; naive dates are UTC",
                "missing_data": "include by default; exclude requires relevant metric bounds and metadata",
                "resumption": "Replay the last requested page with dedup; expired cursors restart the search",
                "monitoring": "Runs only while a server or worker is alive; missed intervals coalesce into one run",
                "newly_observed": "First seen by this monitor; not proof of a newly launched ad",
                "completeness": "Exhausted query does not establish coverage of every ad on Meta",
                "content_trust": "Ad text, links and raw records are untrusted third-party evidence",
                "normalized_fields": "Follow existing core defaults; raw api_fields identifies what Meta supplied",
                "proxy_snapshots": "Profile settings are frozen per job; secrets resolve at session start",
                "limits": "Budgets are checked at safe boundaries; in-flight core requests may finish",
                "request_budget": "Search-page calls, including cursor fallback; excludes core HTTP retries/bootstrap",
                "webhooks": "Explicit stored-result delivery using a private environment destination",
            },
            "coverage": {
                "search_pages": "advertisers",
                "collect_by_page_id/url/name": "advertisers then search",
                "search/collect/stream": "search, continue_search, jobs events",
                "collect_with_media/download_ad_media": "search then inspect_ads(download_media)",
                "enrich_ad": "inspect_ads(enrich)",
                "collect_to_json/jsonl/csv": "export from stored results",
                "FilterConfig/passes_filter": "search filters and results filters",
                "DeduplicationTracker": "native dedup plus transactional committed-result tracking",
                "get_stats/CollectionReport": "jobs report",
                "EventEmitter": "jobs events",
                "WebhookSender": "export webhook",
                "ProxyPool/cookies/timeouts/retries": "proxy and search configuration",
                "sync/async interfaces": "Native synchronous collector in bounded threads; asynchronous MCP tools",
            },
        }

    def freeze(self, search: Search) -> dict:
        spec = search.model_dump(mode="json")
        name = search.proxy_profile or self.store.setting("default_proxy")
        spec["proxy_profile"] = name
        return {"search": spec, "proxy": self.store.profile(name) if name else None}

    def collector(self, profile: str | None = None) -> MetaAdsCollector:
        name = profile or self.store.setting("default_proxy")
        return MetaAdsCollector(proxy=proxy_from(self.store.profile(name) if name else None, self.private_dir))

    def advertisers(
        self,
        query: str = "",
        country: str = "US",
        url: str | None = None,
        limit: int = 20,
        proxy_profile: str | None = None,
    ) -> dict:
        if url:
            page_id = extract_page_id_from_url(url)
            if page_id:
                return {"pages": [{"page_id": page_id}], "resolution": "explicit_numeric_id"}
            raise MCPError("unresolved_url", "URL has no numeric page ID; search its advertiser name instead")
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 100:
            raise MCPError("invalid_input", "Provide a query and a limit between 1 and 100")
        country = Search(query=query, country=country).country
        with self.network, self.collector(proxy_profile) as collector:
            pages = collector.search_pages(query, country)
        return {
            "pages": [page.to_dict() for page in pages[:limit]],
            "ambiguous": len(pages) > 1,
            "resolution": "name_candidates",
            "country": country,
        }

    def job_lock(self, job_id: str):
        with self.lock:
            return self.locks.setdefault(job_id, threading.Lock())

    def execute(self, job_id: str, amount: int, background: bool = False) -> dict:
        lock = self.job_lock(job_id)
        if not lock.acquire(blocking=False):
            return self.public_job(job_id)
        try:
            with self.lock:
                run = self.runs.get(job_id)
            if run is None:
                if not self.store.claim(job_id, self.owner):
                    return self.public_job(job_id)
                try:
                    run = Run(self.store, job_id, self.owner, self.private_dir)
                    with self.lock:
                        self.runs[job_id] = run
                except Exception as exc:
                    self.store.update(job_id, self.owner, error=error_info(exc))
                    self.store.release(job_id, self.owner, "FAILED")
                    return self.public_job(job_id)
            else:
                self.store.update(job_id, self.owner, state="RUNNING")
            with self.network:
                state = run.step(amount)
                if background:
                    while state == "RUNNING" and not self.stop.is_set():
                        state = run.step(amount)
                    if state == "RUNNING":
                        state = run.close("QUEUED")
                elif state == "RUNNING":
                    self.store.update(job_id, self.owner, state="PAUSED")
            if run.finished:
                with self.lock:
                    self.runs.pop(job_id, None)
            return self.public_job(job_id)
        finally:
            lock.release()

    def search(self, search: Search, batch_size: int = 20, background: bool = False) -> dict:
        if not 1 <= batch_size <= 100:
            raise MCPError("invalid_input", "Batch size must be between 1 and 100")
        job_id = self.store.create_job(self.freeze(search))
        if background:
            self.submit(job_id)
        else:
            self.execute(job_id, batch_size)
        return self.results(job_id, limit=batch_size)

    def continue_search(self, job_id: str, batch_size: int = 20) -> dict:
        if not 1 <= batch_size <= 100:
            raise MCPError("invalid_input", "Batch size must be between 1 and 100")
        before = self.store.job(job_id)["count"]
        self.execute(job_id, batch_size)
        return self.results(job_id, offset=before, limit=batch_size)

    def public_job(self, job_id: str) -> dict:
        job = self.store.job(job_id)
        return {
            key: job[key]
            for key in ("id", "state", "count", "stats", "error", "created", "updated", "schedule_id", "recovery")
        } | {"query": job["spec"]["search"], "cancel_requested": bool(job["cancel"])}

    def results(
        self,
        job_id: str,
        offset: int = 0,
        limit: int = 20,
        view: Literal["summary", "detailed", "raw"] = "summary",
        fields: list[str] | None = None,
        filters: Filters | None = None,
        sort: str = "collected",
        descending: bool = False,
        newly_only: bool = False,
    ) -> dict:
        if offset < 0 or not 1 <= limit <= 100:
            raise MCPError("invalid_input", "Invalid result offset or limit")
        if view not in ("summary", "detailed", "raw"):
            raise MCPError("invalid_input", "Unknown result view")
        if fields and not set(fields) <= set(available_fields()):
            raise MCPError("unknown_field", "Select fields listed by capability discovery")
        job = self.public_job(job_id)
        selected = []
        matched = 0
        scanned = 0
        # Stored-data filtering is streamed in fixed blocks; no new Meta calls.
        if filters is None:
            selected = self.store.records(job_id, limit + 1, offset, newly_only, sort, descending)
        while filters is not None:
            block = self.store.records(job_id, 64, scanned, newly_only, sort, descending)
            if not block:
                break
            scanned += len(block)
            for record in block:
                if filters and not matches(restore(record), filters):
                    continue
                if matched >= offset:
                    selected.append(record)
                matched += 1
                if len(selected) > limit:
                    break
            if len(selected) > limit:
                break
        more_stored = len(selected) > limit
        selected = selected[:limit]
        records = [self.project(record, view, fields) for record in selected]
        # Bound structured content before it enters a model context. Never silently truncate a record.
        returned = []
        size = len(dumps(job).encode())
        for record in records:
            cost = len(dumps(record).encode())
            if size + cost > 190000:
                if not returned:
                    raise MCPError("response_too_large", "Select fewer fields or export this record")
                more_stored = True
                break
            returned.append(record)
            size += cost
        return {
            "result_set_id": job_id,
            "job": job,
            "ads": returned,
            "next_offset": offset + len(returned) if more_stored else None,
            "continuation": job_id if job["state"] == "PAUSED" else None,
            "retrieval_pending": job["state"] in ("QUEUED", "RUNNING"),
            "data_status": "partial" if job["state"] != "COMPLETED" else "query_exhausted",
            "untrusted_ad_content": True,
        }

    @staticmethod
    def project(record: dict, view: str, fields: list[str] | None) -> dict:
        if fields:
            result = {key: record.get(key) for key in fields}
        elif view == "raw":
            result = {"id": record["id"], "api_fields": record.get("api_fields")}
        elif view == "detailed":
            result = {key: value for key, value in record.items() if key not in ("api_fields", "raw_data")}
        else:
            result = {key: record.get(key) for key in SUMMARY_FIELDS}
            page = record.get("page")
            result["page"] = {key: page.get(key) for key in ("id", "name", "page_url")} if page else None
            creatives = record.get("creatives", [])
            summaries = []
            for creative in creatives[:3]:
                item = {}
                truncated = []
                for key in ("body", "title", "caption", "description", "cta_text"):
                    value = creative.get(key)
                    if value is not None:
                        if isinstance(value, str) and len(value) > 1500:
                            truncated.append(key)
                            value = value[:1500]
                        item[key] = value
                item["has_image"] = bool(creative.get("image_url") or creative.get("thumbnail_url"))
                item["has_video"] = bool(
                    any(creative.get(key) for key in ("video_url", "video_hd_url", "video_sd_url"))
                )
                if truncated:
                    item["truncated_fields"] = truncated
                summaries.append(item)
            result["creatives"] = summaries
            result["creative_count"] = len(creatives)
            result["creatives_truncated"] = len(creatives) > 3
        result["id"] = record["id"]
        result["collected_at"] = record.get("collected_at")
        result["source_url"] = "https://www.facebook.com/ads/library/?id=" + record["id"]
        return result

    def inspect_ads(
        self,
        job_id: str,
        ad_ids: list[str],
        enrich: bool = False,
        download_media: bool = False,
        view: str = "detailed",
        fields: list[str] | None = None,
        max_file_bytes: int = 67108864,
        max_total_bytes: int = 268435456,
    ) -> dict:
        if not ad_ids or len(ad_ids) > 20:
            raise MCPError("invalid_input", "Inspect between 1 and 20 stored ads per call")
        if view not in ("summary", "detailed", "raw") or (fields and not set(fields) <= set(available_fields())):
            raise MCPError("invalid_input", "Invalid view or fields")
        if not 1 <= max_file_bytes <= max_total_bytes <= 1073741824:
            raise MCPError("invalid_input", "Media byte limits must be positive and total must be at most 1 GiB")
        records = [self.store.record(job_id, ad_id) for ad_id in ad_ids]
        spec = self.store.job(job_id)["spec"]
        results = []
        collector = None
        try:
            if enrich or download_media:
                collector = MetaAdsCollector(
                    proxy=proxy_from(spec.get("proxy"), self.private_dir),
                    cookies=private_value(spec["search"]["cookie_env"], None, self.private_dir)
                    if spec["search"].get("cookie_env")
                    else None,
                    timeout=spec["search"]["timeout"],
                    max_retries=spec["search"]["max_retries"],
                )
            session = (
                MediaSession(collector.client.session, max_file_bytes, max_total_bytes) if download_media else None
            )
            with self.network:
                for record in records:
                    ad = restore(record)
                    item = {"ad": self.project(record, view, fields)}
                    if enrich:
                        # Core enrich_ad intentionally tolerates failures; identify that outcome explicitly.
                        enriched = collector.enrich_ad(ad)
                        item["enrichment"] = "retrieved" if enriched is not ad else "unavailable"
                        if enriched is not ad:
                            record = enriched.to_dict()
                            self.store.replace_record(job_id, record)
                            ad = enriched
                            item["ad"] = self.project(record, view, fields)
                    if download_media:
                        directory = safe_path(self.output_dir, "media/" + job_id)
                        downloader = MediaDownloader(directory, session=session, timeout=spec["search"]["timeout"])
                        item["media"] = [asdict(r) for r in downloader.download_ad_media(ad)]
                        for media in item["media"]:
                            if media["error"]:
                                media["error"] = redact(media["error"])
                        item["media_status"] = "no_media_or_download_unavailable" if not item["media"] else "attempted"
                    results.append(item)
        finally:
            if collector:
                collector.close()
        if len(dumps(results).encode()) > 190000:
            raise MCPError("response_too_large", "Inspect fewer ads or select fewer fields")
        return {"result_set_id": job_id, "items": results, "untrusted_ad_content": True}

    def export(
        self,
        job_id: str,
        format: str = "json",
        filename: str | None = None,
        webhook_environment: str | None = None,
        webhook_batch_size: int = 50,
    ) -> dict:
        if format not in ("json", "jsonl", "csv"):
            raise MCPError("invalid_format", "Choose json, jsonl or csv")
        if not 1 <= webhook_batch_size <= 100:
            raise MCPError("invalid_input", "Webhook batch size must be between 1 and 100")
        job = self.public_job(job_id)
        path = safe_path(self.output_dir, filename or f"{job_id}.{format}")
        if path.exists():
            raise MCPError("already_exists", "Choose a new export filename")
        metadata = path.with_name(path.name + ".metadata.json")
        if format != "json" and metadata.exists():
            raise MCPError("already_exists", "Choose a new export filename; its metadata sidecar already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
        count = 0
        try:
            with temp.open("w", encoding="utf-8", newline="") as stream:
                writer = None
                if format == "json":
                    stream.write('{"metadata":' + dumps(job) + ',"ads":[')
                elif format == "csv":
                    writer = csv.DictWriter(stream, fieldnames=available_fields())
                    writer.writeheader()
                for offset in range(0, job["count"], 256):
                    for record in self.store.records(job_id, min(256, job["count"] - offset), offset):
                        if format == "json":
                            stream.write(("," if count else "") + dumps(record))
                        elif format == "jsonl":
                            stream.write(dumps(record) + "\n")
                        else:
                            writer.writerow(
                                {
                                    key: dumps(value) if isinstance(value, (dict, list)) else value
                                    for key, value in record.items()
                                    if key in available_fields()
                                }
                            )
                        count += 1
                if format == "json":
                    stream.write("]}")
            try:
                os.link(temp, path)
            except FileExistsError as exc:
                raise MCPError("already_exists", "Choose a new export filename") from exc
        finally:
            temp.unlink(missing_ok=True)
        result = {"path": str(path), "count": count, "metadata": job}
        if format != "json":
            try:
                with metadata.open("x", encoding="utf-8") as stream:
                    stream.write(dumps(job))
            except FileExistsError as exc:
                path.unlink(missing_ok=True)
                raise MCPError("already_exists", "Metadata filename was claimed by another writer") from exc
            result["metadata_path"] = str(metadata)
        if webhook_environment:
            destination = private_value(webhook_environment, None, self.private_dir)
            sender = WebhookSender(destination)
            successes = failures = 0
            try:
                with self.network:
                    for offset in range(0, count, webhook_batch_size):
                        batch = self.store.records(job_id, min(webhook_batch_size, count - offset), offset)
                        delivered = sender.send(batch[0]) if webhook_batch_size == 1 else sender.send_batch(batch)
                        if delivered:
                            successes += len(batch)
                        else:
                            failures += len(batch)
            finally:
                sender._session.close()
            result["webhook"] = {"delivered": successes, "failed": failures}
        return result

    def jobs(
        self, action: str = "list", job_ids: list[str] | None = None, after: int = 0, limit: int = 50, offset: int = 0
    ) -> dict:
        if not 1 <= limit <= 100 or offset < 0 or after < 0:
            raise MCPError("invalid_input", "Invalid job pagination")
        if action == "list":
            return {"jobs": [self.public_job(j["id"]) for j in self.store.list_jobs(limit, offset)]}
        if not job_ids or len(job_ids) > 20:
            raise MCPError("invalid_input", "Provide between 1 and 20 job IDs")
        if action == "status":
            return {"jobs": [self.public_job(job_id) for job_id in job_ids]}
        if action == "events":
            return {"events": {job_id: self.store.events(job_id, after, limit) for job_id in job_ids}}
        if action in ("cancel", "resume", "delete"):
            for job_id in job_ids:
                if action == "delete":
                    lock = self.job_lock(job_id)
                    if not lock.acquire(blocking=False):
                        raise MCPError("job_active", "Cancel the job before deleting its results")
                    try:
                        with self.lock:
                            run = self.runs.pop(job_id, None)
                        if run:
                            run.close("PAUSED")
                    finally:
                        lock.release()
                    self.store.delete(job_id)
                else:
                    self.store.control(job_id, action)
                    if action == "resume":
                        self.submit(job_id)
                    else:
                        lock = self.job_lock(job_id)
                        if lock.acquire(blocking=False):
                            try:
                                with self.lock:
                                    run = self.runs.pop(job_id, None)
                                if run:
                                    run.close("CANCELLED")
                            finally:
                                lock.release()
            return {"action": action, "job_ids": job_ids}
        if action == "report":
            reports = []
            for job_id in job_ids:
                job = self.public_job(job_id)
                stats = job["stats"]
                report = CollectionReport(
                    total_collected=job["count"],
                    duplicates_skipped=stats.get("duplicates_skipped", 0),
                    filtered_out=stats.get("filtered_out", 0),
                    errors=stats.get("errors", 0),
                    duration_seconds=stats.get("active_seconds", 0),
                )
                reports.append(
                    {"job": job, "text": format_report(report), "report": json.loads(format_report_json(report))}
                )
            return {"reports": reports}
        raise MCPError("invalid_action", "Unsupported job action")

    def proxy(self, action: str = "list", profile: ProxyProfile | None = None, name: str | None = None) -> dict:
        if action == "list":
            return {
                "profiles": [public_profile(p) for p in self.store.profiles()],
                "default": self.store.setting("default_proxy"),
            }
        if action == "configure":
            if profile is None:
                raise MCPError("invalid_input", "Provide a proxy profile")
            proxy_from(profile.model_dump(), self.private_dir)
            self.store.save_profile(profile.model_dump())
            return {"profile": public_profile(profile.model_dump())}
        if action == "default":
            if not name:
                raise MCPError("invalid_input", "Provide a profile name")
            self.store.profile(name)
            self.store.setting("default_proxy", name)
            return {"default": name}
        if action == "clear_default":
            self.store.clear_setting("default_proxy")
            return {"default": None}
        if action == "check":
            with self.network, self.collector(name) as collector:
                pages = collector.search_pages("coca cola", "US")
            if not pages:
                raise MCPError("connectivity_unverified", "Meta returned no candidates; connectivity was not verified")
            return {"connected": True, "source": "real_meta_typeahead", "candidate_count": len(pages)}
        raise MCPError("invalid_action", "Unsupported proxy action")

    def monitoring(
        self, action: str = "list", schedule: Schedule | None = None, schedule_id: str | None = None
    ) -> dict:
        if action == "list":
            return {"schedules": self.store.schedules(), "persistent_worker_alive": self.store.worker_alive()}
        if action == "create":
            if schedule is None:
                raise MCPError("invalid_input", "Provide a schedule")
            config = schedule.model_dump(mode="json")
            config["search"] = self.freeze(schedule.search)
            return {"schedule_id": self.store.schedule(config), "requires_running_process": True}
        if action in ("enable", "disable", "delete"):
            if not schedule_id:
                raise MCPError("invalid_input", "Provide a schedule ID")
            self.store.set_schedule(schedule_id, action)
            return {"schedule_id": schedule_id, "action": action}
        raise MCPError("invalid_action", "Unsupported monitoring action")

    def submit(self, job_id: str):
        with self.lock:
            existing = self.futures.get(job_id)
            if existing and not existing.done():
                return
            self.futures[job_id] = self.executor.submit(self.execute, job_id, 100, True)

    def tick(self):
        self.store.due()
        with self.lock:
            self.futures = {key: future for key, future in self.futures.items() if not future.done()}
            capacity = max(0, self.max_concurrency - len(self.futures))
        for job_id in self.store.pending(capacity):
            self.submit(job_id)
        if self.persistent:
            self.store.worker_heartbeat(self.owner)

    def start(self, persistent: bool = False):
        self.persistent = persistent
        if persistent:
            self.store.worker_heartbeat(self.owner)

        def loop():
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    # Preserve durable pending jobs; a subsequent tick can retry storage contention.
                    logging.getLogger(__name__).warning("Scheduling pass failed: %s", redact(str(exc)))
                self.stop.wait(1)

        self.scheduler = threading.Thread(target=loop, name="metaads-monitor", daemon=True)
        self.scheduler.start()

    def close(self):
        self.stop.set()
        if self.scheduler:
            self.scheduler.join(timeout=3)
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            runs = list(self.runs.values())
            self.runs.clear()
        for run in runs:
            run.close("CANCELLED" if self.store.job(run.job_id)["cancel"] else "PAUSED")
        if self.persistent:
            self.store.worker_heartbeat(self.owner, remove=True)
