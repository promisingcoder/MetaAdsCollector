"""Tests for token verification and challenge handler in MetaAdsClient."""

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.exceptions import AuthenticationError


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

    def test_empty_lsd_raises_authentication_error(self):
        """An empty LSD token must raise AuthenticationError."""
        client = _make_bare_client()
        client._tokens = {"lsd": ""}
        with pytest.raises(AuthenticationError, match="LSD token"):
            client._verify_tokens()

    def test_missing_lsd_raises_authentication_error(self):
        """A completely missing LSD token must raise AuthenticationError."""
        client = _make_bare_client()
        client._tokens = {"fb_dtsg": "something"}
        with pytest.raises(AuthenticationError, match="LSD token"):
            client._verify_tokens()

    def test_missing_optional_tokens_log_warnings(self, caplog):
        """Missing optional tokens should produce log warnings but not raise."""
        client = _make_bare_client()
        client._tokens = {"lsd": "valid_token"}
        with caplog.at_level(logging.WARNING, logger="meta_ads_collector.client"):
            client._verify_tokens()
        # Should warn about fb_dtsg and jazoest
        assert "fb_dtsg" in caplog.text
        assert "jazoest" in caplog.text

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
        mock_response = MagicMock(spec=requests.Response)
        mock_response.text = "<html><body>No challenge here</body></html>"
        assert client._handle_challenge(mock_response) is False

    def test_returns_true_when_challenge_cookie_received(self):
        """Returns True when rd_challenge cookie is received after POST."""
        client = self._make_challenge_client()

        # Build a mock initial response containing a challenge URL
        mock_response = MagicMock(spec=requests.Response)
        mock_response.text = "fetch('/__rd_verify_abc123?challenge=1'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        # Mock the session.post to set a challenge cookie
        def fake_post(*args, **kwargs):
            client.session.cookies.set("rd_challenge", "solved")
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        with patch.object(client.session, "post", side_effect=fake_post):
            result = client._handle_challenge(mock_response)
        assert result is True

    def test_returns_false_when_no_cookie_received(self):
        """Returns False when POST succeeds but no challenge cookie is set."""
        client = self._make_challenge_client()

        mock_response = MagicMock(spec=requests.Response)
        mock_response.text = "fetch('/__rd_verify_abc123?challenge=1'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        # Mock the session.post but do NOT set any cookie
        def fake_post(*args, **kwargs):
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        with patch.object(client.session, "post", side_effect=fake_post):
            result = client._handle_challenge(mock_response)
        assert result is False

    def test_returns_false_on_request_exception(self):
        """Returns False when the challenge POST itself fails."""
        client = self._make_challenge_client()

        mock_response = MagicMock(spec=requests.Response)
        mock_response.text = "fetch('/__rd_verify_abc123?challenge=1'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        with patch.object(
            client.session, "post",
            side_effect=requests.exceptions.ConnectionError("timeout"),
        ):
            result = client._handle_challenge(mock_response)
        assert result is False

    def test_returns_true_with_alternate_cookie_name(self):
        """Returns True when an alternate challenge-like cookie is received."""
        client = self._make_challenge_client()

        mock_response = MagicMock(spec=requests.Response)
        mock_response.text = "fetch('/__rd_verify_xyz?challenge=5'"
        mock_response.url = "https://www.facebook.com/ads/library/"

        def fake_post(*args, **kwargs):
            client.session.cookies.set("rd_verification", "done")
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        with patch.object(client.session, "post", side_effect=fake_post):
            result = client._handle_challenge(mock_response)
        assert result is True
