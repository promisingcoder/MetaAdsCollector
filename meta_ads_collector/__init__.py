"""Meta Ads Library Collector - Scrapes ads from Facebook Ad Library"""

from .models import Ad, AdCreative, AudienceDistribution, SpendRange, ImpressionRange
from .client import MetaAdsClient
from .collector import MetaAdsCollector

__version__ = "1.0.0"
__all__ = [
    "Ad",
    "AdCreative",
    "AudienceDistribution",
    "SpendRange",
    "ImpressionRange",
    "MetaAdsClient",
    "MetaAdsCollector",
]
