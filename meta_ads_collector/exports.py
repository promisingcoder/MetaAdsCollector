"""Shared flat CSV schema used by the CLI and both collectors.

JSON and JSONL exports carry every :class:`~meta_ads_collector.models.Ad`
field.  CSV cannot nest, so it exposes the most useful scalar fields as
columns and keeps the lossless Meta payload in the ``api_fields`` column.
"""

from __future__ import annotations

import json
from typing import Any

from .models import Ad

CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "page_id",
    "page_name",
    "page_url",
    "is_active",
    "ad_status",
    "delivery_start_time",
    "delivery_stop_time",
    "creative_body",
    "creative_title",
    "creative_description",
    "creative_link_url",
    "creative_image_url",
    "snapshot_url",
    "impressions_lower",
    "impressions_upper",
    "spend_lower",
    "spend_upper",
    "currency",
    "publisher_platforms",
    "languages",
    "funding_entity",
    "disclaimer",
    "ad_type",
    # Columns added in 1.7.0
    "creative_video_url",
    "cta_text",
    "cta_type",
    "display_format",
    "page_like_count",
    "page_categories",
    "categories",
    "bylines",
    "impressions_text",
    "reach_lower",
    "reach_upper",
    "eu_total_reach",
    "payer_beneficiary",
    "targeted_countries",
    "collation_id",
    "collation_count",
    "collected_at",
    "api_fields",
)


def _blank(value: Any) -> Any:
    return "" if value is None else value


def _joined(values: Any) -> str:
    if not isinstance(values, (list, tuple)):
        return "" if values is None else str(values)
    return ",".join(str(item) for item in values if item is not None)


def ad_to_csv_row(ad: Ad) -> dict[str, Any]:
    """Flatten one ad into a row keyed by :data:`CSV_COLUMNS`."""
    primary = ad.creatives[0] if ad.creatives else None
    page = ad.page
    return {
        "id": ad.id,
        "page_id": page.id if page else "",
        "page_name": page.name if page else "",
        "page_url": _blank(page.page_url) if page else "",
        "is_active": _blank(ad.is_active),
        "ad_status": ad.ad_status or "",
        "delivery_start_time": ad.delivery_start_time.isoformat() if ad.delivery_start_time else "",
        "delivery_stop_time": ad.delivery_stop_time.isoformat() if ad.delivery_stop_time else "",
        "creative_body": _blank(primary.body) if primary else "",
        "creative_title": _blank(primary.title) if primary else "",
        "creative_description": _blank(primary.description) if primary else "",
        "creative_link_url": _blank(primary.link_url) if primary else "",
        "creative_image_url": _blank(primary.image_url) if primary else "",
        "snapshot_url": ad.snapshot_url or ad.ad_snapshot_url or "",
        "impressions_lower": _blank(ad.impressions.lower_bound) if ad.impressions else "",
        "impressions_upper": _blank(ad.impressions.upper_bound) if ad.impressions else "",
        "spend_lower": _blank(ad.spend.lower_bound) if ad.spend else "",
        "spend_upper": _blank(ad.spend.upper_bound) if ad.spend else "",
        "currency": ad.currency or "",
        "publisher_platforms": _joined(ad.publisher_platforms),
        "languages": _joined(ad.languages),
        "funding_entity": ad.funding_entity or "",
        "disclaimer": ad.disclaimer or "",
        "ad_type": ad.ad_type or "",
        "creative_video_url": _blank(primary.video_url) if primary else "",
        "cta_text": _blank(primary.cta_text) if primary else "",
        "cta_type": _blank(primary.cta_type) if primary else "",
        "display_format": ad.display_format or "",
        "page_like_count": _blank(page.likes) if page else "",
        "page_categories": _joined(ad.page_categories),
        "categories": _joined(ad.categories),
        "bylines": _joined(ad.bylines),
        "impressions_text": ad.impressions_text or "",
        "reach_lower": _blank(ad.reach.lower_bound) if ad.reach else "",
        "reach_upper": _blank(ad.reach.upper_bound) if ad.reach else "",
        "eu_total_reach": _blank(ad.eu_total_reach),
        "payer_beneficiary": ";".join(
            f"{_blank(item.get('payer'))}|{_blank(item.get('beneficiary'))}"
            for item in ad.payer_beneficiary_data
            if isinstance(item, dict)
        ),
        "targeted_countries": _joined(ad.targeted_or_reached_countries),
        "collation_id": ad.collation_id or "",
        "collation_count": _blank(ad.collation_count),
        "collected_at": ad.collected_at.isoformat(),
        "api_fields": json.dumps(ad.api_fields, ensure_ascii=False),
    }
