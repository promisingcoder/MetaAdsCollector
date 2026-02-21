"""Data models for Meta Ads Library"""

from __future__ import annotations

import json
import re as _re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _parse_spend_string(text: str) -> tuple[int | None, int | None]:
    """Parse a spend string like '$9K-$10K' into (lower, upper) ints."""
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    parts = _re.findall(r'[\d,.]+[KMB]?', text)
    values: list[int] = []
    for part in parts:
        suffix = part[-1].upper() if part[-1].upper() in multipliers else ""
        num_str = part[:-1] if suffix else part
        num_str = num_str.replace(",", "")
        try:
            num = float(num_str)
            if suffix:
                num *= multipliers[suffix]
            values.append(int(num))
        except ValueError:
            continue
    if len(values) >= 2:
        return values[0], values[1]
    if len(values) == 1:
        return values[0], values[0]
    return None, None


def _parse_impression_text(text: str) -> tuple[int | None, int | None]:
    """Parse an impression text like '>1M' or '1K-5K' into (lower, upper)."""
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    parts = _re.findall(r'[\d,.]+[KMB]?', text)
    values: list[int] = []
    for part in parts:
        suffix = part[-1].upper() if part[-1].upper() in multipliers else ""
        num_str = part[:-1] if suffix else part
        num_str = num_str.replace(",", "")
        try:
            num = float(num_str)
            if suffix:
                num *= multipliers[suffix]
            values.append(int(num))
        except ValueError:
            continue
    if len(values) >= 2:
        return values[0], values[1]
    if len(values) == 1:
        # ">1M" means lower=1M, upper=None
        return values[0], None
    return None, None


@dataclass
class SpendRange:
    """Represents ad spend range"""
    lower_bound: int | None = None
    upper_bound: int | None = None
    currency: str | None = None

    def __str__(self) -> str:
        if self.lower_bound is not None and self.upper_bound is not None:
            return f"{self.currency} {self.lower_bound:,} - {self.upper_bound:,}"
        return "N/A"


@dataclass
class ImpressionRange:
    """Represents impression count range"""
    lower_bound: int | None = None
    upper_bound: int | None = None

    def __str__(self) -> str:
        if self.lower_bound is not None and self.upper_bound is not None:
            return f"{self.lower_bound:,} - {self.upper_bound:,}"
        return "N/A"


@dataclass
class AudienceDistribution:
    """Demographic or geographic distribution data"""
    category: str
    percentage: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdCreative:
    """Ad creative content - text, media, links"""
    body: str | None = None
    caption: str | None = None
    description: str | None = None
    title: str | None = None
    link_url: str | None = None
    image_url: str | None = None
    video_url: str | None = None
    video_hd_url: str | None = None
    video_sd_url: str | None = None
    thumbnail_url: str | None = None
    cta_text: str | None = None
    cta_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PageInfo:
    """Information about the page running the ad"""
    id: str
    name: str
    profile_picture_url: str | None = None
    page_url: str | None = None
    likes: int | None = None
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageSearchResult:
    """Result from a typeahead page search in the Ad Library.

    Returned by the typeahead endpoint when searching for pages by name.
    Contains page identification data needed to collect ads for a specific page.
    """
    page_id: str
    page_name: str
    page_profile_uri: str | None = None
    page_alias: str | None = None
    page_logo_url: str | None = None
    page_verified: bool | None = None
    page_like_count: int | None = None
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class TargetingInfo:
    """Ad targeting information"""
    age_min: int | None = None
    age_max: int | None = None
    genders: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    location_types: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    excluded_locations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
    ad_library_id: str | None = None

    # Page information
    page: PageInfo | None = None

    # Ad status and timing
    is_active: bool | None = None  # None when status unknown from search results
    ad_status: str | None = None  # ACTIVE, INACTIVE, etc.
    delivery_start_time: datetime | None = None
    delivery_stop_time: datetime | None = None

    # Creative content (can have multiple variations)
    creatives: list[AdCreative] = field(default_factory=list)

    # Snapshot and preview
    snapshot_url: str | None = None
    ad_snapshot_url: str | None = None

    # Performance metrics
    impressions: ImpressionRange | None = None
    spend: SpendRange | None = None
    reach: ImpressionRange | None = None
    currency: str | None = None

    # Audience demographics
    age_gender_distribution: list[AudienceDistribution] = field(default_factory=list)
    region_distribution: list[AudienceDistribution] = field(default_factory=list)

    # Targeting
    targeting: TargetingInfo | None = None
    estimated_audience_size_lower: int | None = None
    estimated_audience_size_upper: int | None = None

    # Platform and placement
    publisher_platforms: list[str] = field(default_factory=list)  # facebook, instagram, messenger, audience_network

    # Languages
    languages: list[str] = field(default_factory=list)

    # Political/Issue ad specific fields
    bylines: list[str] = field(default_factory=list)
    funding_entity: str | None = None
    disclaimer: str | None = None

    # Categories
    ad_type: str | None = None  # POLITICAL_AND_ISSUE_ADS, HOUSING_ADS, etc.
    categories: list[str] = field(default_factory=list)

    # EU transparency fields
    beneficiary_payers: list[str] = field(default_factory=list)

    # Metadata
    collation_id: str | None = None
    collation_count: int | None = None

    # Raw data for debugging/extensibility
    raw_data: dict[str, Any] | None = field(default=None, repr=False)

    # Collection metadata
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    collection_source: str = "meta_ads_library"

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
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
    def _parse_reach(cls, data: dict[str, Any]) -> ImpressionRange | None:
        """Parse reach data from various API formats."""
        reach_data = data.get("reach") or data.get("reach_estimate") or {}
        if not reach_data:
            return None
        if isinstance(reach_data, str):
            lower, upper = _parse_impression_text(reach_data)
            return ImpressionRange(lower_bound=lower, upper_bound=upper)
        if isinstance(reach_data, dict):
            lower = reach_data.get("lower_bound") or reach_data.get("lowerBound")
            upper = reach_data.get("upper_bound") or reach_data.get("upperBound")
            if lower is None and upper is None:
                return None
            return ImpressionRange(lower_bound=lower, upper_bound=upper)
        return None

    @classmethod
    def _extract_body_text(cls, body_value: Any) -> str | None:
        """Extract body text from API response body field.

        The body can be either a plain string or a dict ``{"text": "..."}``
        depending on the API response format.

        Args:
            body_value: The raw ``body`` value from the response.

        Returns:
            The body text string, or ``None`` if not available.
        """
        if body_value is None:
            return None
        if isinstance(body_value, dict):
            return body_value.get("text")
        if isinstance(body_value, str):
            return body_value
        return None

    @classmethod
    def from_graphql_response(cls, data: dict[str, Any]) -> Ad:
        """
        Parse an ad from the Meta Ad Library GraphQL response.

        Handles multiple response formats:

        1. **Live API format** (primary): Flat top-level fields with
           ``body`` as ``{"text": "..."}`` dict, ``videos[]``,
           ``images[]``, and ``cards`` usually empty.
        2. **Cards format**: ``cards[]`` array containing creative
           content (carousel ads or older responses).
        3. **Legacy format**: ``ad_creative_bodies``,
           ``ad_creative_link_titles``, etc. arrays with optional
           ``snapshot.cards`` for media.
        """
        # ── Extract page info ───────────────────────────────────────
        # Can be in a nested ``page`` object or flat fields at top level
        page_data = data.get("page") or data.get("pageInfo") or {}
        if page_data:
            page = PageInfo(
                id=page_data.get("id", ""),
                name=page_data.get("name", ""),
                profile_picture_url=(
                    page_data.get("profile_picture", {}).get("uri")
                    if page_data.get("profile_picture") else None
                ),
                page_url=page_data.get("url"),
            )
        else:
            # Flat structure from live API search results
            page = PageInfo(
                id=data.get("page_id", ""),
                name=data.get("page_name", ""),
                profile_picture_url=data.get("page_profile_picture_url"),
                page_url=data.get("page_profile_uri"),
                likes=data.get("page_like_count"),
            )

        # Map page_categories to the Ad categories field when present
        page_categories = data.get("page_categories") or []

        # ── Parse creatives ─────────────────────────────────────────
        creatives: list[AdCreative] = []
        cards = data.get("cards") or []

        if cards:
            # Cards format: cards array contains creative content
            for card in cards:
                creative = AdCreative(
                    body=cls._extract_body_text(card.get("body")),
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
            # ── Primary path: live API flat format ──────────────────
            # The live API returns body, title, caption, link_url,
            # videos[], images[] as flat top-level fields.
            has_flat_fields = (
                data.get("body") is not None
                or data.get("title") is not None
                or data.get("videos") is not None
                or data.get("images") is not None
            )

            if has_flat_fields:
                # Extract media from top-level arrays
                videos = data.get("videos") or []
                images = data.get("images") or []
                first_video = videos[0] if videos else {}
                first_image = images[0] if images else {}

                video_hd = first_video.get("video_hd_url")
                video_sd = first_video.get("video_sd_url")
                video_url = video_hd or video_sd
                thumbnail = first_video.get("video_preview_image_url")
                image_url = (
                    first_image.get("original_image_url")
                    or first_image.get("resized_image_url")
                )

                creative = AdCreative(
                    body=cls._extract_body_text(data.get("body")),
                    caption=data.get("caption"),
                    description=data.get("link_description"),
                    title=data.get("title"),
                    link_url=data.get("link_url"),
                    image_url=image_url,
                    video_url=video_url,
                    video_hd_url=video_hd,
                    video_sd_url=video_sd,
                    thumbnail_url=thumbnail,
                    cta_text=data.get("cta_text"),
                    cta_type=data.get("cta_type"),
                )
                creatives.append(creative)
            else:
                # ── Legacy fallback: ad_creative_bodies arrays ──────
                bodies = data.get("ad_creative_bodies") or data.get("adCreativeBodies") or []
                link_captions = (
                    data.get("ad_creative_link_captions")
                    or data.get("adCreativeLinkCaptions") or []
                )
                link_descriptions = (
                    data.get("ad_creative_link_descriptions")
                    or data.get("adCreativeLinkDescriptions") or []
                )
                link_titles = (
                    data.get("ad_creative_link_titles")
                    or data.get("adCreativeLinkTitles") or []
                )

                max_creatives = max(len(bodies), len(link_titles), 1)
                for i in range(max_creatives):
                    creative = AdCreative(
                        body=bodies[i] if i < len(bodies) else None,
                        caption=link_captions[i] if i < len(link_captions) else None,
                        description=link_descriptions[i] if i < len(link_descriptions) else None,
                        title=link_titles[i] if i < len(link_titles) else None,
                    )
                    creatives.append(creative)

                # Parse snapshot/display images for legacy format
                snapshot = data.get("snapshot") or {}
                if snapshot:
                    for i, creative in enumerate(creatives):
                        snap_cards = snapshot.get("cards") or []
                        if i < len(snap_cards):
                            card = snap_cards[i]
                            creative.image_url = (
                                card.get("resized_image_url")
                                or card.get("original_image_url")
                            )
                            creative.video_url = (
                                card.get("video_hd_url")
                                or card.get("video_sd_url")
                            )
                            creative.video_hd_url = card.get("video_hd_url")
                            creative.video_sd_url = card.get("video_sd_url")
                            creative.link_url = card.get("link_url")
                            creative.cta_text = card.get("cta_text")
                            creative.cta_type = card.get("cta_type")

        # Parse dates
        delivery_start = None
        delivery_stop = None
        start_time = data.get("ad_delivery_start_time") or data.get("startDate") or data.get("start_date")
        stop_time = data.get("ad_delivery_stop_time") or data.get("endDate") or data.get("end_date")

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
        imp_data = (
            data.get("impressions")
            or data.get("impressionsWithIndex")
            or data.get("impressions_with_index")
            or {}
        )
        if imp_data:
            if isinstance(imp_data, str):
                lower, upper = _parse_impression_text(imp_data)
                impressions = ImpressionRange(lower_bound=lower, upper_bound=upper)
            elif isinstance(imp_data, dict):
                # Standard format: {lower_bound, upper_bound}
                lower = imp_data.get("lower_bound") or imp_data.get("lowerBound")
                upper = imp_data.get("upper_bound") or imp_data.get("upperBound")
                # Alternative format: {impressions_text, impressions_index}
                if lower is None and upper is None:
                    imp_text = imp_data.get("impressions_text") or imp_data.get("impressionsText")
                    if imp_text:
                        lower, upper = _parse_impression_text(str(imp_text))
                impressions = ImpressionRange(lower_bound=lower, upper_bound=upper)

        # Parse spend
        spend = None
        spend_data = data.get("spend") or data.get("spendWithIndex") or {}
        if spend_data:
            if isinstance(spend_data, str):
                lower, upper = _parse_spend_string(spend_data)
                spend = SpendRange(
                    lower_bound=lower,
                    upper_bound=upper,
                    currency=data.get("currency"),
                )
            elif isinstance(spend_data, dict):
                spend = SpendRange(
                    lower_bound=spend_data.get("lower_bound") or spend_data.get("lowerBound"),
                    upper_bound=spend_data.get("upper_bound") or spend_data.get("upperBound"),
                    currency=data.get("currency"),
                )

        # Parse demographic distribution
        age_gender_dist = []
        demo_data = data.get("demographic_distribution") or data.get("demographicDistribution") or []
        for item in demo_data:
            if not isinstance(item, dict):
                continue
            age_gender_dist.append(AudienceDistribution(
                category=f"{item.get('age', 'unknown')}_{item.get('gender', 'unknown')}",
                percentage=float(item.get("percentage", 0)),
            ))

        # Parse region distribution
        region_dist = []
        region_data = data.get("delivery_by_region") or data.get("deliveryByRegion") or []
        for item in region_data:
            if not isinstance(item, dict):
                continue
            region_dist.append(AudienceDistribution(
                category=item.get("region", "unknown"),
                percentage=float(item.get("percentage", 0)),
            ))

        # Parse publisher platforms (API uses both singular and plural keys)
        platforms = (
            data.get("publisher_platforms")
            or data.get("publisherPlatforms")
            or data.get("publisher_platform")
            or []
        )
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
            reach=cls._parse_reach(data),
            currency=data.get("currency"),
            age_gender_distribution=age_gender_dist,
            region_distribution=region_dist,
            estimated_audience_size_lower=(
                data.get("estimated_audience_size", {}).get("lower_bound")
                if isinstance(data.get("estimated_audience_size"), dict) else None
            ),
            estimated_audience_size_upper=(
                data.get("estimated_audience_size", {}).get("upper_bound")
                if isinstance(data.get("estimated_audience_size"), dict) else None
            ),
            publisher_platforms=platforms,
            languages=data.get("languages") or [],
            bylines=data.get("bylines") or [],
            funding_entity=data.get("funding_entity") or data.get("fundingEntity"),
            disclaimer=data.get("disclaimer"),
            ad_type=data.get("ad_type") or data.get("adType"),
            categories=data.get("categories") or page_categories,
            beneficiary_payers=data.get("beneficiary_payers") or data.get("beneficiaryPayers") or [],
            collation_id=data.get("collation_id") or data.get("collationID"),
            collation_count=data.get("collation_count") or data.get("collationCount"),
            raw_data=data,
        )


@dataclass
class SearchResult:
    """Represents a paginated search result from the Ad Library"""
    ads: list[Ad]
    total_count: int | None = None
    has_next_page: bool = False
    end_cursor: str | None = None
    search_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ads": [ad.to_dict() for ad in self.ads],
            "total_count": self.total_count,
            "has_next_page": self.has_next_page,
            "end_cursor": self.end_cursor,
            "search_id": self.search_id,
        }
