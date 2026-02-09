"""Core pipeline integration tests for meta_ads_collector.

These tests hit the real Meta Ad Library servers to verify that the
full pipeline -- client initialization, GraphQL requests, response
parsing, pagination, and stats tracking -- works end-to-end.

All tests are marked ``@pytest.mark.integration`` and are skipped by
default.  Enable with ``--run-integration`` or ``RUN_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.models import Ad

from .utils import retry_on_transient

pytestmark = pytest.mark.integration


class TestClientInitialization:
    """Verify that a fresh MetaAdsClient can initialize against the live API."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_client_initializes_and_extracts_lsd_token(self) -> None:
        """Create a client, initialize it, and verify the LSD token was extracted.

        The LSD token is mandatory for all subsequent GraphQL requests.
        """
        client = MetaAdsClient(timeout=45, max_retries=3)
        try:
            result = client.initialize()
            assert result is True, "Client initialization returned False"
            assert client._initialized is True, "Client._initialized is not True after init"

            lsd = client._tokens.get("lsd", "")
            assert lsd, "LSD token is empty after initialization"
            assert len(lsd) >= 5, f"LSD token too short: {lsd!r}"
        finally:
            client.close()


class TestBasicSearch:
    """Verify that searching for a well-known brand returns valid ads."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_basic_search_returns_valid_ads(self, collected_ads: list[Ad]) -> None:
        """Search for 'coca cola' and verify each ad has core fields populated.

        Uses the session-scoped collected_ads fixture to avoid extra API calls.
        """
        assert len(collected_ads) >= 1, (
            f"Expected at least 1 ad from 'coca cola' search, got {len(collected_ads)}"
        )

        for ad in collected_ads:
            assert isinstance(ad, Ad), f"Expected Ad instance, got {type(ad)}"
            assert ad.id, f"Ad has empty id: {ad!r}"
            # page info should be present
            assert ad.page is not None, f"Ad {ad.id} has no page info"
            assert ad.page.id, f"Ad {ad.id} page has empty id"
            assert ad.page.name, f"Ad {ad.id} page has empty name"


class TestPagination:
    """Verify that pagination returns multiple pages without duplicates."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_pagination_returns_no_duplicate_ad_ids(self) -> None:
        """Search for 30 ads (requires pagination) and verify no duplicates.

        Meta's API returns ~10 ads per page by default, so requesting 30
        forces at least 3 pagination requests.
        """
        collector = MetaAdsCollector(rate_limit_delay=1.5, jitter=0.5, timeout=45)
        try:
            ads: list[Ad] = []
            for ad in collector.search(
                query="nike",
                country="US",
                max_results=30,
                page_size=10,
            ):
                ads.append(ad)

            assert len(ads) >= 10, (
                f"Expected at least 10 ads from 'nike' search with max_results=30, "
                f"got {len(ads)}"
            )

            # Check for duplicates
            ad_ids = [ad.id for ad in ads]
            unique_ids = set(ad_ids)
            assert len(ad_ids) == len(unique_ids), (
                f"Found {len(ad_ids) - len(unique_ids)} duplicate ad IDs in results. "
                f"Total: {len(ad_ids)}, Unique: {len(unique_ids)}"
            )
        finally:
            collector.close()


class TestCountryFiltering:
    """Verify that country-specific searches succeed."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_country_filtering_returns_results(self) -> None:
        """Search with country='GB' and verify we get results back.

        This confirms the country parameter is correctly passed to the API
        and does not cause errors.
        """
        collector = MetaAdsCollector(rate_limit_delay=1.5, jitter=0.5, timeout=45)
        try:
            ads: list[Ad] = []
            for ad in collector.search(
                query="nike",
                country="GB",
                max_results=5,
                page_size=10,
            ):
                ads.append(ad)

            assert len(ads) >= 1, (
                "Expected at least 1 ad from 'nike' search with country=GB"
            )
        finally:
            collector.close()


class TestMaxResultsEnforcement:
    """Verify that max_results is respected exactly."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_max_results_returns_exact_count(self) -> None:
        """Request exactly 7 ads and verify exactly 7 are returned.

        Uses a broad query ('meta') to ensure there are enough results.
        """
        collector = MetaAdsCollector(rate_limit_delay=1.5, jitter=0.5, timeout=45)
        try:
            ads: list[Ad] = list(collector.search(
                query="meta",
                country="US",
                max_results=7,
                page_size=10,
            ))

            assert len(ads) == 7, (
                f"Expected exactly 7 ads but got {len(ads)}"
            )
        finally:
            collector.close()


class TestStatsAccuracy:
    """Verify that collection stats match the actual results."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_stats_match_collected_count(self) -> None:
        """Collect ads and verify stats reflect the actual counts.

        Checks that requests_made > 0, pages_fetched > 0, and
        ads_collected matches the number of yielded ads.
        """
        collector = MetaAdsCollector(rate_limit_delay=1.5, jitter=0.5, timeout=45)
        try:
            ads: list[Ad] = list(collector.search(
                query="coca cola",
                country="US",
                max_results=5,
                page_size=10,
            ))

            stats = collector.get_stats()
            assert stats["requests_made"] > 0, "requests_made should be > 0"
            assert stats["pages_fetched"] > 0, "pages_fetched should be > 0"
            assert stats["ads_collected"] == len(ads), (
                f"stats.ads_collected ({stats['ads_collected']}) != "
                f"actual count ({len(ads)})"
            )
        finally:
            collector.close()
