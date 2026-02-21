"""Meta Ads Library Collector - Collect ads from the Facebook Ad Library."""

from .client import MetaAdsClient
from .collector import MetaAdsCollector
from .dedup import DeduplicationTracker
from .events import (
    AD_COLLECTED,
    ALL_EVENT_TYPES,
    COLLECTION_FINISHED,
    COLLECTION_STARTED,
    ERROR_OCCURRED,
    PAGE_FETCHED,
    RATE_LIMITED,
    SESSION_REFRESHED,
    Event,
    EventEmitter,
)
from .exceptions import (
    AuthenticationError,
    InvalidParameterError,
    MetaAdsError,
    ProxyError,
    RateLimitError,
    SessionExpiredError,
)
from .filters import FilterConfig, passes_filter
from .logging_config import setup_logging
from .media import MediaDownloader, MediaDownloadResult
from .models import Ad, AdCreative, AudienceDistribution, ImpressionRange, PageSearchResult, SearchResult, SpendRange
from .proxy_pool import ProxyPool
from .reporting import CollectionReport
from .url_parser import extract_page_id_from_url
from .webhooks import WebhookSender

__version__ = "1.1.0"
__all__ = [
    # Models
    "Ad",
    "AdCreative",
    "AudienceDistribution",
    "SpendRange",
    "ImpressionRange",
    "PageSearchResult",
    "SearchResult",
    # Client & Collector
    "MetaAdsClient",
    "MetaAdsCollector",
    "ProxyPool",
    # Media
    "MediaDownloader",
    "MediaDownloadResult",
    # Filtering & Deduplication
    "FilterConfig",
    "passes_filter",
    "DeduplicationTracker",
    # Events
    "Event",
    "EventEmitter",
    "COLLECTION_STARTED",
    "AD_COLLECTED",
    "PAGE_FETCHED",
    "ERROR_OCCURRED",
    "RATE_LIMITED",
    "SESSION_REFRESHED",
    "COLLECTION_FINISHED",
    "ALL_EVENT_TYPES",
    # Webhooks
    "WebhookSender",
    # Logging & Reporting
    "setup_logging",
    "CollectionReport",
    # Utilities
    "extract_page_id_from_url",
    # Exceptions
    "MetaAdsError",
    "AuthenticationError",
    "RateLimitError",
    "SessionExpiredError",
    "ProxyError",
    "InvalidParameterError",
]
