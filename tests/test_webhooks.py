"""Tests for meta_ads_collector.webhooks (WebhookSender)."""

import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

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


# ---------------------------------------------------------------------------
# send()
# ---------------------------------------------------------------------------


class TestWebhookSend:
    @patch("requests.Session.post")
    def test_send_posts_json(self, mock_post):
        mock_post.return_value = MagicMock(ok=True, status_code=200)
        sender = WebhookSender(url="https://hooks.example.com/ads")
        result = sender.send({"id": "ad-1"})

        assert result is True
        mock_post.assert_called_once_with(
            "https://hooks.example.com/ads",
            json={"id": "ad-1"},
            timeout=10,
        )

    @patch("requests.Session.post")
    def test_send_returns_false_on_http_error(self, mock_post):
        mock_post.return_value = MagicMock(ok=False, status_code=500)
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=1)
        result = sender.send({"id": "ad-1"})
        assert result is False

    @patch("requests.Session.post")
    def test_send_returns_false_on_exception(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("connection refused")
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=1)
        result = sender.send({"id": "ad-1"})
        assert result is False

    @patch("requests.Session.post")
    def test_send_never_raises(self, mock_post):
        mock_post.side_effect = RuntimeError("unexpected")
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=1)
        # Must not raise
        result = sender.send({"id": "ad-1"})
        assert result is False

    @patch("requests.Session.post")
    def test_send_custom_timeout(self, mock_post):
        mock_post.return_value = MagicMock(ok=True)
        sender = WebhookSender(url="https://hooks.example.com/ads", timeout=30)
        sender.send({"id": "ad-1"})
        assert mock_post.call_args[1]["timeout"] == 30


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestWebhookRetry:
    @patch("meta_ads_collector.webhooks.time.sleep")
    @patch("requests.Session.post")
    def test_retries_on_failure_then_succeeds(self, mock_post, mock_sleep):
        # Fail twice, then succeed
        mock_post.side_effect = [
            MagicMock(ok=False, status_code=500),
            MagicMock(ok=False, status_code=500),
            MagicMock(ok=True, status_code=200),
        ]
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=3)
        result = sender.send({"id": "ad-1"})

        assert result is True
        assert mock_post.call_count == 3

    @patch("meta_ads_collector.webhooks.time.sleep")
    @patch("requests.Session.post")
    def test_retries_exhausted_returns_false(self, mock_post, mock_sleep):
        mock_post.return_value = MagicMock(ok=False, status_code=500)
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=2)
        result = sender.send({"id": "ad-1"})

        assert result is False
        assert mock_post.call_count == 2

    @patch("meta_ads_collector.webhooks.time.sleep")
    @patch("requests.Session.post")
    def test_exponential_backoff(self, mock_post, mock_sleep):
        mock_post.return_value = MagicMock(ok=False, status_code=500)
        sender = WebhookSender(url="https://hooks.example.com/ads", retries=3)
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
    @patch("requests.Session.post")
    def test_send_batch_posts_wrapped_dict(self, mock_post):
        """send_batch wraps items in {"ads": [...], "count": N}."""
        mock_post.return_value = MagicMock(ok=True, status_code=200)
        sender = WebhookSender(url="https://hooks.example.com/ads")
        items = [{"id": "ad-1"}, {"id": "ad-2"}, {"id": "ad-3"}]
        result = sender.send_batch(items)

        assert result is True
        mock_post.assert_called_once_with(
            "https://hooks.example.com/ads",
            json={"ads": items, "count": 3},
            timeout=10,
        )

    @patch("requests.Session.post")
    def test_send_batch_payload_has_correct_structure(self, mock_post):
        mock_post.return_value = MagicMock(ok=True, status_code=200)
        sender = WebhookSender(url="https://hooks.example.com/ads")
        items = [{"id": "ad-1"}]
        sender.send_batch(items)

        posted_json = mock_post.call_args[1]["json"]
        assert isinstance(posted_json, dict)
        assert "ads" in posted_json
        assert "count" in posted_json
        assert posted_json["count"] == 1
        assert posted_json["ads"] == items


# ---------------------------------------------------------------------------
# as_callback()
# ---------------------------------------------------------------------------


class TestWebhookAsCallback:
    @patch("requests.Session.post")
    def test_callback_sends_ad_data(self, mock_post, sample_ad):
        mock_post.return_value = MagicMock(ok=True)
        sender = WebhookSender(url="https://hooks.example.com/ads")
        callback = sender.as_callback()

        event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
        callback(event)

        mock_post.assert_called_once()
        posted_json = mock_post.call_args[1]["json"]
        assert posted_json["id"] == "ad-123"

    @patch("requests.Session.post")
    def test_callback_ignores_non_ad_events(self, mock_post):
        sender = WebhookSender(url="https://hooks.example.com/ads")
        callback = sender.as_callback()

        event = Event(event_type="page_fetched", data={"page_number": 1})
        callback(event)

        mock_post.assert_not_called()

    @patch("requests.Session.post")
    def test_callback_batch_mode(self, mock_post, sample_ad):
        mock_post.return_value = MagicMock(ok=True)
        sender = WebhookSender(
            url="https://hooks.example.com/ads",
            batch_size=3,
        )
        callback = sender.as_callback()

        # Send 3 ads -- should trigger a batch send on the 3rd
        for _ in range(3):
            event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
            callback(event)

        mock_post.assert_called_once()
        posted_json = mock_post.call_args[1]["json"]
        # Batch is wrapped in {"ads": [...], "count": N}
        assert isinstance(posted_json, dict)
        assert "ads" in posted_json
        assert len(posted_json["ads"]) == 3
        assert posted_json["count"] == 3

    @patch("requests.Session.post")
    def test_callback_batch_mode_partial_batch_not_sent(self, mock_post, sample_ad):
        sender = WebhookSender(
            url="https://hooks.example.com/ads",
            batch_size=5,
        )
        callback = sender.as_callback()

        # Send 2 ads -- should NOT trigger a send (batch_size=5)
        for _ in range(2):
            event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
            callback(event)

        mock_post.assert_not_called()
        assert len(sender._buffer) == 2

    @patch("requests.Session.post")
    def test_flush_sends_buffered_ads(self, mock_post, sample_ad):
        mock_post.return_value = MagicMock(ok=True)
        sender = WebhookSender(
            url="https://hooks.example.com/ads",
            batch_size=10,
        )
        callback = sender.as_callback()

        for _ in range(3):
            event = Event(event_type=AD_COLLECTED, data={"ad": sample_ad})
            callback(event)

        mock_post.assert_not_called()
        result = sender.flush()
        assert result is True
        assert mock_post.call_count == 1
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
        assert isinstance(sender._session, requests.Session)

    @patch("requests.Session.post")
    def test_session_reused_across_sends(self, mock_post):
        mock_post.return_value = MagicMock(ok=True, status_code=200)
        sender = WebhookSender(url="https://hooks.example.com/ads")

        sender.send({"id": "ad-1"})
        sender.send({"id": "ad-2"})

        # Both calls should use the same session (Session.post patched)
        assert mock_post.call_count == 2


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
