"""
Meta Ads Library Collector

High-level interface for collecting ads from the Meta Ad Library.
Handles pagination, rate limiting, and data storage.
"""

import json
import csv
import logging
import time
import random
from pathlib import Path
from typing import Iterator, List, Optional, Dict, Any, Callable
from datetime import datetime

from .client import MetaAdsClient
from .constants import (
    AD_TYPE_ALL,
    AD_TYPE_POLITICAL,
    AD_TYPE_HOUSING,
    AD_TYPE_EMPLOYMENT,
    AD_TYPE_CREDIT,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    STATUS_ALL,
    SEARCH_KEYWORD,
    SEARCH_EXACT,
    SEARCH_UNORDERED,
    SEARCH_PAGE,
    SORT_RELEVANCY,
    SORT_IMPRESSIONS,
    VALID_AD_TYPES,
    VALID_STATUSES,
    VALID_SEARCH_TYPES,
    VALID_SORT_MODES,
    DEFAULT_RATE_LIMIT_DELAY,
    DEFAULT_JITTER,
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PAGE_SIZE,
    RATE_LIMIT_BACKOFF_BASE,
    RATE_LIMIT_JITTER_RANGE,
)
from .exceptions import InvalidParameterError
from .models import Ad, SearchResult

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
        proxy: Optional[str] = None,
        rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
        jitter: float = DEFAULT_JITTER,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        """
        Initialize the collector.

        Args:
            proxy: Proxy string in format "host:port:username:password"
            rate_limit_delay: Base delay between requests (seconds)
            jitter: Random jitter to add to delay (seconds)
            timeout: Request timeout (seconds)
            max_retries: Maximum retry attempts per request
        """
        self.client = MetaAdsClient(
            proxy=proxy,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.rate_limit_delay = rate_limit_delay
        self.jitter = jitter

        # Collection statistics
        self.stats = {
            "requests_made": 0,
            "ads_collected": 0,
            "pages_fetched": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

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
        page_ids: Optional[List[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        progress_callback: Optional[Callable[[int, int], None]] = None,
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

        Yields:
            Ad objects as they are collected
        """
        import uuid

        country = country.upper()
        self._validate_params(ad_type, status, search_type, sort_by, country)

        self.stats["start_time"] = datetime.utcnow()
        cursor = None
        collected = 0

        # Generate consistent session_id and collation_token for the entire search
        search_session_id = str(uuid.uuid4())
        search_collation_token = str(uuid.uuid4())

        logger.info(f"Starting search: query='{query}', country={country}, ad_type={ad_type}")

        try:
            while True:
                # Check if we've hit our limit
                if max_results and collected >= max_results:
                    logger.info(f"Reached max_results limit: {max_results}")
                    break

                # Make the API request with retry logic
                retry_count = 0
                max_retries = 3
                response = None

                while retry_count < max_retries:
                    try:
                        self.stats["requests_made"] += 1
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

                        # Check for rate limiting
                        if response.get("rate_limited"):
                            retry_count += 1
                            if retry_count < max_retries:
                                wait_time = 5 * retry_count + random.uniform(1, 3)
                                logger.warning(f"Rate limited, waiting {wait_time:.1f}s before retry {retry_count}/{max_retries}")
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error("Max retries exceeded due to rate limiting")
                                self.stats["errors"] += 1
                                return

                        # Check for session expiry - client handles refresh,
                        # we just need to retry the request
                        if response.get("session_expired"):
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(f"Session expired, retrying ({retry_count}/{max_retries})...")
                                time.sleep(2)
                                continue
                            else:
                                logger.error("Max retries exceeded due to session expiry")
                                self.stats["errors"] += 1
                                return

                        self.stats["pages_fetched"] += 1
                        break  # Success, exit retry loop

                    except Exception as e:
                        logger.error(f"Search request failed: {e}")
                        self.stats["errors"] += 1
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise
                        time.sleep(3 * retry_count)

                if response is None:
                    logger.error("No response received after retries")
                    break

                # Process results
                ads_data = response.get("ads", [])

                if not ads_data:
                    logger.info("No more results returned")
                    break

                for ad_data in ads_data:
                    if max_results and collected >= max_results:
                        break

                    try:
                        ad = Ad.from_graphql_response(ad_data)
                        collected += 1
                        self.stats["ads_collected"] += 1

                        if progress_callback:
                            progress_callback(collected, max_results or -1)

                        yield ad

                    except Exception as e:
                        logger.warning(f"Failed to parse ad: {e}")
                        self.stats["errors"] += 1
                        continue

                # Check for next page
                if not next_cursor:
                    logger.info("No more pages available")
                    break

                cursor = next_cursor
                logger.debug(f"Fetching next page (collected: {collected})")

                # Rate limiting
                self._delay()

        finally:
            self.stats["end_time"] = datetime.utcnow()
            logger.info(f"Search completed: {collected} ads collected")

    def collect(
        self,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[List[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
    ) -> List[Ad]:
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
        ))

    def collect_to_json(
        self,
        output_path: str,
        query: str = "",
        country: str = "US",
        ad_type: str = AD_TYPE_ALL,
        status: str = STATUS_ACTIVE,
        search_type: str = SEARCH_KEYWORD,
        page_ids: Optional[List[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
        include_raw: bool = False,
        indent: int = 2,
    ) -> int:
        """
        Collect ads and save to a JSON file.

        Args:
            output_path: Path to output JSON file
            include_raw: Include raw API response data
            indent: JSON indentation
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
        ):
            ads.append(ad.to_dict(include_raw=include_raw))

        output = {
            "metadata": {
                "query": query,
                "country": country,
                "ad_type": ad_type,
                "status": status,
                "collected_at": datetime.utcnow().isoformat(),
                "total_count": len(ads),
                "stats": self.stats.copy(),
            },
            "ads": ads,
        }

        # Convert datetime objects in stats
        if output["metadata"]["stats"]["start_time"]:
            output["metadata"]["stats"]["start_time"] = output["metadata"]["stats"]["start_time"].isoformat()
        if output["metadata"]["stats"]["end_time"]:
            output["metadata"]["stats"]["end_time"] = output["metadata"]["stats"]["end_time"].isoformat()

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
        page_ids: Optional[List[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
    ) -> int:
        """
        Collect ads and save to a CSV file.

        Args:
            output_path: Path to output CSV file
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
        page_ids: Optional[List[str]] = None,
        sort_by: Optional[str] = SORT_IMPRESSIONS,
        max_results: Optional[int] = None,
        page_size: int = 10,
        include_raw: bool = False,
    ) -> int:
        """
        Collect ads and save to a JSON Lines file (one JSON object per line).
        This format is better for large datasets and streaming processing.

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
            ):
                f.write(json.dumps(ad.to_dict(include_raw=include_raw), ensure_ascii=False))
                f.write("\n")
                count += 1

        logger.info(f"Saved {count} ads to {output_path}")
        return count

    def get_stats(self) -> Dict[str, Any]:
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
