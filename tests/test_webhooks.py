"""Tests for meta_ads_collector.webhooks (WebhookSender)."""

import sys
from unittest.mock import MagicMock, patch

import pytest
from curl_cffi.requests import Session as CffiSession

from meta_ads_collector.events import AD_COLLECTED, Event
from meta_ads_collector.models import Ad, PageInfo
from meta_ads_collector.webhooks import WebhookSender

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ad():
    """A minimal Ad for testing webhook payloads."""
    return Ad(
        id="ad-123",
        page=PageInfo(id="pg-1", name="Test Page"),
    )


@pytest.fixture
def sender():
    """WebhookSender with a mocked session."""
    s = WebhookSender(url="https://hooks.example.com/ads")
    s._session = MagicMock()
    return s


# ---------------------------------------------------------------------------
# send()
# ---------------------------------------------------------------------------


class TestWebhookSend:
    def test_send_posts_json(self, sender):
        sender._session.post.return_value = MagicMock(ok=True, status_code=200)
        result = sender.send({"id": "ad-1"})

        assert result is True
        sender._session.post.assert_called_once_with(
            "https://hooks.example.com/ads",
            json={"id": "ad-1"},
            timeout=10,
        )

    def test_send_returns_false_on_http_error(self):
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=1)
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=False, status_code=500)
        result = sender.send({"id": "ad-1"})
        assert result is False

    def test_send_returns_false_on_exception(self):
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=1)
        sender._session = MagicMock()
        sender._session.post.side_effect = ConnectionError("connection refused")
        result = sender.send({"id": "ad-1"})
        assert result is False

    def test_send_never_raises(self):
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=1)
        sender._session = MagicMock()
        sender._session.post.side_effect = RuntimeError("unexpected")
        # Must not raise
        result = sender.send({"id": "ad-1"})
        assert result is False

    def test_send_custom_timeout(self):
        sender = WebhookSender(url="https://hooks.example.com/ads", timeout=30)
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=True)
        sender.send({"id": "ad-1"})
        assert sender._session.post.call_args[1]["timeout"] == 30


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestWebhookRetry:
    @patch("meta_ads_collector.webhooks.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep):
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=3)
        sender._session = MagicMock()
        # Fail twice, then succeed
        sender._session.post.side_effect = [
            MagicMock(ok=False, status_code=500),
            MagicMock(ok=False, status_code=500),
            MagicMock(ok=True, status_code=200),
        ]
        result = sender.send({"id": "ad-1"})

        assert result is True
        assert sender._session.post.call_count == 3

    @patch("meta_ads_collector.webhooks.time.sleep")
    def test_retries_exhausted_returns_false(self, mock_sleep):
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=2)
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=False, status_code=500)
        result = sender.send({"id": "ad-1"})

        assert result is False
        assert sender._session.post.call_count == 2

    @patch("meta_ads_collector.webhooks.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=3)
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=False, status_code=500)
        sender.send({"id": "ad-1"})

        # Backoff: 0.1 * 2^0 = 0.1, 0.1 * 2^1 = 0.2
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 2  # No sleep after last retry
        assert abs(sleep_calls[0] - 0.1) < 0.01
        assert abs(sleep_calls[1] - 0.2) < 0.01


# ---------------------------------------------------------------------------
# send_batch()
# ---------------------------------------------------------------------------


class TestWebhookSendBatch:
    def test_send_batch_posts_wrapped_dict(self, sender):
        """send_batch wraps items in {"ads": [...], "count": N}."""
        sender._session.post.return_value = MagicMock(ok=True, status_code=200)
        items = [{"id": "ad-1"}, {"id": "ad-2"}, {"id": "ad-3"}]
        result = sender.send_batch(items)

        assert result is True
        sender._session.post.assert_called_once_with(
            "https://hooks.example.com/ads",
            json={"ads": items, "count": 3},
            timeout=10,
        )

    def test_send_batch_payload_has_correct_structure(self, sender):
        sender._session.post.return_value = MagicMock(ok=True, status_code=200)
        items = [{"id": "ad-1"}]
        sender.send_batch(items)

        posted_json = sender._session.post.call_args[1]["json"]
        assert isinstance(posted_json, dict)
        assert "ads" in posted_json
        assert "count" in posted_json
        assert posted_json["count"] == 1
        assert posted_json["ads"] == items


# ---------------------------------------------------------------------------
# as_callback()
# ---------------------------------------------------------------------------


class TestWebhookAsCallback:
    def test_callback_sends_ad_data(self, sender, sample_ad):
        sender._session.post.return_value = MagicMock(ok=True)
        callback = sender.as_callback()

        event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
        callback(event)

        sender._session.post.assert_called_once()
        posted_json = sender._session.post.call_args[1]["json"]
        assert posted_json["id"] == "ad-123"

    def test_callback_ignores_non_ad_events(self, sender):
        callback = sender.as_callback()

        event = Event(event_type="page_fetched", data={"page_number": 1})
        callback(event)

        sender._session.post.assert_not_called()

    def test_callback_batch_mode(self, sample_ad):
        sender = WebhookSender(
            url="https://hooks.example.com/ads",
            batch_size=3,
        )
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=True)
        callback = sender.as_callback()

        # Send 3 ads -- should trigger a batch send on the 3rd
        for _ in range(3):
            event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
            callback(event)

        sender._session.post.assert_called_once()
        posted_json = sender._session.post.call_args[1]["json"]
        # Batch is wrapped in {"ads": [...], "count": N}
        assert isinstance(posted_json, dict)
        assert "ads" in posted_json
        assert len(posted_json["ads"]) == 3
        assert posted_json["count"] == 3

    def test_callback_batch_mode_partial_batch_not_sent(self, sample_ad):
        sender = WebhookSender(
            url="https://hooks.example.com/ads",
            batch_size=5,
        )
        sender._session = MagicMock()
        callback = sender.as_callback()

        # Send 2 ads -- should NOT trigger a send (batch_size=5)
        for _ in range(2):
            event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
            callback(event)

        sender._session.post.assert_not_called()
        assert len(sender._buffer) == 2

    def test_flush_sends_buffered_ads(self, sample_ad):
        sender = WebhookSender(
            url="https://hooks.example.com/ads",
            batch_size=10,
        )
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=True)
        callback = sender.as_callback()

        for _ in range(3):
            event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
            callback(event)

        sender._session.post.assert_not_called()
        result = sender.flush()
        assert result is True
        assert sender._session.post.call_count == 1
        assert len(sender._buffer) == 0

    def test_flush_empty_buffer_returns_true(self):
        sender = WebhookSender(url="https://hooks.example.com/ads")
        assert sender.flush() is True


# ---------------------------------------------------------------------------
# Connection pooling
# ---------------------------------------------------------------------------


class TestWebhookConnectionPooling:
    def test_session_created_in_init(self):
        sender = WebhookSender(url="https://hooks.example.com/ads")
        assert isinstance(sender._session, CffiSession)

    def test_session_reused_across_sends(self):
        sender = WebhookSender(url="https://hooks.example.com/ads")
        sender._session = MagicMock()
        sender._session.post.return_value = MagicMock(ok=True, status_code=200)

        sender.send({"id": "ad-1"})
        sender.send({"id": "ad-2"})

        # Both calls should use the same session
        assert sender._session.post.call_count == 2


# ---------------------------------------------------------------------------
# CLI flag
# ---------------------------------------------------------------------------


class TestWebhookCLIFlag:
    def test_webhook_url_flag_parsed(self):
        from meta_ads_collector.cli import parse_args
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json", "--webhook-url", "https://hooks.example.com/ads",
        ]):
            args = parse_args()
            assert args.webhook_url == "https://hooks.example.com/ads"

    def test_webhook_url_default_none(self):
        from meta_ads_collector.cli import parse_args
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.webhook_url is None
