"""Shared test fixtures for meta_ads_collector tests."""

import pytest

from meta_ads_collector.models import (
    Ad,
    AdCreative,
    AudienceDistribution,
    ImpressionRange,
    PageInfo,
    SpendRange,
)


@pytest.fixture
def sample_graphql_ad_data():
    """Minimal GraphQL ad response data matching the flattened structure."""
    return {
        "ad_archive_id": "12345",
        "collation_id": "c-001",
        "collation_count": 1,
        "page_id": "pg-99",
        "page": {
            "id": "pg-99",
            "name": "Test Page",
            "url": "https://facebook.com/testpage",
            "profile_picture": {"uri": "https://example.com/pic.jpg"},
        },
        "is_active": True,
        "ad_status": "ACTIVE",
        "ad_delivery_start_time": 1700000000,
        "cards": [
            {
                "body": "Buy our product!",
                "title": "Great Deal",
                "link_description": "Limited time offer",
                "link_url": "https://example.com",
                "resized_image_url": "https://example.com/img.jpg",
                "cta_text": "Shop Now",
                "cta_type": "SHOP_NOW",
            }
        ],
        "impressions": {"lower_bound": 1000, "upper_bound": 5000},
        "spend": {"lower_bound": 100, "upper_bound": 500},
        "currency": "USD",
        "publisher_platforms": ["facebook", "instagram"],
        "languages": ["en"],
        "demographic_distribution": [
            {"age": "25-34", "gender": "male", "percentage": 0.35},
        ],
        "delivery_by_region": [
            {"region": "California", "percentage": 0.20},
        ],
    }


@pytest.fixture
def sample_ad():
    """A fully populated Ad object for testing serialization."""
    return Ad(
        id="12345",
        page=PageInfo(
            id="pg-99",
            name="Test Page",
            profile_picture_url="https://example.com/pic.jpg",
            page_url="https://facebook.com/testpage",
        ),
        is_active=True,
        ad_status="ACTIVE",
        creatives=[
            AdCreative(
                body="Buy our product!",
                title="Great Deal",
                description="Limited time offer",
                link_url="https://example.com",
                image_url="https://example.com/img.jpg",
                cta_text="Shop Now",
            )
        ],
        impressions=ImpressionRange(lower_bound=1000, upper_bound=5000),
        spend=SpendRange(lower_bound=100, upper_bound=500, currency="USD"),
        currency="USD",
        publisher_platforms=["facebook", "instagram"],
        languages=["en"],
        age_gender_distribution=[
            AudienceDistribution(category="25-34_male", percentage=0.35),
        ],
        region_distribution=[
            AudienceDistribution(category="California", percentage=0.20),
        ],
    )
