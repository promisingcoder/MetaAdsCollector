"""Tests for meta_ads_collector.exceptions."""

from meta_ads_collector.exceptions import (
    AuthenticationError,
    InvalidParameterError,
    MetaAdsError,
    ProxyError,
    RateLimitError,
    SessionExpiredError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_base(self):
        assert issubclass(AuthenticationError, MetaAdsError)
        assert issubclass(RateLimitError, MetaAdsError)
        assert issubclass(SessionExpiredError, MetaAdsError)
        assert issubclass(ProxyError, MetaAdsError)
        assert issubclass(InvalidParameterError, MetaAdsError)

    def test_base_is_exception(self):
        assert issubclass(MetaAdsError, Exception)


class TestRateLimitError:
    def test_default_retry_after(self):
        err = RateLimitError()
        assert err.retry_after == 0

    def test_custom_retry_after(self):
        err = RateLimitError("slow down", retry_after=5.0)
        assert err.retry_after == 5.0


class TestInvalidParameterError:
    def test_message_format(self):
        err = InvalidParameterError("country", "XY", ["US", "EG"])
        assert "country" in str(err)
        assert "'XY'" in str(err)
        assert "['US', 'EG']" in str(err)

    def test_attrs(self):
        err = InvalidParameterError("field", "val", {"A", "B"})
        assert err.param == "field"
        assert err.value == "val"
        assert err.allowed == {"A", "B"}
