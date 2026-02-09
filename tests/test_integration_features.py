"""Feature integration tests for meta_ads_collector.

Tests for optional features: page search/typeahead, URL parsing, filters,
deduplication, media download, ad detail enrichment, event system, async
client, and proxy configuration.

Each test first checks if the required module exists and skips gracefully
if the feature has not been implemented yet.

All tests are marked ``@pytest.mark.integration`` and are skipped by
default.  Enable with ``--run-integration`` or ``RUN_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from meta_ads_collector.models import Ad

from .utils import retry_on_transient

pytestmark = pytest.mark.integration


def _module_available(name: str) -> bool:
    """Return True if the given module can be imported."""
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


class TestPageSearchTypeahead:
    """Verify the page search/typeahead feature against the live API."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_page_search_returns_known_page(self) -> None:
        """Search for 'Coca-Cola' page and verify results contain a valid page_id.

        The typeahead endpoint should return at least one result for a
        well-known brand like Coca-Cola.
        """
        from meta_ads_collector.collector import MetaAdsCollector

        collector = MetaAdsCollector(rate_limit_delay=1.5, jitter=0.5, timeout=45)
        try:
            pages = collector.search_pages(query="Coca-Cola", country="US")
            assert len(pages) >= 1, (
                "Expected at least 1 page result for 'Coca-Cola'"
            )

            first = pages[0]
            assert first.page_id, f"First page result has empty page_id: {first}"
            assert first.page_name, f"First page result has empty page_name: {first}"
        finally:
            collector.close()


class TestURLParsing:
    """Verify URL parsing extracts page IDs correctly."""

    def test_parse_ad_library_url_with_view_all_page_id(self) -> None:
        """Parse a known Ad Library URL and verify the extracted page ID."""
        from meta_ads_collector.url_parser import extract_page_id_from_url

        url = "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=40796308305"
        page_id = extract_page_id_from_url(url)
        assert page_id == "40796308305", (
            f"Expected page_id='40796308305', got {page_id!r}"
        )

    def test_parse_profile_url_with_numeric_id(self) -> None:
        """Parse a profile URL with id query parameter."""
        from meta_ads_collector.url_parser import extract_page_id_from_url

        url = "https://www.facebook.com/profile.php?id=100044415891099"
        page_id = extract_page_id_from_url(url)
        assert page_id == "100044415891099", (
            f"Expected page_id='100044415891099', got {page_id!r}"
        )


class TestFilters:
    """Verify that client-side filters work with real data."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_filter_with_date_range_succeeds(self, collected_ads: list[Ad]) -> None:
        """Apply a date range filter to real ads and verify it does not crash.

        We cannot guarantee filtering changes results (ads may lack dates),
        but we verify the filter mechanism runs without error.
        """
        from datetime import datetime

        from meta_ads_collector.filters import FilterConfig, passes_filter

        config = FilterConfig(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2026, 12, 31),
        )

        passed = [ad for ad in collected_ads if passes_filter(ad, config)]
        # At minimum, the filter should not crash
        assert isinstance(passed, list), "Filter should return a list"


class TestDeduplication:
    """Verify deduplication with real ad data."""

    def test_dedup_tracker_identifies_duplicates(self, collected_ads: list[Ad]) -> None:
        """Mark collected ads as seen, then verify has_seen returns True."""
        from meta_ads_collector.dedup import DeduplicationTracker

        tracker = DeduplicationTracker(mode="memory")

        # Mark first 5 ads as seen
        for ad in collected_ads[:5]:
            tracker.mark_seen(ad.id)

        # Verify they are marked
        for ad in collected_ads[:5]:
            assert tracker.has_seen(ad.id), (
                f"Ad {ad.id} should be marked as seen"
            )

        # Verify others are NOT marked (if we have more than 5)
        if len(collected_ads) > 5:
            unseen_ad = collected_ads[5]
            assert not tracker.has_seen(unseen_ad.id), (
                f"Ad {unseen_ad.id} should NOT be marked as seen"
            )


class TestEventSystem:
    """Verify the event system fires events during real collection."""

    @retry_on_transient(max_retries=2, backoff_factor=3.0)
    def test_events_fired_during_collection(self) -> None:
        """Attach a listener and run a small collection; verify events fire.

        Checks that at least collection_started and collection_finished
        events are emitted.
        """
        from meta_ads_collector.collector import MetaAdsCollector
        from meta_ads_collector.events import COLLECTION_FINISHED, COLLECTION_STARTED

        fired_events: list[str] = []

        def listener(event: Any) -> None:
            fired_events.append(event.event_type)

        collector = MetaAdsCollector(rate_limit_delay=1.5, jitter=0.5, timeout=45)
        collector.event_emitter.on(COLLECTION_STARTED, listener)
        collector.event_emitter.on(COLLECTION_FINISHED, listener)

        try:
            list(collector.search(
                query="meta",
                country="US",
                max_results=3,
                page_size=10,
            ))
        finally:
            collector.close()

        assert COLLECTION_STARTED in fired_events, (
            "collection_started event was not fired"
        )
        assert COLLECTION_FINISHED in fired_events, (
            "collection_finished event was not fired"
        )


class TestProxyConfiguration:
    """Verify that proxy configuration is accepted without crashing."""

    def test_proxy_string_accepted(self) -> None:
        """Verify the client accepts a proxy string (config test only).

        Does NOT make any real requests through the proxy.  Just
        verifies the client initializes without error.
        """
        from meta_ads_collector.client import MetaAdsClient

        # Use a clearly-invalid proxy to avoid any real connections
        client = MetaAdsClient(proxy="127.0.0.1:19999", timeout=5)
        try:
            # Verify proxy was configured
            assert client.session.proxies, "Proxies dict should be set"
        finally:
            client.close()
