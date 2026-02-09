"""Tests for MetaAdsCollector.stream() lifecycle event streaming."""

from unittest.mock import MagicMock

from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.events import (
    AD_COLLECTED,
    COLLECTION_FINISHED,
    COLLECTION_STARTED,
    PAGE_FETCHED,
    EventEmitter,
)
from meta_ads_collector.models import Ad

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector():
    """Create a MetaAdsCollector with a mocked client."""
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    collector.rate_limit_delay = 0
    collector.jitter = 0
    collector.event_emitter = EventEmitter()
    collector.stats = {
        "requests_made": 0, "ads_collected": 0, "pages_fetched": 0,
        "errors": 0, "start_time": None, "end_time": None,
    }
    return collector


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStream:
    def test_stream_returns_generator(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}}, None,
        )
        gen = collector.stream(query="test", country="US")
        assert hasattr(gen, "__iter__")
        assert hasattr(gen, "__next__")

    def test_stream_yields_tuples(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        for event_type, data in events:
            assert isinstance(event_type, str)
            assert isinstance(data, dict)

    def test_stream_includes_collection_started(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]
        assert types[0] == COLLECTION_STARTED

    def test_stream_includes_collection_finished(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]
        assert types[-1] == COLLECTION_FINISHED

    def test_stream_includes_page_fetched(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]
        assert PAGE_FETCHED in types

    def test_stream_includes_ad_collected(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]
        assert AD_COLLECTED in types

    def test_stream_ad_collected_carries_ad_instance(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        ad_events = [(et, d) for et, d in events if et == AD_COLLECTED]
        assert len(ad_events) == 1
        assert isinstance(ad_events[0][1]["ad"], Ad)

    def test_stream_event_ordering(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {
                "ads": [
                    {"ad_archive_id": "ad-1"},
                    {"ad_archive_id": "ad-2"},
                ],
                "page_info": {},
            },
            None,
        )
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]

        # Started should be first, finished should be last
        assert types[0] == COLLECTION_STARTED
        assert types[-1] == COLLECTION_FINISHED

        # page_fetched should come before ad_collected
        pf_idx = types.index(PAGE_FETCHED)
        ac_idx = types.index(AD_COLLECTED)
        assert pf_idx < ac_idx

    def test_stream_collection_finished_has_correct_total(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {
                "ads": [
                    {"ad_archive_id": "ad-1"},
                    {"ad_archive_id": "ad-2"},
                    {"ad_archive_id": "ad-3"},
                ],
                "page_info": {},
            },
            None,
        )
        events = list(collector.stream(query="test", country="US"))
        finished_events = [(et, d) for et, d in events if et == COLLECTION_FINISHED]
        assert len(finished_events) == 1
        assert finished_events[0][1]["total_ads"] == 3

    def test_stream_with_max_results(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {
                "ads": [
                    {"ad_archive_id": f"ad-{i}"} for i in range(10)
                ],
                "page_info": {},
            },
            None,
        )
        events = list(collector.stream(query="test", country="US", max_results=5))
        ad_events = [(et, d) for et, d in events if et == AD_COLLECTED]
        assert len(ad_events) == 5

    def test_stream_cleans_up_listeners(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}}, None,
        )
        # Ensure no listeners before
        assert not collector.event_emitter.has_listeners(AD_COLLECTED)

        list(collector.stream(query="test", country="US"))

        # Ensure listeners are removed after
        assert not collector.event_emitter.has_listeners(AD_COLLECTED)

    def test_stream_with_pagination(self):
        collector = _make_collector()
        collector.client.search_ads.side_effect = [
            (
                {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}},
                "cursor-1",
            ),
            (
                {"ads": [{"ad_archive_id": "ad-2"}], "page_info": {}},
                None,
            ),
        ]
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]

        # Should have 2 page_fetched events
        pf_count = types.count(PAGE_FETCHED)
        assert pf_count == 2

        # Should have 2 ad_collected events
        ac_count = types.count(AD_COLLECTED)
        assert ac_count == 2

    def test_stream_empty_results(self):
        collector = _make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}}, None,
        )
        events = list(collector.stream(query="test", country="US"))
        types = [et for et, _ in events]

        assert COLLECTION_STARTED in types
        assert COLLECTION_FINISHED in types
        assert AD_COLLECTED not in types
