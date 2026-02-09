"""Tests for meta_ads_collector.events (EventEmitter and lifecycle events)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from meta_ads_collector.events import (
    AD_COLLECTED,
    ALL_EVENT_TYPES,
    COLLECTION_FINISHED,
    COLLECTION_STARTED,
    ERROR_OCCURRED,
    PAGE_FETCHED,
    RATE_LIMITED,
    SESSION_REFRESHED,
    Event,
    EventEmitter,
)

# ---------------------------------------------------------------------------
# Event data model
# ---------------------------------------------------------------------------


class TestEvent:
    def test_event_has_required_fields(self):
        event = Event(event_type="test", data={"key": "value"})
        assert event.event_type == "test"
        assert event.data == {"key": "value"}
        assert isinstance(event.timestamp, datetime)

    def test_event_default_data(self):
        event = Event(event_type="test")
        assert event.data == {}

    def test_event_timestamp_is_utc(self):
        event = Event(event_type="test")
        assert event.timestamp.tzinfo is not None
        assert event.timestamp.tzinfo == timezone.utc

    def test_event_timestamp_is_recent(self):
        before = datetime.now(timezone.utc)
        event = Event(event_type="test")
        after = datetime.now(timezone.utc)
        assert before <= event.timestamp <= after


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------


class TestEventTypes:
    def test_collection_started(self):
        assert COLLECTION_STARTED == "collection_started"

    def test_ad_collected(self):
        assert AD_COLLECTED == "ad_collected"

    def test_page_fetched(self):
        assert PAGE_FETCHED == "page_fetched"

    def test_error_occurred(self):
        assert ERROR_OCCURRED == "error_occurred"

    def test_rate_limited(self):
        assert RATE_LIMITED == "rate_limited"

    def test_session_refreshed(self):
        assert SESSION_REFRESHED == "session_refreshed"

    def test_collection_finished(self):
        assert COLLECTION_FINISHED == "collection_finished"

    def test_all_event_types_contains_all(self):
        assert frozenset({
            "collection_started",
            "ad_collected",
            "page_fetched",
            "error_occurred",
            "rate_limited",
            "session_refreshed",
            "collection_finished",
        }) == ALL_EVENT_TYPES


# ---------------------------------------------------------------------------
# EventEmitter: registration and firing
# ---------------------------------------------------------------------------


class TestEventEmitterOnAndEmit:
    def test_register_and_fire(self):
        emitter = EventEmitter()
        received = []
        emitter.on("test", lambda e: received.append(e))
        emitter.emit("test", {"x": 1})
        assert len(received) == 1
        assert received[0].event_type == "test"
        assert received[0].data == {"x": 1}

    def test_emit_returns_event(self):
        emitter = EventEmitter()
        event = emitter.emit("test", {"y": 2})
        assert isinstance(event, Event)
        assert event.event_type == "test"
        assert event.data == {"y": 2}

    def test_emit_with_no_data(self):
        emitter = EventEmitter()
        event = emitter.emit("test")
        assert event.data == {}

    def test_emit_with_no_listeners(self):
        emitter = EventEmitter()
        event = emitter.emit("test", {"z": 3})
        assert event.event_type == "test"

    def test_multiple_listeners_all_fire(self):
        emitter = EventEmitter()
        results = []
        emitter.on("test", lambda e: results.append("a"))
        emitter.on("test", lambda e: results.append("b"))
        emitter.on("test", lambda e: results.append("c"))
        emitter.emit("test")
        assert results == ["a", "b", "c"]

    def test_listeners_for_different_events(self):
        emitter = EventEmitter()
        results = []
        emitter.on("alpha", lambda e: results.append("alpha"))
        emitter.on("beta", lambda e: results.append("beta"))
        emitter.emit("alpha")
        assert results == ["alpha"]

    def test_has_listeners(self):
        emitter = EventEmitter()
        assert emitter.has_listeners("test") is False
        emitter.on("test", lambda e: None)
        assert emitter.has_listeners("test") is True

    def test_listener_count(self):
        emitter = EventEmitter()
        assert emitter.listener_count("test") == 0
        emitter.on("test", lambda e: None)
        emitter.on("test", lambda e: None)
        assert emitter.listener_count("test") == 2


# ---------------------------------------------------------------------------
# EventEmitter: removal
# ---------------------------------------------------------------------------


class TestEventEmitterOff:
    def test_remove_callback(self):
        emitter = EventEmitter()
        results = []
        cb = lambda e: results.append("fired")  # noqa: E731
        emitter.on("test", cb)
        emitter.off("test", cb)
        emitter.emit("test")
        assert results == []

    def test_remove_only_target_callback(self):
        emitter = EventEmitter()
        results = []
        cb_keep = lambda e: results.append("keep")  # noqa: E731
        cb_remove = lambda e: results.append("remove")  # noqa: E731
        emitter.on("test", cb_keep)
        emitter.on("test", cb_remove)
        emitter.off("test", cb_remove)
        emitter.emit("test")
        assert results == ["keep"]

    def test_remove_nonexistent_is_noop(self):
        emitter = EventEmitter()
        emitter.off("test", lambda e: None)  # Should not raise

    def test_remove_from_nonexistent_event(self):
        emitter = EventEmitter()
        cb = lambda e: None  # noqa: E731
        emitter.off("nonexistent", cb)  # Should not raise


# ---------------------------------------------------------------------------
# EventEmitter: exception isolation (CRITICAL)
# ---------------------------------------------------------------------------


class TestEventEmitterExceptionIsolation:
    def test_callback_exception_does_not_propagate(self):
        emitter = EventEmitter()
        emitter.on("test", lambda e: 1 / 0)  # ZeroDivisionError
        # This must NOT raise
        event = emitter.emit("test")
        assert event.event_type == "test"

    def test_other_callbacks_still_fire_after_exception(self):
        emitter = EventEmitter()
        results = []
        emitter.on("test", lambda e: results.append("before"))
        emitter.on("test", lambda e: 1 / 0)
        emitter.on("test", lambda e: results.append("after"))
        emitter.emit("test")
        assert results == ["before", "after"]

    def test_multiple_failing_callbacks_all_caught(self):
        emitter = EventEmitter()
        results = []
        emitter.on("test", lambda e: 1 / 0)
        emitter.on("test", lambda e: results.append("ok"))
        emitter.on("test", lambda e: [][0])
        emitter.on("test", lambda e: results.append("ok2"))
        emitter.emit("test")
        assert results == ["ok", "ok2"]

    def test_exception_in_callback_is_logged(self, caplog):
        import logging
        emitter = EventEmitter()
        emitter.on("test", lambda e: 1 / 0)
        with caplog.at_level(logging.WARNING, logger="meta_ads_collector.events"):
            emitter.emit("test")
        assert any("raised an exception" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Convenience callbacks in collector constructor
# ---------------------------------------------------------------------------


class TestCollectorCallbacksParameter:
    def test_callbacks_dict_registers_listeners(self):
        from meta_ads_collector.collector import MetaAdsCollector

        received = []
        callbacks = {
            AD_COLLECTED: lambda e: received.append(e),
            ERROR_OCCURRED: lambda e: received.append(e),
        }

        collector = MetaAdsCollector.__new__(MetaAdsCollector)
        collector.client = MagicMock()
        collector.rate_limit_delay = 0
        collector.jitter = 0
        collector.event_emitter = EventEmitter()
        for event_type, cb in callbacks.items():
            collector.event_emitter.on(event_type, cb)
        collector.stats = {
            "requests_made": 0, "ads_collected": 0, "pages_fetched": 0,
            "errors": 0, "start_time": None, "end_time": None,
        }

        assert collector.event_emitter.has_listeners(AD_COLLECTED)
        assert collector.event_emitter.has_listeners(ERROR_OCCURRED)
        assert not collector.event_emitter.has_listeners(PAGE_FETCHED)


# ---------------------------------------------------------------------------
# Integration: events emitted during search()
# ---------------------------------------------------------------------------


class TestSearchEventEmission:
    """Verify events are emitted at the correct lifecycle points of search()."""

    def _make_collector(self):
        from meta_ads_collector.collector import MetaAdsCollector
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

    def test_collection_started_emitted(self):
        collector = self._make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}}, None,
        )

        events = []
        collector.event_emitter.on(COLLECTION_STARTED, lambda e: events.append(e))
        list(collector.search(query="test", country="US"))

        assert len(events) == 1
        assert events[0].data["query"] == "test"
        assert events[0].data["country"] == "US"

    def test_collection_finished_emitted(self):
        collector = self._make_collector()
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}}, None,
        )

        events = []
        collector.event_emitter.on(COLLECTION_FINISHED, lambda e: events.append(e))
        list(collector.search(query="test", country="US"))

        assert len(events) == 1
        assert events[0].data["total_ads"] == 0
        # A page was fetched (the request succeeded) even though it had no ads
        assert events[0].data["total_pages"] == 1
        assert "duration_seconds" in events[0].data

    def test_ad_collected_emitted_for_each_ad(self):
        collector = self._make_collector()
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

        events = []
        collector.event_emitter.on(AD_COLLECTED, lambda e: events.append(e))
        ads = list(collector.search(query="test", country="US"))

        assert len(ads) == 3
        assert len(events) == 3
        assert events[0].data["ad"].id == "ad-1"
        assert events[1].data["ad"].id == "ad-2"
        assert events[2].data["ad"].id == "ad-3"

    def test_page_fetched_emitted(self):
        collector = self._make_collector()
        collector.client.search_ads.return_value = (
            {
                "ads": [{"ad_archive_id": "ad-1"}],
                "page_info": {},
            },
            None,
        )

        events = []
        collector.event_emitter.on(PAGE_FETCHED, lambda e: events.append(e))
        list(collector.search(query="test", country="US"))

        assert len(events) == 1
        assert events[0].data["page_number"] == 1
        assert events[0].data["ads_on_page"] == 1
        assert events[0].data["has_next_page"] is False

    def test_page_fetched_has_next_page_true(self):
        collector = self._make_collector()
        # First call returns results with cursor, second returns empty
        collector.client.search_ads.side_effect = [
            (
                {"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}},
                "cursor-123",
            ),
            (
                {"ads": [], "page_info": {}},
                None,
            ),
        ]

        events = []
        collector.event_emitter.on(PAGE_FETCHED, lambda e: events.append(e))
        list(collector.search(query="test", country="US"))

        assert len(events) == 1  # Second page is empty, no page_fetched
        assert events[0].data["has_next_page"] is True

    def test_error_occurred_on_ad_parse_failure(self):
        collector = self._make_collector()
        # Return invalid ad data that will cause parsing to fail
        collector.client.search_ads.return_value = (
            {
                "ads": [
                    {"ad_archive_id": "good-ad"},
                    None,  # This will cause from_graphql_response to fail
                ],
                "page_info": {},
            },
            None,
        )

        events = []
        collector.event_emitter.on(ERROR_OCCURRED, lambda e: events.append(e))
        ads = list(collector.search(query="test", country="US"))

        assert len(ads) == 1  # Good ad is still collected
        assert len(events) == 1
        assert "Failed to parse ad" in events[0].data["context"]

    def test_rate_limited_event_emitted(self):
        collector = self._make_collector()
        # First call returns rate_limited, second returns data
        collector.client.search_ads.side_effect = [
            ({"ads": [], "page_info": {}, "rate_limited": True}, None),
            ({"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None),
        ]

        events = []
        collector.event_emitter.on(RATE_LIMITED, lambda e: events.append(e))
        # Need to force max_results to avoid infinite loop with side_effect
        list(collector.search(query="test", country="US", max_results=1))

        assert len(events) == 1
        assert "wait_seconds" in events[0].data
        assert events[0].data["retry_count"] == 1

    def test_session_refreshed_event_emitted(self):
        collector = self._make_collector()
        collector.client.search_ads.side_effect = [
            ({"ads": [], "page_info": {}, "session_expired": True}, None),
            ({"ads": [{"ad_archive_id": "ad-1"}], "page_info": {}}, None),
        ]

        events = []
        collector.event_emitter.on(SESSION_REFRESHED, lambda e: events.append(e))
        list(collector.search(query="test", country="US", max_results=1))

        assert len(events) == 1
        assert events[0].data["reason"] == "session_expired"

    def test_collection_finished_has_correct_totals(self):
        collector = self._make_collector()
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

        events = []
        collector.event_emitter.on(COLLECTION_FINISHED, lambda e: events.append(e))
        list(collector.search(query="test", country="US"))

        assert events[0].data["total_ads"] == 2
        assert events[0].data["total_pages"] == 1
        assert events[0].data["duration_seconds"] >= 0

    def test_collection_finished_emitted_even_on_exception(self):
        collector = self._make_collector()
        collector.client.search_ads.side_effect = RuntimeError("boom")

        events = []
        collector.event_emitter.on(COLLECTION_FINISHED, lambda e: events.append(e))

        with pytest.raises(RuntimeError, match="boom"):
            list(collector.search(query="test", country="US"))

        # collection_finished should still be emitted via finally block
        assert len(events) == 1
        assert events[0].data["total_ads"] == 0

    def test_buggy_callback_does_not_crash_search(self):
        """CRITICAL: a failing callback must not stop the collection."""
        collector = self._make_collector()
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

        def bad_callback(event):
            raise RuntimeError("I am a buggy callback!")

        collector.event_emitter.on(AD_COLLECTED, bad_callback)
        # This must not raise
        ads = list(collector.search(query="test", country="US"))
        assert len(ads) == 2

    def test_event_ordering(self):
        """Events should fire in order: started, page_fetched, ad_collected..., finished."""
        collector = self._make_collector()
        collector.client.search_ads.return_value = (
            {
                "ads": [{"ad_archive_id": "ad-1"}],
                "page_info": {},
            },
            None,
        )

        event_types = []
        for et in ALL_EVENT_TYPES:
            collector.event_emitter.on(et, lambda e, _et=et: event_types.append(_et))

        list(collector.search(query="test", country="US"))

        assert event_types[0] == COLLECTION_STARTED
        assert event_types[-1] == COLLECTION_FINISHED
        # page_fetched should come before ad_collected
        pf_idx = event_types.index(PAGE_FETCHED)
        ac_idx = event_types.index(AD_COLLECTED)
        assert pf_idx < ac_idx
