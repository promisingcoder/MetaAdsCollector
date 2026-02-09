"""Webhook sender for Meta Ads Collector.

Provides a :class:`WebhookSender` that POSTs collected ad data to an
external HTTP endpoint.  Designed for use as an event callback with the
:class:`~meta_ads_collector.events.EventEmitter`.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from .events import AD_COLLECTED, Event

logger = logging.getLogger(__name__)


class WebhookSender:
    """POST collected ad data to an external webhook URL.

    Supports retry with exponential backoff and optional batching.
    All public methods are **safe** -- they catch exceptions internally
    and never propagate them.

    Args:
        url: The webhook endpoint URL.
        retries: Maximum number of retry attempts on failure.
        batch_size: Number of ads to buffer before sending.  ``1`` means
            send immediately on each event.
        timeout: HTTP request timeout in seconds.

    Example::

        sender = WebhookSender("https://hooks.example.com/ads")
        collector.event_emitter.on("ad_collected", sender.as_callback())
    """

    def __init__(
        self,
        url: str,
        retries: int = 3,
        batch_size: int = 1,
        timeout: int = 10,
    ) -> None:
        self.url = url
        self.retries = retries
        self.batch_size = batch_size
        self.timeout = timeout
        self._buffer: list[dict[str, Any]] = []
        self._session = requests.Session()

    def send(self, data: dict[str, Any]) -> bool:
        """POST a single JSON payload to the webhook URL.

        Returns ``True`` on success, ``False`` on failure.  **Never raises.**

        Args:
            data: The JSON-serializable dict to send.

        Returns:
            Whether the POST succeeded.
        """
        for attempt in range(self.retries):
            try:
                response = self._session.post(
                    self.url,
                    json=data,
                    timeout=self.timeout,
                )
                if response.ok:
                    logger.debug("Webhook POST succeeded: %s", response.status_code)
                    return True
                logger.warning(
                    "Webhook POST returned %d (attempt %d/%d)",
                    response.status_code,
                    attempt + 1,
                    self.retries,
                )
            except Exception:
                logger.warning(
                    "Webhook POST failed (attempt %d/%d)",
                    attempt + 1,
                    self.retries,
                    exc_info=True,
                )
            # Exponential backoff before retry
            if attempt < self.retries - 1:
                time.sleep(0.1 * (2 ** attempt))

        return False

    def send_batch(self, items: list[dict[str, Any]]) -> bool:
        """POST an array of items as a single JSON payload.

        The items are wrapped in a dict with ``"ads"`` and ``"count"`` keys
        so that :meth:`send` always receives a ``dict``.

        Returns ``True`` on success, ``False`` on failure.  **Never raises.**

        Args:
            items: A list of JSON-serializable dicts.

        Returns:
            Whether the POST succeeded.
        """
        return self.send({"ads": items, "count": len(items)})

    def flush(self) -> bool:
        """Send any buffered ads immediately.

        Returns:
            Whether the flush succeeded (or ``True`` if buffer was empty).
        """
        if not self._buffer:
            return True
        items = list(self._buffer)
        self._buffer.clear()
        return self.send_batch(items)

    def as_callback(self) -> Callable[[Event], None]:
        """Return a callback function suitable for :meth:`EventEmitter.on`.

        The callback extracts ad data from ``ad_collected`` events and
        sends it to the webhook.  When *batch_size* > 1, ads are buffered
        and sent in batches.

        Returns:
            A callable ``(Event) -> None``.
        """
        def _callback(event: Event) -> None:
            if event.event_type != AD_COLLECTED:
                return
            ad = event.data.get("ad")
            if ad is None:
                return
            ad_dict = ad.to_dict() if hasattr(ad, "to_dict") else dict(ad)

            if self.batch_size <= 1:
                self.send(ad_dict)
            else:
                self._buffer.append(ad_dict)
                if len(self._buffer) >= self.batch_size:
                    self.flush()

        return _callback
