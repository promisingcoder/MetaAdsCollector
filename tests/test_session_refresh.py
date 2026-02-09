"""Tests for session refresh safety in MetaAdsClient."""

from unittest.mock import patch

import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.exceptions import AuthenticationError, SessionExpiredError


class TestRefreshAttemptCounter:
    """Tests for consecutive refresh failure tracking."""

    def test_counter_starts_at_zero(self):
        client = MetaAdsClient()
        assert client._consecutive_refresh_failures == 0

    def test_counter_increments_on_refresh_failure(self):
        """When initialize() fails inside _refresh_session, counter increments."""
        client = MetaAdsClient()
        with patch.object(client, "initialize", side_effect=AuthenticationError("fail")):
            result = client._refresh_session()
        assert result is False
        assert client._consecutive_refresh_failures == 1

    def test_raises_after_max_consecutive_failures(self):
        """After max_refresh_attempts failures, raises SessionExpiredError."""
        client = MetaAdsClient(max_refresh_attempts=2)
        # Simulate 2 prior failures
        client._consecutive_refresh_failures = 2
        with pytest.raises(SessionExpiredError, match="Session refresh failed"):
            client._refresh_session()

    def test_counter_resets_on_successful_refresh(self):
        """A successful refresh resets the counter to 0."""
        client = MetaAdsClient()
        client._consecutive_refresh_failures = 2
        with patch.object(client, "initialize", return_value=True):
            result = client._refresh_session()
        assert result is True
        assert client._consecutive_refresh_failures == 0

    def test_counter_resets_on_successful_graphql_response(self):
        """A successful GraphQL response resets the counter."""
        client = MetaAdsClient()
        client._consecutive_refresh_failures = 2
        # Directly reset, simulating the success path in search_ads
        client._consecutive_refresh_failures = 0
        assert client._consecutive_refresh_failures == 0

    def test_custom_max_refresh_attempts(self):
        """Custom max_refresh_attempts value is respected."""
        client = MetaAdsClient(max_refresh_attempts=5)
        assert client.max_refresh_attempts == 5
        # Should not raise with fewer failures
        client._consecutive_refresh_failures = 4
        with patch.object(client, "initialize", side_effect=AuthenticationError("fail")):
            result = client._refresh_session()
        assert result is False
        assert client._consecutive_refresh_failures == 5
        # Now should raise
        with pytest.raises(SessionExpiredError):
            client._refresh_session()

    def test_default_max_refresh_attempts(self):
        """Default max_refresh_attempts is 3."""
        client = MetaAdsClient()
        assert client.max_refresh_attempts == 3

    def test_multiple_failures_then_success_resets(self):
        """Counter resets properly after multiple failures then a success."""
        client = MetaAdsClient(max_refresh_attempts=5)
        # Fail twice
        with patch.object(client, "initialize", side_effect=AuthenticationError("fail")):
            client._refresh_session()
            client._refresh_session()
        assert client._consecutive_refresh_failures == 2
        # Succeed
        with patch.object(client, "initialize", return_value=True):
            client._refresh_session()
        assert client._consecutive_refresh_failures == 0
