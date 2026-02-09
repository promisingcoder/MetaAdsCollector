"""Deduplication tracker for Meta Ad Library collection.

Provides :class:`DeduplicationTracker` with two modes:

* **memory** -- in-process ``set``-based tracking.  Fast, but state is lost
  when the process exits.
* **persistent** -- SQLite-backed tracking.  State survives across runs,
  enabling incremental collection.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DeduplicationTracker:
    """Track which ads have already been collected.

    Args:
        mode: Either ``"memory"`` (default) or ``"persistent"``.
        db_path: Path to a SQLite database file.  Required when
            ``mode="persistent"``, ignored otherwise.

    Example -- in-memory deduplication within a single run::

        tracker = DeduplicationTracker(mode="memory")
        if not tracker.has_seen(ad.id):
            process(ad)
            tracker.mark_seen(ad.id)

    Example -- persistent deduplication across scheduled runs::

        tracker = DeduplicationTracker(mode="persistent", db_path="state.db")
        last = tracker.get_last_collection_time()
        # ... collect ads newer than `last` ...
        tracker.update_collection_time()
        tracker.save()
    """

    def __init__(
        self,
        mode: str = "memory",
        db_path: str | None = None,
    ) -> None:
        if mode not in ("memory", "persistent"):
            raise ValueError(f"Invalid mode: {mode!r}. Expected 'memory' or 'persistent'.")

        self._mode = mode
        self._db_path = db_path

        # In-memory state
        self._seen_ids: set[str] = set()
        self._timestamps: dict[str, datetime] = {}
        self._last_collection_time: datetime | None = None

        # Persistent state
        self._conn: sqlite3.Connection | None = None

        if mode == "persistent":
            if not db_path:
                raise ValueError("db_path is required for persistent mode.")
            self._init_db()
            self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_seen(self, ad_id: str) -> bool:
        """Return ``True`` if *ad_id* has been recorded previously."""
        if self._mode == "persistent" and self._conn is not None:
            cursor = self._conn.execute(
                "SELECT 1 FROM seen_ads WHERE ad_id = ?", (ad_id,)
            )
            return cursor.fetchone() is not None
        return ad_id in self._seen_ids

    def mark_seen(
        self,
        ad_id: str,
        timestamp: datetime | None = None,
    ) -> None:
        """Record *ad_id* as seen.

        Args:
            ad_id: The unique ad identifier.
            timestamp: Optional override for the ``first_seen`` time.
                Defaults to ``datetime.now(timezone.utc)``.
        """
        ts = timestamp or datetime.now(timezone.utc)

        if self._mode == "persistent" and self._conn is not None:
            self._conn.execute(
                "INSERT OR IGNORE INTO seen_ads (ad_id, first_seen) VALUES (?, ?)",
                (ad_id, ts.isoformat()),
            )
        else:
            self._seen_ids.add(ad_id)
            self._timestamps[ad_id] = ts

    def get_last_collection_time(self) -> datetime | None:
        """Return the timestamp of the most recent completed collection run.

        Returns ``None`` if no collection has been recorded yet.
        """
        if self._mode == "persistent" and self._conn is not None:
            cursor = self._conn.execute(
                "SELECT timestamp FROM collection_runs ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return datetime.fromisoformat(row[0])
            return None
        return self._last_collection_time

    def update_collection_time(self) -> None:
        """Record the current time as the latest collection run timestamp."""
        now = datetime.now(timezone.utc)
        if self._mode == "persistent" and self._conn is not None:
            self._conn.execute(
                "INSERT INTO collection_runs (timestamp) VALUES (?)",
                (now.isoformat(),),
            )
        else:
            self._last_collection_time = now

    def save(self) -> None:
        """Persist in-flight changes to disk (persistent mode only).

        For in-memory mode this is a no-op.
        """
        if self._mode == "persistent" and self._conn is not None:
            self._conn.commit()
            logger.debug("Dedup state saved to %s", self._db_path)

    def load(self) -> None:
        """Load state from disk into the in-memory cache (persistent mode).

        For in-memory mode this is a no-op.
        """
        if self._mode == "persistent" and self._conn is not None:
            cursor = self._conn.execute("SELECT ad_id, first_seen FROM seen_ads")
            for row in cursor:
                self._seen_ids.add(row[0])
                with contextlib.suppress(ValueError, TypeError):
                    self._timestamps[row[0]] = datetime.fromisoformat(row[1])

            cursor = self._conn.execute(
                "SELECT timestamp FROM collection_runs ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                with contextlib.suppress(ValueError, TypeError):
                    self._last_collection_time = datetime.fromisoformat(row[0])

            logger.debug(
                "Loaded %d seen ads from %s", len(self._seen_ids), self._db_path
            )

    def clear(self) -> None:
        """Remove all tracked state."""
        self._seen_ids.clear()
        self._timestamps.clear()
        self._last_collection_time = None

        if self._mode == "persistent" and self._conn is not None:
            self._conn.execute("DELETE FROM seen_ads")
            self._conn.execute("DELETE FROM collection_runs")
            self._conn.commit()

    def count(self) -> int:
        """Return the number of unique ad IDs that have been seen."""
        if self._mode == "persistent" and self._conn is not None:
            cursor = self._conn.execute("SELECT COUNT(*) FROM seen_ads")
            row = cursor.fetchone()
            return row[0] if row else 0
        return len(self._seen_ids)

    def close(self) -> None:
        """Close the underlying database connection (persistent mode)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> DeduplicationTracker:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.save()
        self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the SQLite database and tables if they do not exist."""
        assert self._db_path is not None  # guaranteed by __init__ guard
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_ads ("
            "  ad_id TEXT PRIMARY KEY,"
            "  first_seen TEXT NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS collection_runs ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  timestamp TEXT NOT NULL"
            ")"
        )
        self._conn.commit()
