"""Shared test fixtures for meta_ads_collector tests.

Provides both unit-test fixtures (sample data, mock objects) and
integration-test fixtures (real client, real collected ads).

Integration tests are gated by either:
  - The ``--run-integration`` pytest flag, or
  - The ``RUN_INTEGRATION_TESTS=1`` environment variable.

When neither is set, tests marked with ``@pytest.mark.integration``
are automatically skipped.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pytest

from meta_ads_collector.models import (
    Ad,
    AdCreative,
    AudienceDistribution,
    ImpressionRange,
    PageInfo,
    SpendRange,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Integration test gating
# ---------------------------------------------------------------------------

def pytest_addoption(parser: Any) -> None:
    """Register the ``--run-integration`` CLI flag."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that hit real Meta API servers.",
    )


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Auto-skip tests marked ``@pytest.mark.integration`` unless opted in."""
    run_flag = config.getoption("--run-integration", default=False)
    env_flag = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

    if run_flag or env_flag:
        # Integration tests enabled -- do not skip
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "Integration tests require --run-integration flag or "
            "RUN_INTEGRATION_TESTS=1 environment variable."
        )
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# Session-scoped integration fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def real_client():
    """Session-scoped fixture: a real MetaAdsClient initialized once.

    Only created when integration tests are enabled.  Shared across all
    integration tests in the session to minimize API calls.
    """
    from meta_ads_collector.client import MetaAdsClient

    client = MetaAdsClient(timeout=45, max_retries=3)
    client.initialize()
    yield client
    client.close()


@pytest.fixture(scope="session")
def collected_ads() -> list[Ad]:
    """Session-scoped fixture: 10-20 real ads from a 'coca cola' search.

    Collected once per test session and shared across all tests that
    need real Ad objects (export tests, stats tests, etc.).  This
    avoids redundant API calls.
    """
    from meta_ads_collector.collector import MetaAdsCollector

    collector = MetaAdsCollector(rate_limit_delay=1.0, jitter=0.5, timeout=45)
    ads: list[Ad] = []
    try:
        for ad in collector.search(
            query="coca cola",
            country="US",
            max_results=15,
            page_size=10,
        ):
            ads.append(ad)
            if len(ads) >= 15:
                break
    except Exception as exc:
        logger.warning("Failed to collect ads for session fixture: %s", exc)
    finally:
        collector.close()

    if not ads:
        pytest.skip(
            "Could not collect any ads from Meta API. "
            "Network may be unavailable or API may have changed."
        )

    return ads


# ---------------------------------------------------------------------------
# Unit test fixtures (no network required)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_graphql_ad_data() -> dict[str, Any]:
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
def sample_ad() -> Ad:
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
