"""Tests for token verification and challenge handler in MetaAdsClient."""

import logging
from unittest.mock import MagicMock, patch

from curl_cffi.requests.exceptions import ConnectionError as CffiConnectionError

from meta_ads_collector.client import MetaAdsClient


def _make_client() -> MetaAdsClient:
    """Create a fully-constructed client (through __init__) for testing."""
    client = MetaAdsClient()
    return client


def _make_bare_client() -> MetaAdsClient:
    """Create a bare client without calling __init__, for isolated tests."""
    client = MetaAdsClient.__new__(MetaAdsClient)
    client._tokens = {}
    return client


class TestVerifyTokens:
    """Tests for MetaAdsClient._verify_tokens."""

    def test_valid_tokens_pass(self):
        """A token set with a non-empty LSD should pass silently."""
        client = _make_bare_client()
        client._tokens = {"lsd": "some_token_value", "fb_dtsg": "dtsg_value", "jazoest": "12345"}
        client._verify_tokens()  # should not raise

    def test_empty_lsd_generates_fallback(self):
        """An empty LSD token should be auto-generated."""
        client = _make_bare_client()
        client._tokens = {"lsd": ""}
        client._verify_tokens()
        assert client._tokens["lsd"]  # non-empty
        assert len(client._tokens["lsd"]) >= 8

    def test_missing_lsd_generates_fallback(self):
        """A completely missing LSD token should be auto-generated."""
        client = _make_bare_client()
        client._tokens = {"fb_dtsg": "something"}
        client._verify_tokens()
        assert "lsd" in client._tokens
        assert len(client._tokens["lsd"]) >= 8

    def test_missing_optional_tokens_auto_generated(self):
        """Missing optional tokens should be auto-generated, not just warned."""
        client = _make_bare_client()
        client._tokens = {"lsd": "valid_token"}
        client._verify_tokens()
        assert "fb_dtsg" in client._tokens
        assert "jazoest" in client._tokens
        assert len(client._tokens["fb_dtsg"]) >= 20

    def test_all_tokens_present_no_warnings(self, caplog):
        """When all optional tokens are present, no warnings should be logged."""
        client = _make_bare_client()
        client._tokens = {"lsd": "abc", "fb_dtsg": "dtsg", "jazoest": "999"}
        with caplog.at_level(logging.WARNING, logger="meta_ads_collector.client"):
            client._verify_tokens()
        assert "fb_dtsg" not in caplog.text
        assert "jazoest" not in caplog.text


class TestChallengeHandler:
    """Tests for MetaAdsClient._handle_challenge."""

    def _make_challenge_client(self):
        """Create a client with the minimum state for challenge handling."""
        client = _make_client()
        return client

    def test_returns_false_when_no_challenge_url(self):
        """If no challenge URL pattern is found, returns False."""
        client = self._make_challenge_client()
        mock_response = MagicMock()
        mock_response.text = "<html><body>No challenge here</body></html>"
        assert client._handle_challenge(mock_response) is False

    def test_returns_true_when_challenge_cookie_received(self):
        """Returns True when rd_challenge cookie is received after POST."""
        client = self._make_challenge_client()

        # Build a mock initial response containing a challenge URL
        mock_response = MagicMock()
        mock_response.text = "fetch('/__rd_verify_abc123?challenge=1'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        # Mock the session.post to set a challenge cookie
        def fake_post(*args, **kwargs):
            client.session.cookies.set("rd_challenge", "solved")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch.object(client.session, "post", side_effect=fake_post):
            result = client._handle_challenge(mock_response)
        assert result is True

    def test_returns_false_when_no_cookie_received(self):
        """Returns False when POST succeeds but no challenge cookie is set."""
        client = self._make_challenge_client()

        mock_response = MagicMock()
        mock_response.text = "fetch('/__rd_verify_abc123?challenge=1'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        # Mock the session.post but do NOT set any cookie
        def fake_post(*args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch.object(client.session, "post", side_effect=fake_post):
            result = client._handle_challenge(mock_response)
        assert result is False

    def test_returns_false_on_request_exception(self):
        """Returns False when the challenge POST itself fails."""
        client = self._make_challenge_client()

        mock_response = MagicMock()
        mock_response.text = "fetch('/__rd_verify_abc123?challenge=1'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        with patch.object(
            client.session, "post",
            side_effect=CffiConnectionError("timeout"),
        ):
            result = client._handle_challenge(mock_response)
        assert result is False

    def test_returns_true_with_alternate_cookie_name(self):
        """Returns True when an alternate challenge-like cookie is received."""
        client = self._make_challenge_client()

        mock_response = MagicMock()
        mock_response.text = "fetch('/__rd_verify_xyz?challenge=5'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        def fake_post(*args, **kwargs):
            client.session.cookies.set("rd_verification", "done")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch.object(client.session, "post", side_effect=fake_post):
            result = client._handle_challenge(mock_response)
        assert result is True
