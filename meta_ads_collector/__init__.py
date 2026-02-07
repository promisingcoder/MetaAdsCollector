"""Meta Ads Library Collector - Collect ads from the Facebook Ad Library."""

from .models import Ad, AdCreative, AudienceDistribution, SpendRange, ImpressionRange, SearchResult
from .client import MetaAdsClient
from .collector import MetaAdsCollector
from .exceptions import (
    MetaAdsError,
    AuthenticationError,
    RateLimitError,
    SessionExpiredError,
    ProxyError,
    InvalidParameterError,
)

__version__ = "1.0.0"
__all__ = [
    # Models
    "Ad",
    "AdCreative",
    "AudienceDistribution",
    "SpendRange",
    "ImpressionRange",
    "SearchResult",
    # Client & Collector
    "MetaAdsClient",
    "MetaAdsCollector",
    # Exceptions
    "MetaAdsError",
    "AuthenticationError",
    "RateLimitError",
    "SessionExpiredError",
    "ProxyError",
    "InvalidParameterError",
]
