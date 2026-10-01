"""Data models for Meta Ads Library"""

from __future__ import annotations

import json
import re as _re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    """Return the first key whose value is not None (preserving False/0)."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _numeric_bound(value: Any) -> int | None:
    """Normalize numeric API bounds while treating malformed values as absent."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            try:
                return int(value)
            except ValueError:
                pass
        number = float(value)
        return int(number) if number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    """Parse epoch and ISO dates consistently as UTC instants.

    Naive ISO values are interpreted as UTC because Meta date strings and Unix
    timestamps represent absolute delivery times, not machine-local times.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        if isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    return None


def _as_list(value: Any) -> list[Any]:
    """Normalize a scalar-or-list API value without dropping falsey members."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


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

    # Useful fields present in current Ad Library payloads. `api_fields`
    # below remains the lossless source for every other known or future key.
    ad_id: str | None = None
    display_format: str | None = None
    country_iso_code: str | None = None
    targeted_or_reached_countries: Any = None
    total_active_time: Any = None
    regional_regulation_data: Any = None
    additional_info: Any = None
    ec_certificates: Any = None
    brazil_tax_id: Any = None
    page_is_deleted: bool | None = None
    contains_sensitive_content: bool | None = None
    contains_digital_created_media: bool | None = None
    is_aaa_eligible: bool | None = None
    branded_content: Any = None
    event: Any = None
    has_user_reported: bool | None = None
    report_count: Any = None
    state_media_run_label: Any = None
    hide_data_status: str | None = None
    gated_type: str | None = None
    menu_items: Any = None
    is_reshared: bool | None = None
    root_reshared_post: Any = None
    fev_info: Any = None

    # Metadata
    collation_id: str | None = None
    collation_count: int | None = None

    # Raw data for debugging/extensibility
    raw_data: dict[str, Any] | None = field(default=None, repr=False)

    # Collection metadata
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    collection_source: str = "meta_ads_library"

    @property
    def api_fields(self) -> dict[str, Any] | None:
        """Return an isolated copy of all fields supplied in the API payload."""
        return deepcopy(self.raw_data)

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
            } if (
                self.estimated_audience_size_lower is not None
                or self.estimated_audience_size_upper is not None
            ) else None,
            "publisher_platforms": self.publisher_platforms,
            "languages": self.languages,
            "bylines": self.bylines,
            "funding_entity": self.funding_entity,
            "disclaimer": self.disclaimer,
            "ad_type": self.ad_type,
            "categories": self.categories,
            "beneficiary_payers": self.beneficiary_payers,
            "ad_id": self.ad_id,
            "display_format": self.display_format,
            "country_iso_code": self.country_iso_code,
            "targeted_or_reached_countries": self.targeted_or_reached_countries,
            "total_active_time": self.total_active_time,
            "regional_regulation_data": self.regional_regulation_data,
            "additional_info": self.additional_info,
            "ec_certificates": self.ec_certificates,
            "brazil_tax_id": self.brazil_tax_id,
            "page_is_deleted": self.page_is_deleted,
            "contains_sensitive_content": self.contains_sensitive_content,
            "contains_digital_created_media": self.contains_digital_created_media,
            "is_aaa_eligible": self.is_aaa_eligible,
            "branded_content": self.branded_content,
            "event": self.event,
            "has_user_reported": self.has_user_reported,
            "report_count": self.report_count,
            "state_media_run_label": self.state_media_run_label,
            "hide_data_status": self.hide_data_status,
            "gated_type": self.gated_type,
            "menu_items": self.menu_items,
            "is_reshared": self.is_reshared,
            "root_reshared_post": self.root_reshared_post,
            "fev_info": self.fev_info,
            "collation_id": self.collation_id,
            "collation_count": self.collation_count,
            "collected_at": self.collected_at.isoformat(),
            "collection_source": self.collection_source,
        }

        if self.raw_data is not None:
            result["api_fields"] = self.api_fields

        if include_raw and self.raw_data is not None:
            result["raw_data"] = deepcopy(self.raw_data)

        return result

    def to_json(self, include_raw: bool = False, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(include_raw=include_raw), indent=indent, ensure_ascii=False)

    @classmethod
    def _parse_reach(cls, data: dict[str, Any]) -> ImpressionRange | None:
        """Parse reach data from various API formats."""
        reach_data = _first_present(data, "reach", "reach_estimate")
        if reach_data is None:
            return None
        if isinstance(reach_data, str):
            lower, upper = _parse_impression_text(reach_data)
            return ImpressionRange(lower_bound=lower, upper_bound=upper)
        if isinstance(reach_data, dict):
            lower = _numeric_bound(_first_present(reach_data, "lower_bound", "lowerBound"))
            upper = _numeric_bound(_first_present(reach_data, "upper_bound", "upperBound"))
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

    @staticmethod
    def _parse_targeting(data: dict[str, Any]) -> TargetingInfo | None:
        """Normalize targeting fields only when Meta actually supplies them."""
        raw = _first_present(data, "targeting", "targeting_info", "targetingInfo")
        if not isinstance(raw, dict):
            return None

        def values(*keys: str) -> list[str]:
            value = _first_present(raw, *keys)
            if value is None:
                return []
            if not isinstance(value, (list, tuple)):
                value = [value]
            normalized: list[str] = []
            for entry in value:
                if isinstance(entry, str):
                    normalized.append(entry)
                elif isinstance(entry, (int, float)) and not isinstance(entry, bool):
                    normalized.append(str(entry))
                elif isinstance(entry, dict):
                    label = _first_present(entry, "name", "label", "key", "country", "region")
                    if label is not None:
                        normalized.append(str(label))
            return normalized

        age_min = _numeric_bound(_first_present(raw, "age_min", "ageMin"))
        age_max = _numeric_bound(_first_present(raw, "age_max", "ageMax"))
        genders = values("genders", "gender")
        locations = values("locations", "location")
        location_types = values("location_types", "locationTypes")
        interests = values("interests", "interest")
        excluded = values("excluded_locations", "excludedLocations")
        if not any((age_min is not None, age_max is not None, genders, locations,
                    location_types, interests, excluded)):
            return None
        return TargetingInfo(age_min, age_max, genders, locations,
                             location_types, interests, excluded)

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
        # Some search rows keep creative fields only in `snapshot`; use a
        # working overlay for normalization while retaining the input payload
        # byte-for-byte at the JSON-value level in raw_data/api_fields.
        original_data = data
        data = deepcopy(data)
        snapshot_overlay = data.get("snapshot")
        if isinstance(snapshot_overlay, dict):
            for key, value in snapshot_overlay.items():
                current = data.get(key)
                if key not in data or current is None or current == "" or current == [] or current == {}:
                    data[key] = deepcopy(value)

        # ── Extract page info ───────────────────────────────────────
        # Can be in a nested ``page`` object or flat fields at top level
        page_data = _first_present(data, "page", "pageInfo")
        if isinstance(page_data, dict) and page_data:
            page = PageInfo(
                id=page_data.get("id", ""),
                name=page_data.get("name", ""),
                profile_picture_url=(
                    page_data.get("profile_picture", {}).get("uri")
                    if isinstance(page_data.get("profile_picture"), dict) else None
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
        cards_value = data.get("cards")
        cards = [card for card in cards_value if isinstance(card, dict)] if isinstance(cards_value, list) else []

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
                videos_value = data.get("videos")
                images_value = data.get("images")
                videos = [v for v in videos_value if isinstance(v, dict)] if isinstance(videos_value, list) else []
                images = [v for v in images_value if isinstance(v, dict)] if isinstance(images_value, list) else []
                media_count = max(len(videos), len(images), 1)
                for i in range(media_count):
                    video = videos[i] if i < len(videos) else {}
                    image = images[i] if i < len(images) else {}
                    video_hd = video.get("video_hd_url")
                    video_sd = video.get("video_sd_url")
                    creatives.append(AdCreative(
                        body=cls._extract_body_text(data.get("body")),
                        caption=data.get("caption"),
                        description=data.get("link_description"),
                        title=data.get("title"),
                        link_url=data.get("link_url"),
                        image_url=(image.get("original_image_url") or image.get("resized_image_url")),
                        video_url=video_hd or video_sd,
                        video_hd_url=video_hd,
                        video_sd_url=video_sd,
                        thumbnail_url=video.get("video_preview_image_url"),
                        cta_text=data.get("cta_text"),
                        cta_type=data.get("cta_type"),
                    ))
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
                        snap_cards_value = snapshot.get("cards") if isinstance(snapshot, dict) else []
                        snap_cards = (
                            [item for item in snap_cards_value if isinstance(item, dict)]
                            if isinstance(snap_cards_value, list) else []
                        )
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
        start_time = _first_present(
            data, "ad_delivery_start_time", "startDate", "start_date"
        )
        stop_time = _first_present(
            data, "ad_delivery_stop_time", "endDate", "end_date"
        )
        delivery_start = _parse_datetime(start_time)
        delivery_stop = _parse_datetime(stop_time)

        # Parse impressions
        impressions = None
        imp_data = _first_present(
            data, "impressions", "impressionsWithIndex", "impressions_with_index"
        )
        if imp_data is not None:
            if isinstance(imp_data, str):
                lower, upper = _parse_impression_text(imp_data)
                impressions = ImpressionRange(lower_bound=lower, upper_bound=upper)
            elif isinstance(imp_data, dict):
                # Standard format: {lower_bound, upper_bound}
                lower = _numeric_bound(_first_present(imp_data, "lower_bound", "lowerBound"))
                upper = _numeric_bound(_first_present(imp_data, "upper_bound", "upperBound"))
                # Alternative format: {impressions_text, impressions_index}
                if lower is None and upper is None:
                    imp_text = imp_data.get("impressions_text") or imp_data.get("impressionsText")
                    if imp_text:
                        lower, upper = _parse_impression_text(str(imp_text))
                impressions = ImpressionRange(lower_bound=lower, upper_bound=upper)

        # Parse spend
        spend = None
        spend_data = _first_present(data, "spend", "spendWithIndex")
        if spend_data is not None:
            if isinstance(spend_data, str):
                lower, upper = _parse_spend_string(spend_data)
                spend = SpendRange(
                    lower_bound=lower,
                    upper_bound=upper,
                    currency=data.get("currency"),
                )
            elif isinstance(spend_data, dict):
                spend = SpendRange(
                    lower_bound=_numeric_bound(_first_present(spend_data, "lower_bound", "lowerBound")),
                    upper_bound=_numeric_bound(_first_present(spend_data, "upper_bound", "upperBound")),
                    currency=data.get("currency"),
                )

        # Parse demographic distribution
        age_gender_dist = []
        demo_data = data.get("demographic_distribution") or data.get("demographicDistribution") or []
        for item in demo_data:
            if not isinstance(item, dict):
                continue
            try:
                percentage = item.get("percentage")
                if percentage is None:
                    continue
                age_gender_dist.append(AudienceDistribution(
                    category=f"{item.get('age', 'unknown')}_{item.get('gender', 'unknown')}",
                    percentage=float(percentage),
                ))
            except (TypeError, ValueError, OverflowError):
                continue

        # Parse region distribution
        region_dist = []
        region_data = data.get("delivery_by_region") or data.get("deliveryByRegion") or []
        for item in region_data:
            if not isinstance(item, dict):
                continue
            try:
                percentage = item.get("percentage")
                if percentage is None:
                    continue
                region_dist.append(AudienceDistribution(
                    category=str(item.get("region", "unknown")),
                    percentage=float(percentage),
                ))
            except (TypeError, ValueError, OverflowError):
                continue

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
        is_active = _first_present(data, "is_active", "isActive")
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
            targeting=cls._parse_targeting(data),
            estimated_audience_size_lower=(
                _numeric_bound(_first_present(data.get("estimated_audience_size", {}), "lower_bound", "lowerBound"))
                if isinstance(data.get("estimated_audience_size"), dict) else None
            ),
            estimated_audience_size_upper=(
                _numeric_bound(_first_present(data.get("estimated_audience_size", {}), "upper_bound", "upperBound"))
                if isinstance(data.get("estimated_audience_size"), dict) else None
            ),
            publisher_platforms=platforms,
            languages=data.get("languages") or [],
            bylines=(
                _as_list(_first_present(data, "bylines", "byline"))
                if _first_present(data, "bylines", "byline") not in (None, "") else []
            ),
            funding_entity=data.get("funding_entity") or data.get("fundingEntity"),
            disclaimer=_first_present(data, "disclaimer", "disclaimer_label", "disclaimerLabel"),
            ad_type=data.get("ad_type") or data.get("adType"),
            categories=data.get("categories") or page_categories,
            beneficiary_payers=data.get("beneficiary_payers") or data.get("beneficiaryPayers") or [],
            collation_id=_first_present(data, "collation_id", "collationID"),
            collation_count=_numeric_bound(_first_present(data, "collation_count", "collationCount")),
            ad_id=(
                str(_first_present(data, "ad_id", "adID"))
                if _first_present(data, "ad_id", "adID") is not None else None
            ),
            display_format=_first_present(data, "display_format", "displayFormat"),
            country_iso_code=_first_present(data, "country_iso_code", "countryIsoCode"),
            targeted_or_reached_countries=deepcopy(_first_present(
                data, "targeted_or_reached_countries", "targetedOrReachedCountries"
            )),
            total_active_time=deepcopy(_first_present(data, "total_active_time", "totalActiveTime")),
            regional_regulation_data=deepcopy(_first_present(
                data, "regional_regulation_data", "regionalRegulationData"
            )),
            additional_info=deepcopy(_first_present(data, "additional_info", "additionalInfo")),
            ec_certificates=deepcopy(_first_present(data, "ec_certificates", "ecCertificates")),
            brazil_tax_id=deepcopy(_first_present(data, "brazil_tax_id", "brazilTaxId")),
            page_is_deleted=_first_present(data, "page_is_deleted", "pageIsDeleted"),
            contains_sensitive_content=_first_present(
                data, "contains_sensitive_content", "containsSensitiveContent"
            ),
            contains_digital_created_media=_first_present(
                data, "contains_digital_created_media", "containsDigitalCreatedMedia"
            ),
            is_aaa_eligible=_first_present(data, "is_aaa_eligible", "isAaaEligible"),
            branded_content=deepcopy(_first_present(data, "branded_content", "brandedContent")),
            event=deepcopy(_first_present(data, "event")),
            has_user_reported=_first_present(data, "has_user_reported", "hasUserReported"),
            report_count=deepcopy(_first_present(data, "report_count", "reportCount")),
            state_media_run_label=deepcopy(_first_present(
                data, "state_media_run_label", "stateMediaRunLabel"
            )),
            hide_data_status=_first_present(data, "hide_data_status", "hideDataStatus"),
            gated_type=_first_present(data, "gated_type", "gatedType"),
            menu_items=deepcopy(_first_present(data, "menu_items", "menuItems")),
            is_reshared=_first_present(data, "is_reshared", "isReshared"),
            root_reshared_post=deepcopy(_first_present(
                data, "root_reshared_post", "rootResharedPost"
            )),
            fev_info=deepcopy(_first_present(data, "fev_info", "fevInfo")),
            raw_data=deepcopy(original_data),
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
