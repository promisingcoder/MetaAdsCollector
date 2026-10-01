"""
Meta Ads Library Collector

High-level interface for collecting ads from the Meta Ad Library.
Handles pagination, rate limiting, and data storage.
"""

import csv
import json
import logging
import random
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Union

from .client import MetaAdsClient
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
from .exceptions import (
    InvalidParameterError,
    MetaAdsError,
    RateLimitError,
    SessionExpiredError,
)
from .filters import FilterConfig, passes_filter
from .media import MediaDownloader, MediaDownloadResult
from .models import Ad, PageSearchResult
from .proxy_pool import ProxyPool
from .url_parser import extract_page_id_from_url

logger = logging.getLogger(__name__)


class MetaAdsCollector:
    """
    High-level collector for Meta Ad Library ads.

    Provides an easy-to-use interface for searching and collecting ads
    with automatic pagination, rate limiting, and multiple export formats.
    """

    # Ad type constants (aliases for convenience)
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
    SORT_DATE = None  # Not supported; falls back to server-default

    def __init__(
        self,
        proxy: Optional[Union[str, list[str], ProxyPool]] = None,
        rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
        jitter: float = DEFAULT_JITTER,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        callbacks: Optional[dict[str, Callable]] = None,
        cookies: Optional[Union[dict, str]] = None,
    ):
        """
        Initialize the collector.

        Args:
            proxy: Proxy configuration. Accepts a single proxy string,
                a list of proxy strings, a ProxyPool instance, or None.
            rate_limit_delay: Base delay between requests (seconds)
            jitter: Random jitter to add to delay (seconds)
            timeout: Request timeout (seconds)
            max_retries: Maximum retry attempts per request
            callbacks: Optional mapping of event type strings to callback
                functions for convenience registration. Example::

                    {"ad_collected": my_callback, "error_occurred": my_error_handler}
            cookies: Optional cookies to seed the HTTP session with,
                either a ``{name: value}`` dict or a ``"k=v; k2=v2"``
                header string (e.g. copied from a logged-in browser).
                Passed through to :class:`MetaAdsClient`.
        """
        self.client = MetaAdsClient(
            proxy=proxy,
            timeout=timeout,
            max_retries=max_retries,
            cookies=cookies,
        )
        self.rate_limit_delay = rate_limit_delay
        self.jitter = jitter

        # Event emitter for lifecycle events
        self.event_emitter = EventEmitter()
        if callbacks:
            for event_type, cb in callbacks.items():
                self.event_emitter.on(event_type, cb)

        # Collection statistics
        self.stats: dict[str, Any] = {
            "requests_made": 0,
            "ads_collected": 0,
            "duplicates_skipped": 0,
            "filtered_out": 0,
            "pages_fetched": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

    def search_pages(
        self,
        query: str,
        country: str = "US",
    ) -> list[PageSearchResult]:
        """Search for Facebook pages by name using the typeahead endpoint.

        This is useful for resolving a human-readable page name to its
        numeric page ID, which can then be passed to :meth:`search` via
        ``page_ids``.

        Args:
            query: The page name or search string (e.g. "Coca-Cola").
            country: ISO 3166-1 alpha-2 country code (default ``"US"``).

        Returns:
            A list of :class:`PageSearchResult` objects. Returns an empty
            list when no matches are found or on error.
        """
        raw_pages = self.client.search_pages(query=query, country=country)

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
                continue

        return results

    def collect_by_page_id(
        self,
        page_id: str,
        **kwargs: Any,
    ) -> Iterator[Ad]:
        """Collect all ads from a specific Facebook page by its numeric ID.

        This is a convenience wrapper around :meth:`search` that sets
        ``page_ids=[page_id]`` and ``search_type=PAGE``.

        Args:
            page_id: Numeric page ID (e.g. ``"123456"``).
            **kwargs: Additional keyword arguments forwarded to :meth:`search`
                (e.g. ``country``, ``max_results``, ``ad_type``).

        Yields:
            :class:`Ad` objects.
        """
        kwargs.setdefault("search_type", SEARCH_PAGE)
        kwargs["page_ids"] = [page_id]
        yield from self.search(**kwargs)

    def collect_by_page_url(
        self,
        url: str,
        **kwargs: Any,
    ) -> Iterator[Ad]:
        """Collect all ads from a Facebook page identified by URL.

        Parses the URL to extract a numeric page ID, then delegates to
        :meth:`collect_by_page_id`.  If the URL is a vanity URL that
        cannot be resolved without a network call, a warning is logged
        and an empty iterator is returned.

        Args:
            url: A Facebook page URL (Ad Library URL, profile URL, or
                direct numeric page URL).
            **kwargs: Additional keyword arguments forwarded to :meth:`search`.

        Yields:
            :class:`Ad` objects.
        """
        page_id = extract_page_id_from_url(url)
        if not page_id:
            logger.warning(
                "Could not extract page ID from URL: %s. "
                "If this is a vanity URL, use search_pages() to resolve it first.",
                url,
            )
            return
        yield from self.collect_by_page_id(page_id, **kwargs)

    def collect_by_page_name(
        self,
        page_name: str,
        country: str = "US",
        **kwargs: Any,
    ) -> Iterator[Ad]:
        """Search for a page by name, then collect its ads.

        Uses the typeahead endpoint to find the page, selects the first
        result, and then collects ads for that page.

        Args:
            page_name: The page name to search for.
            country: Country code for the typeahead search.
            **kwargs: Additional keyword arguments forwarded to :meth:`search`.

        Yields:
            :class:`Ad` objects.
        """
        pages = self.search_pages(query=page_name, country=country)
        if not pages:
            logger.warning("No pages found for name: %s", page_name)
            return
        best = pages[0]
        logger.info(
            "Resolved page name %r to page ID %s (%s)",
            page_name,
            best.page_id,
            best.page_name,
        )
        kwargs.setdefault("country", country)
        yield from self.collect_by_page_id(best.page_id, **kwargs)

    def _delay(self) -> None:
        """Apply rate limiting delay with jitter."""
        delay = self.rate_limit_delay + random.uniform(0, self.jitter)
        time.sleep(delay)

    @staticmethod
    def _validate_params(
        ad_type: str,
        status: str,
        search_type: str,
        sort_by: Optional[str],
        country: str,
    ) -> None:
        """Validate public API parameters and raise on invalid values."""
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
                "country", country, "a 2-letter ISO 3166-1 alpha-2 code (e.g. 'US', 'EG')"
            )

    def search(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> Iterator[Ad]:
        """
        Search for ads and yield results as Ad objects.

        Args:
            query: Search query string
            country: Country code (e.g., "US", "EG", "GB")
            ad_type: Type of ads to search for
            status: Active status filter
            search_type: Type of search (keyword, exact, page)
            page_ids: Filter by specific page IDs
            sort_by: Sort order (SORT_BY_TOTAL_IMPRESSIONS or None for relevancy)
            max_results: Maximum number of ads to collect (None for no limit)
            page_size: Results per API request (max ~30)
            progress_callback: Optional callback(collected, total) for progress updates
            filter_config: Optional client-side filter configuration
            dedup_tracker: Optional deduplication tracker to skip already-seen ads

        Yields:
            Ad objects as they are collected
        """
        import uuid

        country = country.upper()
        self._validate_params(ad_type, status, search_type, sort_by, country)
        if max_results is not None and (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or max_results < 0
        ):
            raise InvalidParameterError(
                "max_results", max_results, "a non-negative integer or None"
            )

        self.stats["start_time"] = datetime.now(timezone.utc)
        cursor = None
        seen_cursors: set[str] = set()
        consecutive_empty_pages = 0
        collected = 0
        page_number = 0
        search_completed = False
        had_parse_errors = False
        search_start_time = time.monotonic()

        # Generate consistent session_id and collation_token for the entire search
        search_session_id = str(uuid.uuid4())
        search_collation_token = str(uuid.uuid4())

        logger.info(f"Starting search: query='{query}', country={country}, ad_type={ad_type}")

        # Emit collection_started
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
                # Check if we've hit our limit
                if max_results is not None and collected >= max_results:
                    logger.info(f"Reached max_results limit: {max_results}")
                    break

                # Make the API request with retry logic
                retry_count = 0
                max_retries = 3
                response = None
                response_error: MetaAdsError | None = None

                while retry_count < max_retries:
                    try:
                        self.stats["requests_made"] += 1
                        try:
                            response, next_cursor = self.client.search_ads(
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
                        except MetaAdsError as client_error:
                            self.stats["errors"] += 1
                            self.event_emitter.emit(ERROR_OCCURRED, {
                                "exception": client_error,
                                "context": "Search client raised an error",
                            })
                            raise

                        # Check for rate limiting
                        if response.get("rate_limited"):
                            retry_count += 1
                            wait_time = 5 * retry_count + random.uniform(1, 3)
                            self.event_emitter.emit(RATE_LIMITED, {
                                "wait_seconds": wait_time,
                                "retry_count": retry_count,
                            })
                            if retry_count < max_retries:
                                logger.warning(
                                    f"Rate limited, waiting {wait_time:.1f}s "
                                    f"before retry {retry_count}/{max_retries}"
                                )
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error("Max retries exceeded due to rate limiting")
                                self.stats["errors"] += 1
                                rate_limit_error: MetaAdsError = RateLimitError(
                                    "Max retries exceeded due to rate limiting",
                                    retry_after=wait_time,
                                )
                                self.event_emitter.emit(ERROR_OCCURRED, {
                                    "exception": rate_limit_error,
                                    "context": "Max retries exceeded due to rate limiting",
                                })
                                raise rate_limit_error

                        # Check for session expiry - client handles refresh,
                        # we just need to retry the request
                        if response.get("session_expired"):
                            retry_count += 1
                            self.event_emitter.emit(SESSION_REFRESHED, {
                                "reason": "session_expired",
                            })
                            if retry_count < max_retries:
                                logger.warning(f"Session expired, retrying ({retry_count}/{max_retries})...")
                                time.sleep(2)
                                continue
                            else:
                                logger.error("Max retries exceeded due to session expiry")
                                self.stats["errors"] += 1
                                session_expired_error = SessionExpiredError(
                                    "Max retries exceeded due to session expiry"
                                )
                                self.event_emitter.emit(ERROR_OCCURRED, {
                                    "exception": session_expired_error,
                                    "context": "Max retries exceeded due to session expiry",
                                })
                                raise session_expired_error

                        if response.get("error"):
                            response_error = MetaAdsError(str(response["error"]))
                            break

                        self.stats["pages_fetched"] += 1
                        page_number += 1
                        break  # Success, exit retry loop

                    except MetaAdsError:
                        raise
                    except Exception as e:
                        logger.error(f"Search request failed: {e}")
                        self.stats["errors"] += 1
                        self.event_emitter.emit(ERROR_OCCURRED, {
                            "exception": e,
                            "context": f"Search request failed on retry {retry_count + 1}",
                        })
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise
                        time.sleep(3 * retry_count)

                if response_error is not None:
                    self.stats["errors"] += 1
                    self.event_emitter.emit(ERROR_OCCURRED, {
                        "exception": response_error,
                        "context": "Search response contained an error",
                    })
                    raise response_error

                if response is None:
                    logger.error("No response received after retries")
                    break

                # Process results
                ads_data = response.get("ads", [])

                if not ads_data and not next_cursor:
                    logger.info("No more results returned")
                    search_completed = not had_parse_errors
                    break

                self.event_emitter.emit(PAGE_FETCHED, {
                    "page_number": page_number,
                    "ads_on_page": len(ads_data),
                    "has_next_page": bool(next_cursor),
                })

                if not ads_data:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages > 25:
                        empty_pages_error = MetaAdsError(
                            "Exceeded 25 consecutive empty pages with pagination cursors"
                        )
                        self.stats["errors"] += 1
                        self.event_emitter.emit(ERROR_OCCURRED, {
                            "exception": empty_pages_error,
                            "context": "Too many consecutive empty pages",
                        })
                        raise empty_pages_error
                else:
                    consecutive_empty_pages = 0

                limit_reached = False
                for ad_data in ads_data:
                    if max_results is not None and collected >= max_results:
                        limit_reached = True
                        break

                    try:
                        ad = Ad.from_graphql_response(ad_data)

                        # Skip already-seen ads
                        if dedup_tracker is not None and dedup_tracker.has_seen(ad.id):
                            self.stats["duplicates_skipped"] = (
                                self.stats.get("duplicates_skipped", 0) + 1
                            )
                            continue

                        # Apply client-side filters
                        if filter_config is not None and not passes_filter(ad, filter_config):
                            self.stats["filtered_out"] = (
                                self.stats.get("filtered_out", 0) + 1
                            )
                            continue

                    except Exception as e:
                        logger.warning(f"Failed to parse ad: {e}")
                        self.stats["errors"] += 1
                        had_parse_errors = True
                        self.event_emitter.emit(ERROR_OCCURRED, {
                            "exception": e,
                            "context": "Failed to parse ad from response",
                        })
                        continue

                    next_collected = collected + 1
                    if progress_callback:
                        try:
                            progress_callback(
                                next_collected,
                                max_results if max_results is not None else -1,
                            )
                        except Exception as e:
                            self.stats["errors"] += 1
                            self.event_emitter.emit(ERROR_OCCURRED, {
                                "exception": e,
                                "context": "Progress callback failed",
                            })
                            raise

                    collected = next_collected
                    self.stats["ads_collected"] += 1
                    if dedup_tracker is not None:
                        # Persist an ad before handing it to the caller so an
                        # early iterator close cannot lose its dedup record.
                        dedup_tracker.mark_seen(ad.id)
                    self.event_emitter.emit(AD_COLLECTED, {"ad": ad})
                    yield ad

                if limit_reached:
                    break

                # Check for next page
                if not next_cursor:
                    logger.info("No more pages available")
                    search_completed = not had_parse_errors
                    break

                if max_results is not None and collected >= max_results:
                    # The cursor proves that results remain beyond this limit.
                    break

                if next_cursor in seen_cursors:
                    repeated_cursor_error = MetaAdsError(
                        f"Repeated pagination cursor detected: {next_cursor!r}"
                    )
                    self.stats["errors"] += 1
                    self.event_emitter.emit(ERROR_OCCURRED, {
                        "exception": repeated_cursor_error,
                        "context": "Repeated pagination cursor",
                    })
                    raise repeated_cursor_error

                cursor = next_cursor
                seen_cursors.add(next_cursor)
                logger.debug(f"Fetching next page (collected: {collected})")

                # Rate limiting
                self._delay()

        finally:
            self.stats["end_time"] = datetime.now(timezone.utc)
            duration = time.monotonic() - search_start_time
            # Finalise deduplication tracker
            if dedup_tracker is not None:
                if search_completed:
                    dedup_tracker.update_collection_time()
                dedup_tracker.save()
            logger.info(f"Search completed: {collected} ads collected")
            self.event_emitter.emit(COLLECTION_FINISHED, {
                "total_ads": collected,
                "total_pages": page_number,
                "duration_seconds": duration,
            })

    def stream(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Stream lifecycle events as ``(event_type, data)`` tuples.

        Registers an internal listener on **all** event types, runs
        :meth:`search`, and yields every event that is emitted during the
        collection.  This provides a single iterator interface for
        consumers who want both ad data and metadata events in one stream.

        The stream ends after the ``collection_finished`` event has been
        yielded.

        Args:
            query: Search query string.
            country: Country code.
            ad_type: Type of ads to search for.
            status: Active status filter.
            search_type: Type of search.
            page_ids: Filter by specific page IDs.
            sort_by: Sort order.
            max_results: Maximum number of ads to collect.
            page_size: Results per API request.
            filter_config: Optional client-side filter configuration.
            dedup_tracker: Optional deduplication tracker.

        Yields:
            ``(event_type_string, event_data_dict)`` tuples.
        """
        import queue as _queue

        from .events import ALL_EVENT_TYPES, COLLECTION_FINISHED, Event

        _SENTINEL = object()
        event_queue: _queue.Queue[Any] = _queue.Queue()

        def _listener(event: Event) -> None:
            event_queue.put((event.event_type, event.data))
            if event.event_type == COLLECTION_FINISHED:
                event_queue.put(_SENTINEL)

        # Register on all event types
        for et in ALL_EVENT_TYPES:
            self.event_emitter.on(et, _listener)

        try:
            # Consume the search generator to trigger event emission.
            # Since search() is synchronous and events are emitted from
            # the same thread, all events are pushed into the queue
            # during iteration.  We interleave: consume one ad from the
            # generator, then drain all queued events before consuming
            # the next ad.
            search_iter = self.search(
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
            )

            for _ad in search_iter:
                # Drain all events queued so far
                while not event_queue.empty():
                    item = event_queue.get_nowait()
                    if item is _SENTINEL:
                        return
                    yield item

            # After the generator is exhausted, drain remaining events
            # (e.g. collection_finished emitted in the finally block)
            while not event_queue.empty():
                item = event_queue.get_nowait()
                if item is _SENTINEL:
                    return
                yield item

        finally:
            # Clean up listeners
            for et in ALL_EVENT_TYPES:
                self.event_emitter.off(et, _listener)

    def collect_with_media(
        self,
        media_output_dir: Union[str, Path] = "./ad_media",
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> Iterator[tuple[Ad, list[MediaDownloadResult]]]:
        """Search for ads and download their media files.

        Works exactly like :meth:`search` but additionally downloads
        images, videos, and thumbnails for each collected ad.  Yields
        ``(ad, download_results)`` tuples.

        If media downloading fails unexpectedly for a given ad, the ad
        is still yielded with an empty results list -- **ad data is never
        lost**.

        Args:
            media_output_dir: Directory where downloaded media files are
                stored.  Created automatically if it does not exist.
            query: Search query string.
            country: Country code (e.g. ``"US"``).
            ad_type: Type of ads to search for.
            status: Active status filter.
            search_type: Type of search (keyword, exact, page).
            page_ids: Filter by specific page IDs.
            sort_by: Sort order.
            max_results: Maximum number of ads to collect.
            page_size: Results per API request.
            progress_callback: Optional progress callback.
            filter_config: Optional client-side filter configuration.
            dedup_tracker: Optional deduplication tracker.

        Yields:
            Tuples of ``(Ad, list[MediaDownloadResult])``.
        """
        downloader = MediaDownloader(
            output_dir=media_output_dir,
            session=self.client.session,
        )

        for ad in self.search(
            query=query,
            country=country,
            ad_type=ad_type,
            status=status,
            search_type=search_type,
            page_ids=page_ids,
            sort_by=sort_by,
            max_results=max_results,
            page_size=page_size,
            progress_callback=progress_callback,
            filter_config=filter_config,
            dedup_tracker=dedup_tracker,
        ):
            try:
                results = downloader.download_ad_media(ad)
            except Exception as exc:
                logger.warning(
                    "Unexpected media download failure for ad %s: %s",
                    ad.id, exc,
                )
                results = []
            yield ad, results

    def download_ad_media(
        self,
        ad: Ad,
        output_dir: Union[str, Path] = "./ad_media",
    ) -> list[MediaDownloadResult]:
        """Download media files for a single ad.

        Convenience method for users who already have an :class:`Ad`
        object and just want to download its media.

        Args:
            ad: The ad whose creatives should be downloaded.
            output_dir: Directory for downloaded files.

        Returns:
            A list of :class:`MediaDownloadResult` objects.  **Never
            raises.**
        """
        try:
            downloader = MediaDownloader(
                output_dir=output_dir,
                session=self.client.session,
            )
            return downloader.download_ad_media(ad)
        except Exception as exc:
            logger.warning(
                "Failed to download media for ad %s: %s", ad.id, exc,
            )
            return []

    def enrich_ad(self, ad: Ad) -> Ad:
        """Fetch additional detail data and merge into the ad object.

        Uses :meth:`~meta_ads_collector.client.MetaAdsClient.get_ad_details`
        to retrieve richer data from the ad detail/snapshot endpoint and
        merges non-``None`` fields into the ad.

        **FAILURE SAFE**: If detail fetching fails for ANY reason, the
        original ad object is returned completely unchanged and a warning
        is logged.  The original ad is never mutated until validated
        replacement data is available.

        Args:
            ad: The :class:`Ad` to enrich.

        Returns:
            An enriched :class:`Ad` (may be a new instance) or the
            original *ad* unchanged on failure.
        """
        try:
            page_id = ad.page.id if ad.page else None
            detail_data = self.client.get_ad_details(
                ad_archive_id=ad.id,
                page_id=page_id,
            )
        except NotImplementedError:
            logger.warning(
                "Ad detail endpoint not available for ad %s", ad.id,
            )
            return ad
        except Exception as exc:
            logger.warning(
                "Failed to fetch details for ad %s: %s", ad.id, exc,
            )
            return ad

        # Merge detail data into a *new* Ad instance, recursively filling
        # empty fields in the current model. ``None``, empty strings, empty
        # lists, and empty dictionaries are missing; False and zero are real
        # values and must be preserved.
        try:
            enriched = Ad.from_graphql_response(detail_data)
            import copy
            from dataclasses import fields, is_dataclass

            result = copy.deepcopy(ad)


            def merge_missing(current: Any, incoming: Any) -> Any:
                if incoming is None:
                    return current

                if is_dataclass(incoming):
                    if current is None:
                        return copy.deepcopy(incoming)
                    if not is_dataclass(current) or type(current) is not type(incoming):
                        return current
                    for model_field in fields(incoming):
                        field_name = model_field.name
                        setattr(
                            current,
                            field_name,
                            merge_missing(
                                getattr(current, field_name),
                                getattr(incoming, field_name),
                            ),
                        )
                    return current

                if isinstance(incoming, list):
                    if not current:
                        return copy.deepcopy(incoming)
                    if (
                        isinstance(current, list)
                        and incoming
                        and all(is_dataclass(item) for item in incoming)
                        and all(is_dataclass(item) for item in current)
                    ):
                        merged_items = [
                            merge_missing(current[index], item)
                            if index < len(current) else copy.deepcopy(item)
                            for index, item in enumerate(incoming)
                        ]
                        if len(current) > len(merged_items):
                            merged_items.extend(current[len(merged_items):])
                        return merged_items
                    return current

                if isinstance(incoming, dict):
                    if not current:
                        return copy.deepcopy(incoming)
                    if not isinstance(current, dict):
                        return current
                    merged_dict = copy.deepcopy(current)
                    for key, value in incoming.items():
                        merged_dict[key] = merge_missing(merged_dict.get(key), value)
                    return merged_dict

                if current is None or current == "":
                    return copy.deepcopy(incoming)
                return current

            for model_field in fields(result):
                if model_field.name == "id":
                    continue
                setattr(
                    result,
                    model_field.name,
                    merge_missing(
                        getattr(result, model_field.name),
                        getattr(enriched, model_field.name),
                    ),
                )

            logger.debug("Enriched ad %s successfully", ad.id)
            return result

        except Exception as exc:
            logger.warning(
                "Failed to merge detail data for ad %s: %s", ad.id, exc,
            )
            return ad

    def collect(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> list[Ad]:
        """
        Collect ads and return as a list.

        Same parameters as search(), but returns all results at once.
        """
        return list(self.search(
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
        ))

    def collect_to_json(
        self,
        output_path: str,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
        include_raw: bool = False,
        indent: int = 2,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> int:
        """
        Collect ads and save to a JSON file.

        Args:
            output_path: Path to output JSON file
            include_raw: Include raw API response data
            indent: JSON indentation
            filter_config: Optional client-side filter configuration
            dedup_tracker: Optional deduplication tracker to skip already-seen ads
            ... (other args same as search)

        Returns:
            Number of ads collected
        """
        ads = []

        for ad in self.search(
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
            ads.append(ad.to_dict(include_raw=include_raw))

        stats_copy = self.stats.copy()

        # Convert datetime objects in stats
        if stats_copy["start_time"]:
            stats_copy["start_time"] = stats_copy["start_time"].isoformat()
        if stats_copy["end_time"]:
            stats_copy["end_time"] = stats_copy["end_time"].isoformat()

        output: dict[str, Any] = {
            "metadata": {
                "query": query,
                "country": country,
                "ad_type": ad_type,
                "status": status,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "total_count": len(ads),
                "stats": stats_copy,
            },
            "ads": ads,
        }

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=indent, ensure_ascii=False)

        logger.info(f"Saved {len(ads)} ads to {output_path}")
        return len(ads)

    def collect_to_csv(
        self,
        output_path: str,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> int:
        """
        Collect ads and save to a CSV file.

        Args:
            output_path: Path to output CSV file
            filter_config: Optional client-side filter configuration
            dedup_tracker: Optional deduplication tracker to skip already-seen ads
            ... (other args same as search)

        Returns:
            Number of ads collected
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Define CSV columns (flattened schema)
        columns = [
            "id",
            "page_id",
            "page_name",
            "page_url",
            "is_active",
            "ad_status",
            "delivery_start_time",
            "delivery_stop_time",
            "creative_body",
            "creative_title",
            "creative_description",
            "creative_link_url",
            "creative_image_url",
            "snapshot_url",
            "impressions_lower",
            "impressions_upper",
            "spend_lower",
            "spend_upper",
            "currency",
            "publisher_platforms",
            "languages",
            "funding_entity",
            "disclaimer",
            "ad_type",
            "collected_at",
            "api_fields",
        ]

        count = 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            for ad in self.search(
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
                # Flatten ad data for CSV
                primary_creative = ad.creatives[0] if ad.creatives else None

                row = {
                    "id": ad.id,
                    "page_id": ad.page.id if ad.page else "",
                    "page_name": ad.page.name if ad.page else "",
                    "page_url": ad.page.page_url if ad.page else "",
                    "is_active": ad.is_active if ad.is_active is not None else "",
                    "ad_status": ad.ad_status or "",
                    "delivery_start_time": ad.delivery_start_time.isoformat() if ad.delivery_start_time else "",
                    "delivery_stop_time": ad.delivery_stop_time.isoformat() if ad.delivery_stop_time else "",
                    "creative_body": primary_creative.body if primary_creative else "",
                    "creative_title": primary_creative.title if primary_creative else "",
                    "creative_description": primary_creative.description if primary_creative else "",
                    "creative_link_url": primary_creative.link_url if primary_creative else "",
                    "creative_image_url": primary_creative.image_url if primary_creative else "",
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
                    "api_fields": json.dumps(ad.api_fields, ensure_ascii=False),
                }

                writer.writerow(row)
                count += 1

        logger.info(f"Saved {count} ads to {output_path}")
        return count

    def collect_to_jsonl(
        self,
        output_path: str,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[list[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
        include_raw: bool = False,
        filter_config: Optional[FilterConfig] = None,
        dedup_tracker: Optional[DeduplicationTracker] = None,
    ) -> int:
        """
        Collect ads and save to a JSON Lines file (one JSON object per line).
        This format is better for large datasets and streaming processing.

        Args:
            filter_config: Optional client-side filter configuration
            dedup_tracker: Optional deduplication tracker to skip already-seen ads

        Returns:
            Number of ads collected
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with open(path, "w", encoding="utf-8") as f:
            for ad in self.search(
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
                f.write(json.dumps(ad.to_dict(include_raw=include_raw), ensure_ascii=False))
                f.write("\n")
                count += 1

        logger.info(f"Saved {count} ads to {output_path}")
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

    def close(self) -> None:
        """Close the collector and cleanup resources."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
