"""Tests for meta_ads_collector.dedup."""

import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from meta_ads_collector.cli import parse_args
from meta_ads_collector.dedup import DeduplicationTracker
from meta_ads_collector.events import EventEmitter

# ---------------------------------------------------------------------------
# In-memory mode
# ---------------------------------------------------------------------------

class TestInMemoryTracker:
    def test_new_tracker_empty(self):
        tracker = DeduplicationTracker(mode="memory")
        assert tracker.count() == 0

    def test_mark_seen_then_has_seen(self):
        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("ad-1")
        assert tracker.has_seen("ad-1") is True

    def test_unknown_ad_not_seen(self):
        tracker = DeduplicationTracker(mode="memory")
        assert tracker.has_seen("ad-unknown") is False

    def test_count_increases(self):
        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("ad-1")
        tracker.mark_seen("ad-2")
        assert tracker.count() == 2

    def test_duplicate_mark_does_not_increase_count(self):
        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("ad-1")
        tracker.mark_seen("ad-1")
        assert tracker.count() == 1

    def test_clear_resets_everything(self):
        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("ad-1")
        tracker.update_collection_time()
        tracker.clear()
        assert tracker.has_seen("ad-1") is False
        assert tracker.count() == 0
        assert tracker.get_last_collection_time() is None

    def test_last_collection_time_initially_none(self):
        tracker = DeduplicationTracker(mode="memory")
        assert tracker.get_last_collection_time() is None

    def test_update_collection_time(self):
        tracker = DeduplicationTracker(mode="memory")
        tracker.update_collection_time()
        last = tracker.get_last_collection_time()
        assert last is not None
        assert isinstance(last, datetime)

    def test_save_and_load_noop_in_memory(self):
        """save() and load() are no-ops for in-memory mode."""
        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("ad-1")
        tracker.save()  # should not raise
        tracker.load()  # should not raise
        assert tracker.has_seen("ad-1") is True

    def test_context_manager(self):
        with DeduplicationTracker(mode="memory") as tracker:
            tracker.mark_seen("ad-1")
            assert tracker.has_seen("ad-1") is True

    def test_mark_seen_with_custom_timestamp(self):
        tracker = DeduplicationTracker(mode="memory")
        ts = datetime(2024, 1, 1, 12, 0, 0)
        tracker.mark_seen("ad-1", timestamp=ts)
        assert tracker.has_seen("ad-1") is True
        assert tracker._timestamps["ad-1"] == ts


# ---------------------------------------------------------------------------
# Persistent mode (SQLite)
# ---------------------------------------------------------------------------

class TestPersistentTracker:
    def test_create_and_use(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            tracker = DeduplicationTracker(mode="persistent", db_path=db_path)
            tracker.mark_seen("ad-1")
            tracker.save()
            assert tracker.has_seen("ad-1") is True
            assert tracker.count() == 1
            tracker.close()
        finally:
            os.unlink(db_path)

    def test_persistence_across_instances(self):
        """Data written by one tracker can be read by another."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Write with first tracker
            tracker1 = DeduplicationTracker(mode="persistent", db_path=db_path)
            tracker1.mark_seen("ad-1")
            tracker1.mark_seen("ad-2")
            tracker1.update_collection_time()
            tracker1.save()
            tracker1.close()

            # Read with second tracker
            tracker2 = DeduplicationTracker(mode="persistent", db_path=db_path)
            assert tracker2.has_seen("ad-1") is True
            assert tracker2.has_seen("ad-2") is True
            assert tracker2.has_seen("ad-3") is False
            assert tracker2.count() == 2
            assert tracker2.get_last_collection_time() is not None
            tracker2.close()
        finally:
            os.unlink(db_path)

    def test_last_collection_time_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            tracker1 = DeduplicationTracker(mode="persistent", db_path=db_path)
            assert tracker1.get_last_collection_time() is None
            tracker1.update_collection_time()
            tracker1.save()
            tracker1.close()

            tracker2 = DeduplicationTracker(mode="persistent", db_path=db_path)
            last = tracker2.get_last_collection_time()
            assert last is not None
            assert isinstance(last, datetime)
            tracker2.close()
        finally:
            os.unlink(db_path)

    def test_clear_persistent(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            tracker = DeduplicationTracker(mode="persistent", db_path=db_path)
            tracker.mark_seen("ad-1")
            tracker.update_collection_time()
            tracker.save()
            tracker.clear()
            assert tracker.has_seen("ad-1") is False
            assert tracker.count() == 0
            assert tracker.get_last_collection_time() is None
            tracker.close()
        finally:
            os.unlink(db_path)

    def test_context_manager_persistent(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            with DeduplicationTracker(mode="persistent", db_path=db_path) as tracker:
                tracker.mark_seen("ad-1")
            # After context manager exit, save() was called
            tracker2 = DeduplicationTracker(mode="persistent", db_path=db_path)
            assert tracker2.has_seen("ad-1") is True
            tracker2.close()
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestTrackerValidation:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            DeduplicationTracker(mode="invalid")

    def test_persistent_without_db_path_raises(self):
        with pytest.raises(ValueError, match="db_path is required"):
            DeduplicationTracker(mode="persistent")


# ---------------------------------------------------------------------------
# Integration: collector skips duplicates
# ---------------------------------------------------------------------------

class TestCollectorDedupIntegration:
    def test_skips_already_seen_ads(self):
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

        # Mock search_ads to return two ads: one already seen, one new
        collector.client.search_ads.return_value = (
            {
                "ads": [
                    {"ad_archive_id": "seen-1"},
                    {"ad_archive_id": "new-1"},
                ],
                "page_info": {},
            },
            None,
        )

        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("seen-1")

        ads = list(collector.search(
            query="test",
            country="US",
            dedup_tracker=tracker,
        ))

        assert len(ads) == 1
        assert ads[0].id == "new-1"
        # "new-1" should now be tracked
        assert tracker.has_seen("new-1") is True

    def test_marks_new_ads_as_seen(self):
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
        collector.client.search_ads.return_value = (
            {
                "ads": [
                    {"ad_archive_id": "ad-a"},
                    {"ad_archive_id": "ad-b"},
                ],
                "page_info": {},
            },
            None,
        )

        tracker = DeduplicationTracker(mode="memory")
        ads = list(collector.search(query="test", country="US", dedup_tracker=tracker))
        assert len(ads) == 2
        assert tracker.has_seen("ad-a") is True
        assert tracker.has_seen("ad-b") is True
        assert tracker.count() == 2

    def test_updates_collection_time_after_search(self):
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
        collector.client.search_ads.return_value = (
            {"ads": [], "page_info": {}},
            None,
        )

        tracker = DeduplicationTracker(mode="memory")
        assert tracker.get_last_collection_time() is None

        list(collector.search(query="test", country="US", dedup_tracker=tracker))
        assert tracker.get_last_collection_time() is not None


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------

class TestDedupCLIFlags:
    def test_deduplicate_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--deduplicate"
        ]):
            args = parse_args()
            assert args.deduplicate is True

    def test_dedup_short_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--dedup"
        ]):
            args = parse_args()
            assert args.deduplicate is True

    def test_state_file_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--state-file", "state.db"
        ]):
            args = parse_args()
            assert args.state_file == "state.db"

    def test_since_last_run_flag(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--since-last-run", "--state-file", "state.db"
        ]):
            args = parse_args()
            assert args.since_last_run is True

    def test_dedup_defaults(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.deduplicate is False
            assert args.state_file is None
            assert args.since_last_run is False
