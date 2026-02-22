"""Async collector for Meta Ad Library.

Mirrors :class:`~meta_ads_collector.collector.MetaAdsCollector` method-for-
method but uses ``async`` / ``await`` throughout.  Uses
``curl_cffi.requests.AsyncSession`` with Chrome TLS impersonation.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .async_client import AsyncMetaAdsClient
from .constants import (
    AD_TYPE_ALL,
    AD_TYPE_CREDIT,
    AD_TYPE_EMPLOYMENT,
    AD_TYPE_HOUSING,
    AD_TYPE_POLITICAL,
    DEFAULT_JITTER,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RATE_LIMIT_DELAY,
    DEFAULT_TIMEOUT,
    SEARCH_EXACT,
    SEARCH_KEYWORD,
    SEARCH_PAGE,
    SEARCH_UNORDERED,
    SORT_IMPRESSIONS,
    SORT_RELEVANCY,
    STATUS_ACTIVE,
    STATUS_ALL,
    STATUS_INACTIVE,
    VALID_AD_TYPES,
    VALID_SEARCH_TYPES,
    VALID_SORT_MODES,
    VALID_STATUSES,
)
from .dedup import DeduplicationTracker
from .events import (
    AD_COLLECTED,
    COLLECTION_FINISHED,
    COLLECTION_STARTED,
    ERROR_OCCURRED,
    PAGE_FETCHED,
    RATE_LIMITED,
    SESSION_REFRESHED,
    EventEmitter,
)
from .exceptions import InvalidParameterError
from .filters import FilterConfig, passes_filter
from .models import Ad, PageSearchResult
from .proxy_pool import ProxyPool

logger = logging.getLogger(__name__)


class AsyncMetaAdsCollector:
    """Async collector for Meta Ad Library ads.

    Mirrors the API of :class:`~meta_ads_collector.collector.MetaAdsCollector`
    with ``async def`` methods and ``async for`` generators.

    Supports ``async with`` for resource cleanup::

        async with AsyncMetaAdsCollector() as collector:
            async for ad in collector.search(query="test"):
                print(ad.id)
    """

    # Ad type constants
    AD_TYPE_ALL = AD_TYPE_ALL
    AD_TYPE_POLITICAL = AD_TYPE_POLITICAL
    AD_TYPE_HOUSING = AD_TYPE_HOUSING
    AD_TYPE_EMPLOYMENT = AD_TYPE_EMPLOYMENT
    AD_TYPE_CREDIT = AD_TYPE_CREDIT

    # Status constants
    STATUS_ACTIVE = STATUS_ACTIVE
    STATUS_INACTIVE = STATUS_INACTIVE
    STATUS_ALL = STATUS_ALL

    # Search type constants
    SEARCH_KEYWORD = SEARCH_KEYWORD
    SEARCH_EXACT = SEARCH_EXACT
    SEARCH_UNORDERED = SEARCH_UNORDERED
    SEARCH_PAGE = SEARCH_PAGE

    # Sort constants
    SORT_RELEVANCY = SORT_RELEVANCY
    SORT_IMPRESSIONS = SORT_IMPRESSIONS

    def __init__(
        self,
        proxy: str | list[str] | ProxyPool | None = None,
        rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
        jitter: float = DEFAULT_JITTER,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        callbacks: dict[str, Callable] | None = None,
    ) -> None:
        """Initialize the async collector.

        Args:
            proxy: Proxy configuration.
            rate_limit_delay: Base delay between requests (seconds).
            jitter: Random jitter added to delay (seconds).
            timeout: Request timeout (seconds).
            max_retries: Maximum retry attempts per request.
            callbacks: Optional mapping of event type strings to callbacks.
        """
        self.client = AsyncMetaAdsClient(
            proxy=proxy,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.rate_limit_delay = rate_limit_delay
        self.jitter = jitter

        # Event emitter
        self.event_emitter = EventEmitter()
        if callbacks:
            for event_type, cb in callbacks.items():
                self.event_emitter.on(event_type, cb)

        # Collection statistics
        self.stats: dict[str, Any] = {
            "requests_made": 0,
            "ads_collected": 0,
            "pages_fetched": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

    async def _delay(self) -> None:
        """Apply async rate limiting delay with jitter."""
        import asyncio
        delay = self.rate_limit_delay + random.uniform(0, self.jitter)
        await asyncio.sleep(delay)

    @staticmethod
    def _validate_params(
        ad_type: str,
        status: str,
        search_type: str,
        sort_by: str | None,
        country: str,
    ) -> None:
        """Validate public API parameters."""
        if ad_type not in VALID_AD_TYPES:
            raise InvalidParameterError("ad_type", ad_type, VALID_AD_TYPES)
        if status not in VALID_STATUSES:
            raise InvalidParameterError("status", status, VALID_STATUSES)
        if search_type not in VALID_SEARCH_TYPES:
            raise InvalidParameterError("search_type", search_type, VALID_SEARCH_TYPES)
        if sort_by not in VALID_SORT_MODES:
            raise InvalidParameterError("sort_by", sort_by, VALID_SORT_MODES)
        if not country or len(country) != 2 or not country.isalpha():
            raise InvalidParameterError(
                "country", country,
                "a 2-letter ISO 3166-1 alpha-2 code (e.g. 'US', 'EG')",
            )

    async def search_pages(
        self,
        query: str,
        country: str = "US",
    ) -> list[PageSearchResult]:
        """Search for pages by name (async version).

        Same parameters and return type as the sync
        :meth:`~meta_ads_collector.collector.MetaAdsCollector.search_pages`.
        """
        raw_pages = await self.client.search_pages(query=query, country=country)
        results: list[PageSearchResult] = []
        for page_data in raw_pages:
            try:
                result = PageSearchResult(
                    page_id=page_data.get("page_id", ""),
                    page_name=page_data.get("page_name", ""),
                    page_profile_uri=page_data.get("page_profile_uri"),
                    page_alias=page_data.get("page_alias"),
                    page_logo_url=page_data.get("page_logo_url"),
                    page_verified=page_data.get("page_verified"),
                    page_like_count=page_data.get("page_like_count"),
                    category=page_data.get("category"),
                )
                if result.page_id:
                    results.append(result)
            except Exception as exc:
                logger.warning("Failed to parse page search result: %s", exc)
        return results

    async def search(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: list[str] | None = None,
        sort_by: str | None = SORT_IMPRESSIONS,
        max_results: int | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        progress_callback: Callable[[int, int], None] | None = None,
        filter_config: FilterConfig | None = None,
        dedup_tracker: DeduplicationTracker | None = None,
    ) -> AsyncIterator[Ad]:
        """Search for ads and yield results as an async generator.

        Same parameters as the sync
        :meth:`~meta_ads_collector.collector.MetaAdsCollector.search`.

        Yields:
            :class:`Ad` objects as they are collected.
        """
        import asyncio
        import uuid

        country = country.upper()
        self._validate_params(ad_type, status, search_type, sort_by, country)

        self.stats["start_time"] = datetime.now(timezone.utc)
        cursor = None
        collected = 0
        page_number = 0
        search_start_time = time.monotonic()

        search_session_id = str(uuid.uuid4())
        search_collation_token = str(uuid.uuid4())

        logger.info("Starting async search: query='%s', country=%s", query, country)

        self.event_emitter.emit(COLLECTION_STARTED, {
            "query": query,
            "country": country,
            "ad_type": ad_type,
            "status": status,
            "search_type": search_type,
            "page_ids": page_ids,
            "max_results": max_results,
        })

        try:
            while True:
                if max_results and collected >= max_results:
                    break

                retry_count = 0
                max_retries_inner = 3
                response = None

                while retry_count < max_retries_inner:
                    try:
                        self.stats["requests_made"] += 1
                        response, next_cursor = await self.client.search_ads(
                            query=query,
                            country=country,
                            ad_type=ad_type,
                            active_status=status,
                            search_type=search_type,
                            page_ids=page_ids,
                            cursor=cursor,
                            first=page_size,
                            sort_mode=sort_by,
                            session_id=search_session_id,
                            collation_token=search_collation_token,
                        )

                        if response.get("rate_limited"):
                            retry_count += 1
                            wait_time = 5 * retry_count + random.uniform(1, 3)
                            self.event_emitter.emit(RATE_LIMITED, {
                                "wait_seconds": wait_time,
                                "retry_count": retry_count,
                            })
                            if retry_count < max_retries_inner:
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                self.stats["errors"] += 1
                                self.event_emitter.emit(ERROR_OCCURRED, {
                                    "exception": None,
                                    "context": "Max retries exceeded due to rate limiting",
                                })
                                return

                        if response.get("session_expired"):
                            retry_count += 1
                            self.event_emitter.emit(SESSION_REFRESHED, {
                                "reason": "session_expired",
                            })
                            if retry_count < max_retries_inner:
                                await asyncio.sleep(2)
                                continue
                            else:
                                self.stats["errors"] += 1
                                self.event_emitter.emit(ERROR_OCCURRED, {
                                    "exception": None,
                                    "context": "Max retries exceeded due to session expiry",
                                })
                                return

                        self.stats["pages_fetched"] += 1
                        page_number += 1
                        break

                    except Exception as e:
                        self.stats["errors"] += 1
                        self.event_emitter.emit(ERROR_OCCURRED, {
                            "exception": e,
                            "context": f"Search request failed on retry {retry_count + 1}",
                        })
                        retry_count += 1
                        if retry_count >= max_retries_inner:
                            raise
                        await asyncio.sleep(3 * retry_count)

                if response is None:
                    break

                ads_data = response.get("ads", [])
                if not ads_data:
                    break

                has_next = bool(next_cursor)
                self.event_emitter.emit(PAGE_FETCHED, {
                    "page_number": page_number,
                    "ads_on_page": len(ads_data),
                    "has_next_page": has_next,
                })

                for ad_data in ads_data:
                    if max_results and collected >= max_results:
                        break

                    try:
                        ad = Ad.from_graphql_response(ad_data)

                        if dedup_tracker is not None and dedup_tracker.has_seen(ad.id):
                            continue

                        if filter_config is not None and not passes_filter(ad, filter_config):
                            continue

                        collected += 1
                        self.stats["ads_collected"] += 1

                        if progress_callback:
                            progress_callback(collected, max_results or -1)

                        self.event_emitter.emit(AD_COLLECTED, {"ad": ad})
                        yield ad

                        if dedup_tracker is not None:
                            dedup_tracker.mark_seen(ad.id)

                    except Exception as e:
                        self.stats["errors"] += 1
                        self.event_emitter.emit(ERROR_OCCURRED, {
                            "exception": e,
                            "context": "Failed to parse ad from response",
                        })
                        continue

                if not next_cursor:
                    break

                cursor = next_cursor
                await self._delay()

        finally:
            self.stats["end_time"] = datetime.now(timezone.utc)
            duration = time.monotonic() - search_start_time
            if dedup_tracker is not None:
                dedup_tracker.update_collection_time()
                dedup_tracker.save()
            self.event_emitter.emit(COLLECTION_FINISHED, {
                "total_ads": collected,
                "total_pages": page_number,
                "duration_seconds": duration,
            })

    async def collect(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: list[str] | None = None,
        sort_by: str | None = SORT_IMPRESSIONS,
        max_results: int | None = None,
        page_size: int = 10,
        filter_config: FilterConfig | None = None,
        dedup_tracker: DeduplicationTracker | None = None,
    ) -> list[Ad]:
        """Collect ads and return as a list (async version).

        Same parameters as sync
        :meth:`~meta_ads_collector.collector.MetaAdsCollector.collect`.
        """
        ads: list[Ad] = []
        async for ad in self.search(
            query=query,
            country=country,
            ad_type=ad_type,
            status=status,
            search_type=search_type,
            page_ids=page_ids,
            sort_by=sort_by,
            max_results=max_results,
            page_size=page_size,
            filter_config=filter_config,
            dedup_tracker=dedup_tracker,
        ):
            ads.append(ad)
        return ads

    async def collect_to_json(
        self,
        output_path: str,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: list[str] | None = None,
        sort_by: str | None = SORT_IMPRESSIONS,
        max_results: int | None = None,
        page_size: int = 10,
        include_raw: bool = False,
        indent: int = 2,
        filter_config: FilterConfig | None = None,
        dedup_tracker: DeduplicationTracker | None = None,
    ) -> int:
        """Collect ads and save to JSON (async version)."""
        ads_dicts: list[dict[str, Any]] = []
        async for ad in self.search(
            query=query, country=country, ad_type=ad_type,
            status=status, search_type=search_type, page_ids=page_ids,
            sort_by=sort_by, max_results=max_results, page_size=page_size,
            filter_config=filter_config, dedup_tracker=dedup_tracker,
        ):
            ads_dicts.append(ad.to_dict(include_raw=include_raw))

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        output: dict[str, Any] = {
            "metadata": {
                "query": query,
                "country": country,
                "ad_type": ad_type,
                "status": status,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "total_count": len(ads_dicts),
            },
            "ads": ads_dicts,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=indent, ensure_ascii=False)

        return len(ads_dicts)

    async def collect_to_csv(
        self,
        output_path: str,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: list[str] | None = None,
        sort_by: str | None = SORT_IMPRESSIONS,
        max_results: int | None = None,
        page_size: int = 10,
        filter_config: FilterConfig | None = None,
        dedup_tracker: DeduplicationTracker | None = None,
    ) -> int:
        """Collect ads and save to CSV (async version)."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        columns = [
            "id", "page_id", "page_name", "page_url", "is_active",
            "ad_status", "delivery_start_time", "delivery_stop_time",
            "creative_body", "creative_title", "creative_description",
            "creative_link_url", "creative_image_url", "snapshot_url",
            "impressions_lower", "impressions_upper", "spend_lower",
            "spend_upper", "currency", "publisher_platforms", "languages",
            "funding_entity", "disclaimer", "ad_type", "collected_at",
        ]

        count = 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            async for ad in self.search(
                query=query, country=country, ad_type=ad_type,
                status=status, search_type=search_type, page_ids=page_ids,
                sort_by=sort_by, max_results=max_results, page_size=page_size,
                filter_config=filter_config, dedup_tracker=dedup_tracker,
            ):
                primary = ad.creatives[0] if ad.creatives else None
                row = {
                    "id": ad.id,
                    "page_id": ad.page.id if ad.page else "",
                    "page_name": ad.page.name if ad.page else "",
                    "page_url": ad.page.page_url if ad.page else "",
                    "is_active": ad.is_active if ad.is_active is not None else "",
                    "ad_status": ad.ad_status or "",
                    "delivery_start_time": ad.delivery_start_time.isoformat() if ad.delivery_start_time else "",
                    "delivery_stop_time": ad.delivery_stop_time.isoformat() if ad.delivery_stop_time else "",
                    "creative_body": primary.body if primary else "",
                    "creative_title": primary.title if primary else "",
                    "creative_description": primary.description if primary else "",
                    "creative_link_url": primary.link_url if primary else "",
                    "creative_image_url": primary.image_url if primary else "",
                    "snapshot_url": ad.snapshot_url or ad.ad_snapshot_url or "",
                    "impressions_lower": ad.impressions.lower_bound if ad.impressions else "",
                    "impressions_upper": ad.impressions.upper_bound if ad.impressions else "",
                    "spend_lower": ad.spend.lower_bound if ad.spend else "",
                    "spend_upper": ad.spend.upper_bound if ad.spend else "",
                    "currency": ad.currency or "",
                    "publisher_platforms": ",".join(ad.publisher_platforms),
                    "languages": ",".join(ad.languages),
                    "funding_entity": ad.funding_entity or "",
                    "disclaimer": ad.disclaimer or "",
                    "ad_type": ad.ad_type or "",
                    "collected_at": ad.collected_at.isoformat(),
                }
                writer.writerow(row)
                count += 1

        return count

    def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        stats = self.stats.copy()
        if stats["start_time"] and stats["end_time"]:
            duration = (stats["end_time"] - stats["start_time"]).total_seconds()
            stats["duration_seconds"] = duration
            if duration > 0:
                stats["ads_per_second"] = stats["ads_collected"] / duration
        return stats

    async def close(self) -> None:
        """Close the collector and cleanup resources."""
        await self.client.close()

    async def __aenter__(self) -> AsyncMetaAdsCollector:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
