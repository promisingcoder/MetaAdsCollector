"""Tests verifying enrich_ad uses deep copy so original Ad objects are never mutated.

Regression test for issue S9: copy.copy(ad) was a shallow copy, meaning
mutable fields like ``creatives`` (a list of AdCreative objects),
``publisher_platforms``, ``languages``, etc. were shared between the
original ad and the working copy.  When enrichment code mutated
``creative.image_url = e_creative.image_url``, it also mutated the
original ad's creative.

The fix changed ``copy.copy(ad)`` to ``copy.deepcopy(ad)`` in
``MetaAdsCollector.enrich_ad``.
"""

from unittest.mock import MagicMock

import pytest

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
def ad_with_creatives():
    """An Ad with creatives that have some media URLs missing."""
    return Ad(
        id="DEEPCOPY_TEST",
        page=PageInfo(id="pg-1", name="Test Page"),
        creatives=[
            AdCreative(
                body="Original body text",
                title="Original title",
                image_url=None,  # missing -- enrichment will fill this
                video_hd_url=None,  # missing
                video_sd_url=None,  # missing
                thumbnail_url=None,  # missing
            ),
            AdCreative(
                body="Second creative",
                title="Second title",
                image_url="https://example.com/existing.jpg",  # already present
                video_hd_url=None,  # missing
            ),
        ],
        publisher_platforms=["facebook"],
        languages=["en"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnrichAdDeepCopy:
    """Verify that enrich_ad deep-copies the ad so the original is never mutated."""

    def test_original_creatives_not_mutated_after_enrichment(
        self, mock_collector, ad_with_creatives
    ):
        """After enrichment fills in media URLs, the original ad's creatives
        must remain unchanged (issue S9 regression)."""
        # Capture original state before enrichment
        orig_creative0_image = ad_with_creatives.creatives[0].image_url
        orig_creative0_video_hd = ad_with_creatives.creatives[0].video_hd_url
        orig_creative0_video_sd = ad_with_creatives.creatives[0].video_sd_url
        orig_creative0_thumbnail = ad_with_creatives.creatives[0].thumbnail_url
        orig_creative1_image = ad_with_creatives.creatives[1].image_url
        orig_creative1_video_hd = ad_with_creatives.creatives[1].video_hd_url

        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "DEEPCOPY_TEST",
            "page_id": "pg-1",
            "page_name": "Test Page",
            "cards": [
                {
                    "body": "Original body text",
                    "title": "Original title",
                    "resized_image_url": "https://cdn.example.com/enriched_img.jpg",
                    "video_hd_url": "https://cdn.example.com/enriched_hd.mp4",
                    "video_sd_url": "https://cdn.example.com/enriched_sd.mp4",
                    "video_preview_image_url": "https://cdn.example.com/enriched_thumb.jpg",
                },
                {
                    "body": "Second creative",
                    "title": "Second title",
                    "resized_image_url": "https://cdn.example.com/enriched_img2.jpg",
                    "video_hd_url": "https://cdn.example.com/enriched_hd2.mp4",
                },
            ],
        }

        result = mock_collector.enrich_ad(ad_with_creatives)

        # -- The returned ad should have enriched media URLs --
        assert result.creatives[0].image_url == "https://cdn.example.com/enriched_img.jpg"
        assert result.creatives[0].video_hd_url == "https://cdn.example.com/enriched_hd.mp4"
        assert result.creatives[0].video_sd_url == "https://cdn.example.com/enriched_sd.mp4"
        assert result.creatives[0].thumbnail_url == "https://cdn.example.com/enriched_thumb.jpg"

        # Second creative: image_url already existed, so it should NOT be overwritten
        assert result.creatives[1].image_url == "https://example.com/existing.jpg"
        # But video_hd_url was missing and should be filled
        assert result.creatives[1].video_hd_url == "https://cdn.example.com/enriched_hd2.mp4"

        # -- The ORIGINAL ad must be completely unchanged --
        assert ad_with_creatives.creatives[0].image_url is orig_creative0_image
        assert ad_with_creatives.creatives[0].image_url is None
        assert ad_with_creatives.creatives[0].video_hd_url is orig_creative0_video_hd
        assert ad_with_creatives.creatives[0].video_hd_url is None
        assert ad_with_creatives.creatives[0].video_sd_url is orig_creative0_video_sd
        assert ad_with_creatives.creatives[0].video_sd_url is None
        assert ad_with_creatives.creatives[0].thumbnail_url is orig_creative0_thumbnail
        assert ad_with_creatives.creatives[0].thumbnail_url is None

        assert ad_with_creatives.creatives[1].image_url == orig_creative1_image
        assert ad_with_creatives.creatives[1].image_url == "https://example.com/existing.jpg"
        assert ad_with_creatives.creatives[1].video_hd_url is orig_creative1_video_hd
        assert ad_with_creatives.creatives[1].video_hd_url is None

    def test_original_list_fields_not_mutated(self, mock_collector, ad_with_creatives):
        """Mutable list fields (publisher_platforms, languages, etc.) on the
        original ad must not be affected by enrichment."""
        orig_platforms = ad_with_creatives.publisher_platforms.copy()
        orig_languages = ad_with_creatives.languages.copy()

        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "DEEPCOPY_TEST",
            "page_id": "pg-1",
            "page_name": "Test Page",
            # These won't overwrite because originals are non-empty,
            # but with shallow copy the list objects would be shared.
        }

        result = mock_collector.enrich_ad(ad_with_creatives)

        # Original lists must be the same content
        assert ad_with_creatives.publisher_platforms == orig_platforms
        assert ad_with_creatives.languages == orig_languages

        # And they must NOT be the same object as the result's lists
        # (deepcopy guarantees distinct list objects)
        assert ad_with_creatives.creatives is not result.creatives

    def test_original_creatives_list_identity_preserved(
        self, mock_collector, ad_with_creatives
    ):
        """The original ad's creatives list must be a different object from
        the result's creatives list (not shared reference)."""
        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "DEEPCOPY_TEST",
            "page_id": "pg-1",
            "page_name": "Test Page",
            "cards": [
                {
                    "body": "Original body text",
                    "resized_image_url": "https://cdn.example.com/new.jpg",
                },
            ],
        }

        result = mock_collector.enrich_ad(ad_with_creatives)

        # The creatives lists must be different objects
        assert ad_with_creatives.creatives is not result.creatives
        # Individual creative objects must also be different
        assert ad_with_creatives.creatives[0] is not result.creatives[0]

    def test_enrichment_of_empty_creatives_does_not_affect_original(
        self, mock_collector
    ):
        """When the original ad has no creatives and enrichment adds them,
        the original must stay empty."""
        ad = Ad(
            id="EMPTY_CREATIVES",
            page=PageInfo(id="pg-1", name="Test"),
            creatives=[],
        )

        mock_collector.client.get_ad_details.return_value = {
            "ad_archive_id": "EMPTY_CREATIVES",
            "page_id": "pg-1",
            "page_name": "Test",
            "cards": [
                {
                    "body": "New creative from enrichment",
                    "resized_image_url": "https://cdn.example.com/new.jpg",
                },
            ],
        }

        result = mock_collector.enrich_ad(ad)

        # Result should have the new creative
        assert len(result.creatives) == 1
        assert result.creatives[0].image_url == "https://cdn.example.com/new.jpg"

        # Original must remain empty
        assert len(ad.creatives) == 0
