"""Custom exceptions for Meta Ads Library Collector."""


class MetaAdsError(Exception):
    """Base exception for all Meta Ads Collector errors."""


class AuthenticationError(MetaAdsError):
    """Raised when session initialization or token extraction fails."""


class RateLimitError(MetaAdsError):
    """Raised when the Meta API rate-limits requests."""

    def __init__(self, message: str = "Rate limited by Meta API", retry_after: float = 0):
        super().__init__(message)
        self.retry_after = retry_after


class SessionExpiredError(MetaAdsError):
    """Raised when the session has expired and automatic refresh failed."""


class ProxyError(MetaAdsError):
    """Raised when the proxy configuration is invalid or the proxy is unreachable."""


class InvalidParameterError(MetaAdsError):
    """Raised when an invalid parameter value is passed to the public API."""

    def __init__(self, param: str, value: object, allowed: object = None):
        msg = f"Invalid value for '{param}': {value!r}"
        if allowed is not None:
            msg += f". Allowed values: {allowed}"
        super().__init__(msg)
        self.param = param
        self.value = value
        self.allowed = allowed
