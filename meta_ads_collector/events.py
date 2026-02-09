"""Event system for Meta Ads Collector.

Provides an event emitter with lifecycle event types for the collection
pipeline. Callbacks are invoked synchronously and are fully exception-
isolated -- a buggy callback will never crash the collection.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

COLLECTION_STARTED = "collection_started"
AD_COLLECTED = "ad_collected"
PAGE_FETCHED = "page_fetched"
ERROR_OCCURRED = "error_occurred"
RATE_LIMITED = "rate_limited"
SESSION_REFRESHED = "session_refreshed"
COLLECTION_FINISHED = "collection_finished"

ALL_EVENT_TYPES = frozenset({
    COLLECTION_STARTED,
    AD_COLLECTED,
    PAGE_FETCHED,
    ERROR_OCCURRED,
    RATE_LIMITED,
    SESSION_REFRESHED,
    COLLECTION_FINISHED,
})


# ---------------------------------------------------------------------------
# Event data model
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A single lifecycle event emitted by the collector.

    Attributes:
        event_type: One of the event type constants (e.g. ``"ad_collected"``).
        data: A type-specific payload dict.
        timestamp: When the event was created (UTC).
    """

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# EventEmitter
# ---------------------------------------------------------------------------

class EventEmitter:
    """A simple synchronous event emitter with callback exception isolation.

    Register callbacks with :meth:`on`, remove with :meth:`off`, and fire
    with :meth:`emit`.  If a callback raises, the exception is logged and
    swallowed -- remaining callbacks and the collection pipeline continue
    unaffected.

    Example::

        emitter = EventEmitter()
        emitter.on("ad_collected", lambda event: print(event.data))
        emitter.emit("ad_collected", {"ad": some_ad})
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[Event], Any]]] = {}

    def on(self, event_type: str, callback: Callable[[Event], Any]) -> None:
        """Register a callback for *event_type*.

        Multiple callbacks may be registered for the same event type and
        they will be called in registration order.

        Args:
            event_type: The event type string to listen for.
            callback: A callable that accepts an :class:`Event` argument.
        """
        self._listeners.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback: Callable[[Event], Any]) -> None:
        """Remove a previously registered *callback* for *event_type*.

        If *callback* was not registered, this is a no-op.

        Args:
            event_type: The event type string.
            callback: The exact callable to remove.
        """
        listeners = self._listeners.get(event_type, [])
        with contextlib.suppress(ValueError):
            listeners.remove(callback)

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> Event:
        """Fire all registered callbacks for *event_type*.

        Each callback invocation is wrapped in ``try/except Exception`` so
        that a failing callback **never** propagates to the caller or
        prevents other callbacks from running.

        Args:
            event_type: The event type string.
            data: Optional payload dict (defaults to ``{}``).

        Returns:
            The :class:`Event` that was created and dispatched.
        """
        event = Event(event_type=event_type, data=data or {})
        for cb in list(self._listeners.get(event_type, [])):
            try:
                cb(event)
            except Exception:
                logger.warning(
                    "Callback %r for event %r raised an exception",
                    cb,
                    event_type,
                    exc_info=True,
                )
        return event

    def has_listeners(self, event_type: str) -> bool:
        """Return ``True`` if at least one callback is registered for *event_type*."""
        return bool(self._listeners.get(event_type))

    def listener_count(self, event_type: str) -> int:
        """Return the number of callbacks registered for *event_type*."""
        return len(self._listeners.get(event_type, []))
