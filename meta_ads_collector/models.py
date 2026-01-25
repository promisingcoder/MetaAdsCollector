"""Data models for Meta Ads Library"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


@dataclass
class SpendRange:
    """Represents ad spend range"""
    lower_bound: Optional[int] = None
    upper_bound: Optional[int] = None
    currency: Optional[str] = None

    def __str__(self) -> str:
        if self.lower_bound and self.upper_bound:
            return f"{self.currency} {self.lower_bound:,} - {self.upper_bound:,}"
        return "N/A"


@dataclass
class ImpressionRange:
    """Represents impression count range"""
    lower_bound: Optional[int] = None
    upper_bound: Optional[int] = None

    def __str__(self) -> str:
        if self.lower_bound and self.upper_bound:
            return f"{self.lower_bound:,} - {self.upper_bound:,}"
        return "N/A"


@dataclass
class AudienceDistribution:
    """Demographic or geographic distribution data"""
    category: str
    percentage: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdCreative:
    """Ad creative content - text, media, links"""
    body: Optional[str] = None
    caption: Optional[str] = None
    description: Optional[str] = None
    title: Optional[str] = None
    link_url: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    video_hd_url: Optional[str] = None
    video_sd_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    cta_text: Optional[str] = None
    cta_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PageInfo:
    """Information about the page running the ad"""
    id: str
    name: str
    profile_picture_url: Optional[str] = None
    page_url: Optional[str] = None
    likes: Optional[int] = None
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TargetingInfo:
    """Ad targeting information"""
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    genders: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    location_types: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
    excluded_locations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Ad:
    """
    Complete Meta Ad schema with all available fields from Ad Library.

    This schema captures the full data available from the Meta Ad Library
    GraphQL API including creative content, targeting, performance metrics,
    and compliance information.
    """
    # Core identifiers
    id: str  # Ad Archive ID
    ad_library_id: Optional[str] = None

    # Page information
    page: Optional[PageInfo] = None

    # Ad status and timing
    is_active: Optional[bool] = None  # None when status unknown from search results
    ad_status: Optional[str] = None  # ACTIVE, INACTIVE, etc.
    delivery_start_time: Optional[datetime] = None
    delivery_stop_time: Optional[datetime] = None

    # Creative content (can have multiple variations)
    creatives: List[AdCreative] = field(default_factory=list)

    # Snapshot and preview
    snapshot_url: Optional[str] = None
    ad_snapshot_url: Optional[str] = None

    # Performance metrics
    impressions: Optional[ImpressionRange] = None
    spend: Optional[SpendRange] = None
    reach: Optional[ImpressionRange] = None
    currency: Optional[str] = None

    # Audience demographics
    age_gender_distribution: List[AudienceDistribution] = field(default_factory=list)
    region_distribution: List[AudienceDistribution] = field(default_factory=list)

    # Targeting
    targeting: Optional[TargetingInfo] = None
    estimated_audience_size_lower: Optional[int] = None
    estimated_audience_size_upper: Optional[int] = None

    # Platform and placement
    publisher_platforms: List[str] = field(default_factory=list)  # facebook, instagram, messenger, audience_network

    # Languages
    languages: List[str] = field(default_factory=list)

    # Political/Issue ad specific fields
    bylines: List[str] = field(default_factory=list)
    funding_entity: Optional[str] = None
    disclaimer: Optional[str] = None

    # Categories
    ad_type: Optional[str] = None  # POLITICAL_AND_ISSUE_ADS, HOUSING_ADS, etc.
    categories: List[str] = field(default_factory=list)

    # EU transparency fields
    beneficiary_payers: List[str] = field(default_factory=list)

    # Metadata
    collation_id: Optional[str] = None
    collation_count: Optional[int] = None

    # Raw data for debugging/extensibility
    raw_data: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # Collection metadata
    collected_at: datetime = field(default_factory=datetime.utcnow)
    collection_source: str = "meta_ads_library"

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            "id": self.id,
            "ad_library_id": self.ad_library_id,
            "page": self.page.to_dict() if self.page else None,
            "is_active": self.is_active,
            "ad_status": self.ad_status,
            "delivery_start_time": self.delivery_start_time.isoformat() if self.delivery_start_time else None,
            "delivery_stop_time": self.delivery_stop_time.isoformat() if self.delivery_stop_time else None,
            "creatives": [c.to_dict() for c in self.creatives],
            "snapshot_url": self.snapshot_url,
            "ad_snapshot_url": self.ad_snapshot_url,
            "impressions": {
                "lower_bound": self.impressions.lower_bound,
                "upper_bound": self.impressions.upper_bound,
            } if self.impressions else None,
            "spend": {
                "lower_bound": self.spend.lower_bound,
                "upper_bound": self.spend.upper_bound,
                "currency": self.spend.currency,
            } if self.spend else None,
            "reach": {
                "lower_bound": self.reach.lower_bound,
                "upper_bound": self.reach.upper_bound,
            } if self.reach else None,
            "currency": self.currency,
            "age_gender_distribution": [d.to_dict() for d in self.age_gender_distribution],
            "region_distribution": [d.to_dict() for d in self.region_distribution],
            "targeting": self.targeting.to_dict() if self.targeting else None,
            "estimated_audience_size": {
                "lower_bound": self.estimated_audience_size_lower,
                "upper_bound": self.estimated_audience_size_upper,
            } if self.estimated_audience_size_lower else None,
            "publisher_platforms": self.publisher_platforms,
            "languages": self.languages,
            "bylines": self.bylines,
            "funding_entity": self.funding_entity,
            "disclaimer": self.disclaimer,
            "ad_type": self.ad_type,
            "categories": self.categories,
            "beneficiary_payers": self.beneficiary_payers,
            "collation_id": self.collation_id,
            "collation_count": self.collation_count,
            "collected_at": self.collected_at.isoformat(),
            "collection_source": self.collection_source,
        }

        if include_raw and self.raw_data:
            result["raw_data"] = self.raw_data

        return result

    def to_json(self, include_raw: bool = False, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(include_raw=include_raw), indent=indent, ensure_ascii=False)

    @classmethod
    def from_graphql_response(cls, data: Dict[str, Any]) -> "Ad":
        """
        Parse an ad from the Meta Ad Library GraphQL response.
        Handles the flattened structure from AdLibrarySearchPaginationQuery.
        """
        # Extract page info - can be in nested page object or flat fields
        page_data = data.get("page") or data.get("pageInfo") or {}
        if page_data:
            page = PageInfo(
                id=page_data.get("id", ""),
                name=page_data.get("name", ""),
                profile_picture_url=page_data.get("profile_picture", {}).get("uri") if page_data.get("profile_picture") else None,
                page_url=page_data.get("url"),
            )
        else:
            # Flat structure from search results
            page = PageInfo(
                id=data.get("page_id", ""),
                name=data.get("page_name", ""),
                profile_picture_url=data.get("page_profile_picture_url"),
                page_url=data.get("page_profile_uri"),
                likes=data.get("page_like_count"),
            )

        # Parse creatives from cards array
        creatives = []
        cards = data.get("cards") or []

        if cards:
            # New format: cards array contains creative content
            for card in cards:
                creative = AdCreative(
                    body=card.get("body"),
                    caption=card.get("caption") or data.get("caption"),
                    description=card.get("link_description"),
                    title=card.get("title"),
                    link_url=card.get("link_url"),
                    image_url=card.get("resized_image_url") or card.get("original_image_url"),
                    video_url=card.get("video_hd_url") or card.get("video_sd_url"),
                    video_hd_url=card.get("video_hd_url"),
                    video_sd_url=card.get("video_sd_url"),
                    thumbnail_url=card.get("video_preview_image_url"),
                    cta_text=card.get("cta_text") or data.get("cta_text"),
                    cta_type=card.get("cta_type"),
                )
                creatives.append(creative)
        else:
            # Fallback to old format
            bodies = data.get("ad_creative_bodies") or data.get("adCreativeBodies") or []
            link_captions = data.get("ad_creative_link_captions") or data.get("adCreativeLinkCaptions") or []
            link_descriptions = data.get("ad_creative_link_descriptions") or data.get("adCreativeLinkDescriptions") or []
            link_titles = data.get("ad_creative_link_titles") or data.get("adCreativeLinkTitles") or []

            max_creatives = max(len(bodies), len(link_titles), 1)
            for i in range(max_creatives):
                creative = AdCreative(
                    body=bodies[i] if i < len(bodies) else None,
                    caption=link_captions[i] if i < len(link_captions) else None,
                    description=link_descriptions[i] if i < len(link_descriptions) else None,
                    title=link_titles[i] if i < len(link_titles) else None,
                )
                creatives.append(creative)

            # Parse snapshot/display images for old format
            snapshot = data.get("snapshot") or {}
            if snapshot:
                for i, creative in enumerate(creatives):
                    snap_cards = snapshot.get("cards") or []
                    if i < len(snap_cards):
                        card = snap_cards[i]
                        creative.image_url = card.get("resized_image_url") or card.get("original_image_url")
                        creative.video_url = card.get("video_hd_url") or card.get("video_sd_url")
                        creative.video_hd_url = card.get("video_hd_url")
                        creative.video_sd_url = card.get("video_sd_url")
                        creative.link_url = card.get("link_url")
                        creative.cta_text = card.get("cta_text")
                        creative.cta_type = card.get("cta_type")

        # Parse dates
        delivery_start = None
        delivery_stop = None
        start_time = data.get("ad_delivery_start_time") or data.get("startDate")
        stop_time = data.get("ad_delivery_stop_time") or data.get("endDate")

        if start_time:
            try:
                if isinstance(start_time, int):
                    delivery_start = datetime.fromtimestamp(start_time)
                else:
                    delivery_start = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if stop_time:
            try:
                if isinstance(stop_time, int):
                    delivery_stop = datetime.fromtimestamp(stop_time)
                else:
                    delivery_stop = datetime.fromisoformat(str(stop_time).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Parse impressions
        impressions = None
        imp_data = data.get("impressions") or data.get("impressionsWithIndex") or {}
        if imp_data:
            impressions = ImpressionRange(
                lower_bound=imp_data.get("lower_bound") or imp_data.get("lowerBound"),
                upper_bound=imp_data.get("upper_bound") or imp_data.get("upperBound"),
            )

        # Parse spend
        spend = None
        spend_data = data.get("spend") or data.get("spendWithIndex") or {}
        if spend_data:
            spend = SpendRange(
                lower_bound=spend_data.get("lower_bound") or spend_data.get("lowerBound"),
                upper_bound=spend_data.get("upper_bound") or spend_data.get("upperBound"),
                currency=data.get("currency"),
            )

        # Parse demographic distribution
        age_gender_dist = []
        demo_data = data.get("demographic_distribution") or data.get("demographicDistribution") or []
        for item in demo_data:
            age_gender_dist.append(AudienceDistribution(
                category=f"{item.get('age', 'unknown')}_{item.get('gender', 'unknown')}",
                percentage=float(item.get("percentage", 0)),
            ))

        # Parse region distribution
        region_dist = []
        region_data = data.get("delivery_by_region") or data.get("deliveryByRegion") or []
        for item in region_data:
            region_dist.append(AudienceDistribution(
                category=item.get("region", "unknown"),
                percentage=float(item.get("percentage", 0)),
            ))

        # Parse publisher platforms
        platforms = data.get("publisher_platforms") or data.get("publisherPlatforms") or []
        if isinstance(platforms, str):
            platforms = [platforms]

        # Determine active status - None when field isn't present in data
        is_active = data.get("is_active") or data.get("isActive")
        if is_active is None:
            ad_status_val = data.get("ad_status") or data.get("adStatus")
            if ad_status_val:
                is_active = ad_status_val == "ACTIVE"

        return cls(
            id=str(data.get("id") or data.get("adArchiveID") or data.get("ad_archive_id", "")),
            ad_library_id=data.get("adLibraryID") or data.get("ad_library_id"),
            page=page,
            is_active=is_active,
            ad_status=data.get("ad_status") or data.get("adStatus"),
            delivery_start_time=delivery_start,
            delivery_stop_time=delivery_stop,
            creatives=creatives,
            snapshot_url=data.get("snapshot_url") or data.get("snapshotUrl"),
            ad_snapshot_url=data.get("ad_snapshot_url") or data.get("adSnapshotUrl"),
            impressions=impressions,
            spend=spend,
            currency=data.get("currency"),
            age_gender_distribution=age_gender_dist,
            region_distribution=region_dist,
            estimated_audience_size_lower=data.get("estimated_audience_size", {}).get("lower_bound") if data.get("estimated_audience_size") else None,
            estimated_audience_size_upper=data.get("estimated_audience_size", {}).get("upper_bound") if data.get("estimated_audience_size") else None,
            publisher_platforms=platforms,
            languages=data.get("languages") or [],
            bylines=data.get("bylines") or [],
            funding_entity=data.get("funding_entity") or data.get("fundingEntity"),
            disclaimer=data.get("disclaimer"),
            ad_type=data.get("ad_type") or data.get("adType"),
            categories=data.get("categories") or [],
            beneficiary_payers=data.get("beneficiary_payers") or data.get("beneficiaryPayers") or [],
            collation_id=data.get("collation_id") or data.get("collationID"),
            collation_count=data.get("collation_count") or data.get("collationCount"),
            raw_data=data,
        )


@dataclass
class SearchResult:
    """Represents a paginated search result from the Ad Library"""
    ads: List[Ad]
    total_count: Optional[int] = None
    has_next_page: bool = False
    end_cursor: Optional[str] = None
    search_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ads": [ad.to_dict() for ad in self.ads],
            "total_count": self.total_count,
            "has_next_page": self.has_next_page,
            "end_cursor": self.end_cursor,
            "search_id": self.search_id,
        }
