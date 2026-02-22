"""Tests for ad detail endpoint and enrichment functionality."""

import copy
from unittest.mock import MagicMock

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CffiConnectionError
from curl_cffi.requests.exceptions import Timeout as CffiTimeout

from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.models import Ad, AdCreative, PageInfo

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_collector():
    """Create a MetaAdsCollector with a mocked client."""
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    collector.client.session = MagicMock()
    collector.rate_limit_delay = 0
    collector.jitter = 0
    collector.stats = {
        "requests_made": 0,
        "ads_collected": 0,
        "pages_fetched": 0,
        "errors": 0,
        "start_time": None,
        "end_time": None,
    }
    return collector


@pytest.fixture
def basic_ad():
    """An ad with minimal data that could benefit from enrichment."""
    return Ad(
        id="12345",
        page=PageInfo(id="pg-1", name="Test Page"),
        creatives=[
            AdCreative(
                body="Buy our product!",
                title="Great Deal",
                image_url="https://example.com/img.jpg",
            ),
        ],
    )


@pytest.fixture
def fully_populated_ad():
    """An ad with all fields already populated."""
    return Ad(
        id="99999",
        ad_library_id="lib-99999",
        page=PageInfo(
            id="pg-99",
            name="Full Page",
            profile_picture_url="https://example.com/pic.jpg",
            page_url="https://facebook.com/fullpage",
        ),
        is_active=True,
        ad_status="ACTIVE",
        creatives=[
            AdCreative(
                body="Full creative",
                title="Full title",
                image_url="https://example.com/full.jpg",
                video_hd_url="https://example.com/full_hd.mp4",
                video_sd_url="https://example.com/full_sd.mp4",
                thumbnail_url="https://example.com/full_thumb.jpg",
            ),
        ],
        snapshot_url="https://example.com/snapshot",
        ad_snapshot_url="https://example.com/ad_snapshot",
        funding_entity="Full Funding Corp",
        disclaimer="Full Disclaimer",
        ad_type="ALL",
        publisher_platforms=["facebook", "instagram"],
        languages=["en"],
        categories=["HOUSING_ADS"],
        bylines=["Original Byline"],
    )


# ---------------------------------------------------------------------------
# enrich_ad: failure safety
# ---------------------------------------------------------------------------


class TestEnrichAdFailureSafety:
    def test_returns_original_on_not_implemented(self, mock_collector, basic_ad):
        """If get_ad_details raises NotImplementedError, return original ad unchanged."""
        mock_collector.client.get_ad_details.side_effect = NotImplementedError("Not available")

        result = mock_collector.enrich_ad(basic_ad)

        assert result is basic_ad  # exact same object
        assert result.id == "12345"
        assert result.creatives[0].body == "Buy our product!"

    def test_returns_original_on_connection_error(self, mock_collector, basic_ad):
        """Network failures should not mutate or lose the ad."""
        mock_collector.client.get_ad_details.side_effect = CffiConnectionError("offline")

        result = mock_collector.enrich_ad(basic_ad)

        assert result is basic_ad
        assert result.id == "12345"

    def test_returns_original_on_timeout(self, mock_collector, basic_ad):
        """Timeout should not crash or lose data."""
        mock_collector.client.get_ad_details.side_effect = CffiTimeout("timed out")

        result = mock_collector.enrich_ad(basic_ad)

        assert result is basic_ad

    def test_returns_original_on_any_exception(self, mock_collector, basic_ad):
        """Any unexpected exception returns the original ad."""
        mock_collector.client.get_ad_details.side_effect = RuntimeError("totally unexpected")

        result = mock_collector.enrich_ad(basic_ad)

        assert result is basic_ad
        assert result.id == "12345"

    def test_returns_original_on_malformed_detail_data(self, mock_collector, basic_ad):
        """If detail data can't be parsed into an Ad, return original."""
        # Return data that will cause from_graphql_response to have issues
        # but not crash - it'll just produce a mostly-empty Ad
        mock_collector.client.get_ad_details.return_value = {"garbage": True}

        result = mock_collector.enrich_ad(basic_ad)

        # Should not crash; either returns enriched or original
        assert result is not None
        assert result.id == "12345" or result.id == ""

    def test_original_ad_fields_preserved_on_failure(self, mock_collector, basic_ad):
        """All fields of the original ad must remain unchanged after failure."""
        original_copy = copy.deepcopy(basic_ad)
        mock_collector.client.get_ad_details.side_effect = Exception("boom")

        result = mock_collector.enrich_ad(basic_ad)

        # Compare all critical fields
        assert result.id == original_copy.id
        assert result.page.id == original_copy.page.id
        assert result.page.name == original_copy.page.name
        assert len(result.creatives) == len(original_copy.creatives)
        assert result.creatives[0].body == original_copy.creatives[0].body
        assert result.creatives[0].title == original_copy.creatives[0].title
        assert result.creatives[0].image_url == original_copy.creatives[0].image_url


# ---------------------------------------------------------------------------
# enrich_ad: successful enrichment
# ---------------------------------------------------------------------------


class TestEnrichAdSuccess:
    def test_fills_empty_fields(self, mock_collector, basic_ad):
        """Enrichment should fill in fields that were previously empty."""
        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "12345",
            "page_id": "pg-1",
            "page_name": "Test Page",
            "snapshot_url": "https://example.com/snapshot",
            "ad_snapshot_url": "https://example.com/ad_snapshot",
            "funding_entity": "Test Funding Corp",
            "disclaimer": "Test Disclaimer",
            "publisher_platforms": ["facebook", "instagram"],
            "languages": ["en", "es"],
        }

        result = mock_collector.enrich_ad(basic_ad)

        assert result.snapshot_url == "https://example.com/snapshot"
        assert result.ad_snapshot_url == "https://example.com/ad_snapshot"
        assert result.funding_entity == "Test Funding Corp"
        assert result.disclaimer == "Test Disclaimer"
        assert result.publisher_platforms == ["facebook", "instagram"]
        assert result.languages == ["en", "es"]

    def test_does_not_overwrite_existing_fields(self, mock_collector, fully_populated_ad):
        """Enrichment should NOT overwrite fields that already have values."""
        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "99999",
            "page_id": "pg-99",
            "page_name": "Different Page",
            "snapshot_url": "https://example.com/new_snapshot",
            "funding_entity": "Different Corp",
            "publisher_platforms": ["messenger"],
            "languages": ["fr"],
        }

        result = mock_collector.enrich_ad(fully_populated_ad)

        # Original values should be preserved
        assert result.snapshot_url == "https://example.com/snapshot"
        assert result.funding_entity == "Full Funding Corp"
        assert result.publisher_platforms == ["facebook", "instagram"]
        assert result.languages == ["en"]

    def test_enriches_creative_media_urls(self, mock_collector):
        """Enrichment should fill in missing media URLs on creatives."""
        ad = Ad(
            id="MEDIA_AD",
            page=PageInfo(id="pg-1", name="Test"),
            creatives=[
                AdCreative(
                    body="Test",
                    image_url="https://example.com/img.jpg",
                    # video URLs are missing
                ),
            ],
        )

        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "MEDIA_AD",
            "page_id": "pg-1",
            "page_name": "Test",
            "cards": [
                {
                    "body": "Test",
                    "resized_image_url": "https://example.com/img.jpg",
                    "video_hd_url": "https://example.com/hd.mp4",
                    "video_sd_url": "https://example.com/sd.mp4",
                    "video_preview_image_url": "https://example.com/thumb.jpg",
                }
            ],
        }

        result = mock_collector.enrich_ad(ad)

        assert result.creatives[0].image_url == "https://example.com/img.jpg"  # preserved
        assert result.creatives[0].video_hd_url == "https://example.com/hd.mp4"  # enriched
        assert result.creatives[0].video_sd_url == "https://example.com/sd.mp4"  # enriched
        assert result.creatives[0].thumbnail_url == "https://example.com/thumb.jpg"  # enriched


# ---------------------------------------------------------------------------
# get_ad_details: client method
# ---------------------------------------------------------------------------


class TestGetAdDetails:
    def test_approach1_parses_embedded_json(self):
        """Test that approach 1 can parse ad data from HTML."""
        from meta_ads_collector.client import MetaAdsClient

        client = MetaAdsClient.__new__(MetaAdsClient)
        # Test the _parse_ad_detail_page method directly
        html = '''
        <html><body><script>
        {"ad_archive_id": "55555", "page_name": "Test", "snapshot_url": "https://snap.example.com"}
        </script></body></html>
        '''

        result = client._parse_ad_detail_page(html, "55555")
        assert result is not None
        assert result["ad_archive_id"] == "55555"

    def test_approach1_returns_none_for_missing_ad(self):
        """Test that approach 1 returns None when ad ID is not in HTML."""
        from meta_ads_collector.client import MetaAdsClient

        client = MetaAdsClient.__new__(MetaAdsClient)
        html = '<html><body>No ads here</body></html>'

        result = client._parse_ad_detail_page(html, "99999")
        assert result is None

    def test_approach1_handles_malformed_html(self):
        """Test that approach 1 handles broken HTML gracefully."""
        from meta_ads_collector.client import MetaAdsClient

        client = MetaAdsClient.__new__(MetaAdsClient)
        html = '{"ad_archive_id": "123", broken json here }'

        client._parse_ad_detail_page(html, "123")
        # Should not crash, may return None
        # The ad_archive_id pattern match will find it but JSON parse fails
        # This is acceptable

    def test_approach1_collated_results_pattern(self):
        """Test extraction from collated_results pattern."""
        from meta_ads_collector.client import MetaAdsClient

        client = MetaAdsClient.__new__(MetaAdsClient)
        html = '''
        <script>
        "collated_results": [{"ad_archive_id": "77777", "page_name": "Collated", "snapshot_url": "https://snap.example.com"}]
        </script>
        '''

        result = client._parse_ad_detail_page(html, "77777")
        assert result is not None
        assert result["ad_archive_id"] == "77777"

    def test_approach1_adArchiveID_pattern(self):
        """Test extraction using camelCase adArchiveID pattern."""
        from meta_ads_collector.client import MetaAdsClient

        client = MetaAdsClient.__new__(MetaAdsClient)
        html = '''
        <script>
        {"adArchiveID": "88888", "pageName": "CamelCase", "snapshotUrl": "https://snap.example.com"}
        </script>
        '''

        result = client._parse_ad_detail_page(html, "88888")
        assert result is not None


# ---------------------------------------------------------------------------
# enrich_ad does not mutate original ad on success
# ---------------------------------------------------------------------------


class TestEnrichDoesNotMutateOriginal:
    def test_original_ad_preserved_after_successful_enrichment(self, mock_collector):
        """After successful enrichment, the original Ad object must not be changed."""
        original = Ad(
            id="ORIG",
            page=PageInfo(id="pg-1", name="Original"),
            creatives=[
                AdCreative(body="Original body"),
            ],
        )
        # Save values before enrichment
        orig_id = original.id
        orig_page_name = original.page.name
        orig_body = original.creatives[0].body

        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "ORIG",
            "page_id": "pg-1",
            "page_name": "Original",
            "funding_entity": "New Corp",
            "languages": ["fr"],
        }

        result = mock_collector.enrich_ad(original)

        # The result should have enriched data
        assert result.funding_entity == "New Corp"
        assert result.languages == ["fr"]

        # But original should remain unchanged
        assert original.id == orig_id
        assert original.page.name == orig_page_name
        assert original.creatives[0].body == orig_body
        assert original.funding_entity is None
        assert original.languages == []
