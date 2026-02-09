"""Client-side filtering for Meta Ad Library results.

Provides a :class:`FilterConfig` dataclass to express ad filters and a
:func:`passes_filter` function that tests an :class:`~meta_ads_collector.models.Ad`
against the configured criteria.  All criteria use AND logic -- an ad
must satisfy every configured filter to pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .models import Ad

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """Configuration for client-side ad filtering.

    Every field defaults to ``None`` (disabled).  When a filter field is
    set, the ad must satisfy it to pass.  All enabled filters are ANDed
    together: an ad passes only if it satisfies *every* non-None criterion.

    Impression / spend logic:
        For range-based fields (impressions, spend) the ad model stores
        ``lower_bound`` and ``upper_bound``.  We use a conservative
        approach:

        * ``min_impressions`` passes if the ad's ``upper_bound >= min``
          (the ad *could* have at least that many impressions).
        * ``max_impressions`` passes if the ad's ``lower_bound <= max``
          (the ad *could* have at most that many impressions).

        The same logic applies to spend filters.

    Missing data policy:
        If a filter is set but the ad lacks the corresponding data
        (e.g. ``min_impressions=1000`` but ``ad.impressions is None``),
        the ad is **included** (passes the filter).  Rationale: excluding
        ads with missing data would silently drop results; users who want
        strict filtering can post-process.
    """

    min_impressions: int | None = None
    max_impressions: int | None = None
    min_spend: int | None = None
    max_spend: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    media_type: str | None = None
    publisher_platforms: list[str] | None = field(default=None)
    languages: list[str] | None = field(default=None)
    has_video: bool | None = None
    has_image: bool | None = None

    def is_empty(self) -> bool:
        """Return ``True`` when no filters are configured."""
        return all(
            getattr(self, f.name) is None
            for f in self.__dataclass_fields__.values()
        )


def passes_filter(ad: Ad, config: FilterConfig) -> bool:
    """Test whether *ad* passes all criteria in *config*.

    Args:
        ad: The ad to test.
        config: Filter configuration.

    Returns:
        ``True`` if the ad satisfies every enabled filter (or no filters
        are enabled).
    """
    # Fast path: no filters configured
    if config.is_empty():
        return True

    # -- Impression filters --
    # If impressions data is missing, include the ad (missing data policy)
    if (
        config.min_impressions is not None
        and ad.impressions is not None
        and ad.impressions.upper_bound is not None
        and ad.impressions.upper_bound < config.min_impressions
    ):
        return False

    if (
        config.max_impressions is not None
        and ad.impressions is not None
        and ad.impressions.lower_bound is not None
        and ad.impressions.lower_bound > config.max_impressions
    ):
        return False

    # -- Spend filters --
    if (
        config.min_spend is not None
        and ad.spend is not None
        and ad.spend.upper_bound is not None
        and ad.spend.upper_bound < config.min_spend
    ):
        return False

    if (
        config.max_spend is not None
        and ad.spend is not None
        and ad.spend.lower_bound is not None
        and ad.spend.lower_bound > config.max_spend
    ):
        return False

    # -- Date filters --
    # start_date: ad must have started on or after this date
    if config.start_date is not None and ad.delivery_start_time is not None:
        ad_start = _strip_tz(ad.delivery_start_time)
        filter_start = _strip_tz(config.start_date)
        if ad_start < filter_start:
            return False

    # end_date: ad must have started on or before this date
    if config.end_date is not None and ad.delivery_start_time is not None:
        ad_start = _strip_tz(ad.delivery_start_time)
        filter_end = _strip_tz(config.end_date)
        if ad_start > filter_end:
            return False

    # -- Media type filter --
    if config.media_type is not None:
        media_upper = config.media_type.upper()
        if media_upper != "ALL":
            ad_has_vid = _ad_has_video(ad)
            ad_has_img = _ad_has_image(ad)
            if media_upper == "VIDEO" and not ad_has_vid:
                return False
            if media_upper == "IMAGE" and not ad_has_img:
                return False
            if media_upper == "MEME" and not ad_has_img:
                return False
            if media_upper == "NONE" and (ad_has_vid or ad_has_img):
                return False

    # -- Publisher platform filter --
    if config.publisher_platforms is not None:
        requested = {p.lower() for p in config.publisher_platforms}
        if ad.publisher_platforms:
            ad_platforms = {p.lower() for p in ad.publisher_platforms}
            if not requested.intersection(ad_platforms):
                return False
        # Missing platforms data -> include

    # -- Language filter --
    if config.languages is not None:
        requested_langs = {lang.lower() for lang in config.languages}
        if ad.languages:
            ad_langs = {lang.lower() for lang in ad.languages}
            if not requested_langs.intersection(ad_langs):
                return False
        # Missing languages -> include

    # -- has_video filter --
    if config.has_video is not None:
        if config.has_video and not _ad_has_video(ad):
            return False
        if not config.has_video and _ad_has_video(ad):
            return False

    # -- has_image filter --
    if config.has_image is not None:
        if config.has_image and not _ad_has_image(ad):
            return False
        if not config.has_image and _ad_has_image(ad):
            return False

    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_tz(dt: datetime) -> datetime:
    """Return a naive datetime (drop timezone info for comparison)."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _ad_has_video(ad: Ad) -> bool:
    """Return ``True`` if any creative in the ad contains a video URL."""
    if any(
        creative.video_url or creative.video_hd_url or creative.video_sd_url
        for creative in ad.creatives
    ):
        return True
    # Also check raw_data for top-level videos array
    return bool(ad.raw_data and ad.raw_data.get("videos"))


def _ad_has_image(ad: Ad) -> bool:
    """Return ``True`` if any creative in the ad contains an image URL."""
    if any(
        creative.image_url or creative.thumbnail_url
        for creative in ad.creatives
    ):
        return True
    # Also check raw_data for top-level images array
    return bool(ad.raw_data and ad.raw_data.get("images"))
