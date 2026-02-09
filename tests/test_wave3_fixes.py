"""Tests for wave-3 fixes: S1 (datetime.utcnow removal) and N3 (setup_logging handler safety).

S1: Every ``datetime.utcnow()`` in the library has been replaced with
``datetime.now(timezone.utc)`` to eliminate DeprecationWarnings on
Python 3.12+.  Tests here verify that the returned datetimes are
timezone-aware (``tzinfo is not None``).

N3: ``setup_logging`` previously stripped **all** root-logger handlers,
which would break host-application logging.  The fix tags handlers with
a ``_meta_ads_collector`` attribute and only removes those.  Tests here
verify that external handlers survive repeated ``setup_logging`` calls
while library-owned handlers are correctly replaced.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from meta_ads_collector.logging_config import setup_logging
from meta_ads_collector.models import Ad

# =========================================================================
# S1 -- datetime.utcnow() replaced with datetime.now(timezone.utc)
# =========================================================================


class TestDatetimeTimezoneAwareness:
    """Verify that all datetime values produced by the library are tz-aware."""

    def test_ad_default_collected_at_is_timezone_aware(self) -> None:
        """Ad.collected_at default should be a timezone-aware UTC datetime."""
        ad = Ad(id="tz-test-1")
        assert ad.collected_at.tzinfo is not None, (
            "Ad.collected_at should be timezone-aware but tzinfo is None"
        )
        assert ad.collected_at.tzinfo == timezone.utc, (
            f"Expected UTC timezone, got {ad.collected_at.tzinfo}"
        )

    def test_ad_collected_at_is_recent(self) -> None:
        """Ad.collected_at default should be within a few seconds of now(UTC)."""
        before = datetime.now(timezone.utc)
        ad = Ad(id="tz-test-2")
        after = datetime.now(timezone.utc)
        assert before <= ad.collected_at <= after, (
            f"collected_at {ad.collected_at} is not between {before} and {after}"
        )

    def test_ad_from_graphql_response_collected_at_is_tz_aware(self) -> None:
        """Ad.from_graphql_response should produce a tz-aware collected_at."""
        data = {
            "ad_archive_id": "tz-gql-1",
            "page_id": "pg-1",
            "page_name": "Test",
        }
        ad = Ad.from_graphql_response(data)
        assert ad.collected_at.tzinfo is not None, (
            "collected_at from from_graphql_response should be timezone-aware"
        )

    def test_dedup_mark_seen_default_timestamp_is_tz_aware(self) -> None:
        """DeduplicationTracker.mark_seen default timestamp should be tz-aware."""
        from meta_ads_collector.dedup import DeduplicationTracker

        tracker = DeduplicationTracker(mode="memory")
        tracker.mark_seen("ad-123")
        # Access the internal timestamp to verify
        ts = tracker._timestamps.get("ad-123")
        assert ts is not None, "Timestamp should have been recorded"
        assert ts.tzinfo is not None, (
            "mark_seen default timestamp should be timezone-aware"
        )

    def test_dedup_update_collection_time_is_tz_aware(self) -> None:
        """DeduplicationTracker.update_collection_time should store tz-aware datetime."""
        from meta_ads_collector.dedup import DeduplicationTracker

        tracker = DeduplicationTracker(mode="memory")
        tracker.update_collection_time()
        last = tracker.get_last_collection_time()
        assert last is not None
        assert last.tzinfo is not None, (
            "update_collection_time should record a timezone-aware datetime"
        )


# =========================================================================
# N3 -- setup_logging preserves external handlers
# =========================================================================


class TestSetupLoggingHandlerSafety:
    """Verify that setup_logging only removes its own handlers."""

    def _cleanup(self) -> None:
        """Remove all handlers from root logger (test cleanup only)."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def test_preserves_external_handler(self) -> None:
        """Pre-existing handlers without _meta_ads_collector should survive."""
        self._cleanup()
        root = logging.getLogger()

        # Add an "external" handler (simulates host-application handler)
        external = logging.StreamHandler()
        external.setLevel(logging.DEBUG)
        root.addHandler(external)
        assert external in root.handlers

        # Call setup_logging -- it should NOT remove the external handler
        setup_logging(level="INFO")

        assert external in root.handlers, (
            "setup_logging removed an external handler that it did not create"
        )
        # Should have: external + 1 new console handler from setup_logging
        assert len(root.handlers) >= 2, (
            f"Expected at least 2 handlers, got {len(root.handlers)}"
        )

        self._cleanup()

    def test_replaces_own_handlers_on_repeated_calls(self) -> None:
        """Calling setup_logging twice should replace its own handlers, not duplicate."""
        self._cleanup()

        setup_logging(level="INFO")
        root = logging.getLogger()
        first_call_handlers = [
            h for h in root.handlers
            if getattr(h, "_meta_ads_collector", False)
        ]
        assert len(first_call_handlers) == 1, (
            f"Expected 1 library handler after first call, got {len(first_call_handlers)}"
        )

        # Second call should replace, not duplicate
        setup_logging(level="DEBUG")
        second_call_handlers = [
            h for h in root.handlers
            if getattr(h, "_meta_ads_collector", False)
        ]
        assert len(second_call_handlers) == 1, (
            f"Expected 1 library handler after second call, got {len(second_call_handlers)}"
        )

        self._cleanup()

    def test_external_handler_survives_multiple_setup_calls(self) -> None:
        """External handler should survive across multiple setup_logging calls."""
        self._cleanup()
        root = logging.getLogger()

        external = logging.StreamHandler()
        root.addHandler(external)

        setup_logging(level="INFO")
        setup_logging(level="DEBUG")
        setup_logging(level="WARNING")

        assert external in root.handlers, (
            "External handler was removed after multiple setup_logging calls"
        )

        self._cleanup()

    def test_file_handler_tagged_and_replaced(self, tmp_path: pytest.TempPathFactory) -> None:
        """File handlers should also be tagged and replaced on re-call."""
        self._cleanup()

        log_file = str(tmp_path / "test.log")  # type: ignore[operator]
        setup_logging(level="INFO", log_file=log_file)
        root = logging.getLogger()
        tagged = [
            h for h in root.handlers
            if getattr(h, "_meta_ads_collector", False)
        ]
        # Should have console + file = 2 tagged handlers
        assert len(tagged) == 2, (
            f"Expected 2 tagged handlers (console + file), got {len(tagged)}"
        )

        # Re-call without file -- old file handler should be removed
        setup_logging(level="DEBUG")
        tagged_after = [
            h for h in root.handlers
            if getattr(h, "_meta_ads_collector", False)
        ]
        assert len(tagged_after) == 1, (
            f"Expected 1 tagged handler after re-call without file, got {len(tagged_after)}"
        )

        self._cleanup()

    def test_handler_marker_attribute_exists(self) -> None:
        """Handlers created by setup_logging should have _meta_ads_collector=True."""
        self._cleanup()

        setup_logging(level="INFO")
        root = logging.getLogger()
        for handler in root.handlers:
            if getattr(handler, "_meta_ads_collector", False):
                assert handler._meta_ads_collector is True  # type: ignore[attr-defined]
                break
        else:
            pytest.fail("No handler with _meta_ads_collector attribute found")

        self._cleanup()
