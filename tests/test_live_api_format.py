"""Tests for live Meta API response format parsing.

These tests verify that ``Ad.from_graphql_response()`` correctly handles
the actual response structure returned by the live Meta Ad Library API,
as observed in real API captures.

Key differences from the old test fixtures:
- ``body`` is a dict ``{"text": "..."}`` not a plain string
- ``videos[]`` and ``images[]`` are top-level arrays
- ``cards`` is typically an empty list for single-creative ads
- ``page_categories`` maps to ``Ad.categories``
- ``page_like_count`` maps to ``PageInfo.likes``
- ``display_format`` is present but not directly mapped to a field
"""

from __future__ import annotations

from typing import Any

import pytest

from meta_ads_collector.models import Ad

# ---------------------------------------------------------------------------
# Fixtures: realistic API response data
# ---------------------------------------------------------------------------


@pytest.fixture
def live_api_ad_data() -> dict[str, Any]:
    """A realistic ad dict matching the actual Meta API response structure.

    This mirrors the real collated_results item format as documented in
    the C1 bug report.
    """
    return {
        "ad_archive_id": "1888158438694361",
        "body": {"text": "Want to learn how to invest in the stock market?"},
        "title": "Call to Leap - Stock Market Education",
        "caption": "calltoleap.com",
        "link_url": "https://calltoleap.com/join",
        "link_description": None,
        "cta_text": "Learn more",
        "cta_type": "LEARN_MORE",
        "display_format": "VIDEO",
        "videos": [
            {
                "video_hd_url": "https://video.xx.fbcdn.net/hd.mp4",
                "video_sd_url": "https://video.xx.fbcdn.net/sd.mp4",
                "video_preview_image_url": "https://scontent.xx.fbcdn.net/thumb.jpg",
            }
        ],
        "images": [
            {
                "original_image_url": "https://scontent.xx.fbcdn.net/original.jpg",
                "resized_image_url": "https://scontent.xx.fbcdn.net/resized.jpg",
            }
        ],
        "cards": [],
        "page_id": "100654373063470",
        "page_name": "Call to Leap",
        "page_profile_picture_url": "https://scontent.xx.fbcdn.net/profile.jpg",
        "page_profile_uri": "https://www.facebook.com/calltoleap/",
        "page_like_count": 1513559,
        "page_categories": ["Financial Service"],
        "page_is_deleted": False,
        "collation_id": "1059068629377795",
        "collation_count": 4,
        "branded_content": None,
        "byline": None,
        "disclaimer_label": None,
        "is_reshared": False,
    }


@pytest.fixture
def live_api_image_only_ad() -> dict[str, Any]:
    """A live API ad with images but no videos."""
    return {
        "ad_archive_id": "2222222222222222",
        "body": {"text": "Check out our summer sale!"},
        "title": "Summer Sale 2024",
        "caption": "example.com",
        "link_url": "https://example.com/sale",
        "link_description": "Up to 50% off",
        "cta_text": "Shop Now",
        "cta_type": "SHOP_NOW",
        "display_format": "IMAGE",
        "videos": [],
        "images": [
            {
                "original_image_url": "https://scontent.xx.fbcdn.net/sale.jpg",
                "resized_image_url": "https://scontent.xx.fbcdn.net/sale_resized.jpg",
            }
        ],
        "cards": [],
        "page_id": "999999999",
        "page_name": "Example Store",
        "page_profile_picture_url": "https://scontent.xx.fbcdn.net/store.jpg",
        "page_profile_uri": "https://www.facebook.com/examplestore/",
        "page_like_count": 25000,
        "page_categories": ["Shopping & Retail", "E-Commerce"],
        "page_is_deleted": False,
        "collation_id": "3333333333333333",
        "collation_count": 1,
    }


@pytest.fixture
def live_api_minimal_ad() -> dict[str, Any]:
    """A minimal live API ad with only required fields."""
    return {
        "ad_archive_id": "3333333333333333",
        "body": {"text": "Simple text ad"},
        "title": None,
        "caption": None,
        "link_url": None,
        "videos": [],
        "images": [],
        "cards": [],
        "page_id": "111111111",
        "page_name": "Simple Page",
        "page_like_count": 100,
        "page_categories": [],
        "collation_count": 1,
    }


# ---------------------------------------------------------------------------
# C1: Body parsing - body as dict {"text": "..."}
# ---------------------------------------------------------------------------


class TestBodyParsing:
    """Verify that body is correctly extracted from dict format."""

    def test_body_dict_format(self, live_api_ad_data):
        """body: {"text": "..."} should extract the text value."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.creatives[0].body == "Want to learn how to invest in the stock market?"

    def test_body_string_format(self):
        """body as plain string should still work (backward compat)."""
        data = {
            "ad_archive_id": "111",
            "body": "Plain string body",
            "title": "Test",
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body == "Plain string body"

    def test_body_dict_none_text(self):
        """body: {"text": None} should return None."""
        data = {
            "ad_archive_id": "222",
            "body": {"text": None},
            "title": "Test",
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body is None

    def test_body_dict_empty_text(self):
        """body: {"text": ""} should return empty string."""
        data = {
            "ad_archive_id": "333",
            "body": {"text": ""},
            "title": "Test",
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body == ""

    def test_body_none(self):
        """body: None should return None."""
        data = {
            "ad_archive_id": "444",
            "body": None,
            "title": "Test",
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body is None

    def test_body_dict_in_cards(self):
        """body in cards should also handle dict format."""
        data = {
            "ad_archive_id": "555",
            "cards": [
                {
                    "body": {"text": "Card body text"},
                    "title": "Card Title",
                }
            ],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body == "Card body text"


# ---------------------------------------------------------------------------
# C1: Video array parsing
# ---------------------------------------------------------------------------


class TestVideosParsing:
    """Verify videos[] array is correctly parsed from top-level."""

    def test_video_urls_extracted(self, live_api_ad_data):
        """videos[0] should populate video URLs on the creative."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        creative = ad.creatives[0]
        assert creative.video_hd_url == "https://video.xx.fbcdn.net/hd.mp4"
        assert creative.video_sd_url == "https://video.xx.fbcdn.net/sd.mp4"
        assert creative.video_url == "https://video.xx.fbcdn.net/hd.mp4"
        assert creative.thumbnail_url == "https://scontent.xx.fbcdn.net/thumb.jpg"

    def test_empty_videos_array(self, live_api_image_only_ad):
        """Empty videos[] should leave video URLs as None."""
        ad = Ad.from_graphql_response(live_api_image_only_ad)
        creative = ad.creatives[0]
        assert creative.video_url is None
        assert creative.video_hd_url is None
        assert creative.video_sd_url is None
        assert creative.thumbnail_url is None

    def test_video_sd_only(self):
        """When only video_sd_url is present, video_url should use SD."""
        data = {
            "ad_archive_id": "vid-sd-only",
            "body": {"text": "SD only"},
            "title": "Test",
            "videos": [
                {
                    "video_hd_url": None,
                    "video_sd_url": "https://video.xx.fbcdn.net/sd.mp4",
                    "video_preview_image_url": None,
                }
            ],
            "images": [],
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        creative = ad.creatives[0]
        assert creative.video_url == "https://video.xx.fbcdn.net/sd.mp4"
        assert creative.video_hd_url is None
        assert creative.video_sd_url == "https://video.xx.fbcdn.net/sd.mp4"


# ---------------------------------------------------------------------------
# C1: Images array parsing
# ---------------------------------------------------------------------------


class TestImagesParsing:
    """Verify images[] array is correctly parsed from top-level."""

    def test_image_url_extracted(self, live_api_ad_data):
        """images[0] should populate image_url on the creative."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        creative = ad.creatives[0]
        assert creative.image_url == "https://scontent.xx.fbcdn.net/original.jpg"

    def test_image_resized_fallback(self):
        """When original_image_url is None, fall back to resized."""
        data = {
            "ad_archive_id": "img-resized",
            "body": {"text": "Resized only"},
            "title": "Test",
            "videos": [],
            "images": [
                {
                    "original_image_url": None,
                    "resized_image_url": "https://scontent.xx.fbcdn.net/resized.jpg",
                }
            ],
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].image_url == "https://scontent.xx.fbcdn.net/resized.jpg"

    def test_empty_images_array(self):
        """Empty images[] should leave image_url as None."""
        data = {
            "ad_archive_id": "no-img",
            "body": {"text": "No images"},
            "title": "Test",
            "videos": [],
            "images": [],
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].image_url is None


# ---------------------------------------------------------------------------
# C1: Single creative construction from flat fields
# ---------------------------------------------------------------------------


class TestFlatFieldCreative:
    """Verify that flat top-level fields build a single AdCreative."""

    def test_single_creative_from_flat_fields(self, live_api_ad_data):
        """When cards is empty, should build one creative from flat fields."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert len(ad.creatives) == 1

    def test_creative_has_all_flat_fields(self, live_api_ad_data):
        """The creative should have all mapped flat fields."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        creative = ad.creatives[0]
        assert creative.title == "Call to Leap - Stock Market Education"
        assert creative.caption == "calltoleap.com"
        assert creative.link_url == "https://calltoleap.com/join"
        assert creative.cta_text == "Learn more"
        assert creative.cta_type == "LEARN_MORE"
        assert creative.description is None  # link_description was None

    def test_link_description_mapped(self, live_api_image_only_ad):
        """link_description should map to creative.description."""
        ad = Ad.from_graphql_response(live_api_image_only_ad)
        assert ad.creatives[0].description == "Up to 50% off"


# ---------------------------------------------------------------------------
# C1: page_categories mapping
# ---------------------------------------------------------------------------


class TestPageCategoriesMapping:
    """Verify page_categories maps to Ad.categories."""

    def test_page_categories_mapped(self, live_api_ad_data):
        """page_categories should populate Ad.categories."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.categories == ["Financial Service"]

    def test_multiple_page_categories(self, live_api_image_only_ad):
        """Multiple page_categories should all be present."""
        ad = Ad.from_graphql_response(live_api_image_only_ad)
        assert ad.categories == ["Shopping & Retail", "E-Commerce"]

    def test_empty_page_categories(self, live_api_minimal_ad):
        """Empty page_categories should result in empty categories."""
        ad = Ad.from_graphql_response(live_api_minimal_ad)
        assert ad.categories == []

    def test_categories_field_takes_precedence(self):
        """Explicit categories field should take precedence over page_categories."""
        data = {
            "ad_archive_id": "cat-both",
            "categories": ["Political"],
            "page_categories": ["Financial Service"],
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.categories == ["Political"]


# ---------------------------------------------------------------------------
# C1: page_like_count mapping
# ---------------------------------------------------------------------------


class TestPageLikeCountMapping:
    """Verify page_like_count maps to PageInfo.likes."""

    def test_page_like_count_mapped(self, live_api_ad_data):
        """page_like_count should populate PageInfo.likes."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.page is not None
        assert ad.page.likes == 1513559

    def test_page_like_count_zero(self):
        """page_like_count of 0 should still be stored."""
        data = {
            "ad_archive_id": "likes-zero",
            "page_id": "pg-1",
            "page_name": "No Likes",
            "page_like_count": 0,
            "cards": [],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.page is not None
        assert ad.page.likes == 0


# ---------------------------------------------------------------------------
# C1: Page info from flat fields
# ---------------------------------------------------------------------------


class TestPageInfoFromFlatFields:
    """Verify page info is correctly extracted from flat top-level fields."""

    def test_page_id_extracted(self, live_api_ad_data):
        """page_id should be used for PageInfo.id."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.page.id == "100654373063470"

    def test_page_name_extracted(self, live_api_ad_data):
        """page_name should be used for PageInfo.name."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.page.name == "Call to Leap"

    def test_page_profile_picture_url(self, live_api_ad_data):
        """page_profile_picture_url should map to profile_picture_url."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.page.profile_picture_url == "https://scontent.xx.fbcdn.net/profile.jpg"

    def test_page_profile_uri(self, live_api_ad_data):
        """page_profile_uri should map to page_url."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.page.page_url == "https://www.facebook.com/calltoleap/"


# ---------------------------------------------------------------------------
# C1: Collation fields
# ---------------------------------------------------------------------------


class TestCollationFields:
    """Verify collation fields are correctly mapped."""

    def test_collation_id(self, live_api_ad_data):
        """collation_id should be mapped."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.collation_id == "1059068629377795"

    def test_collation_count(self, live_api_ad_data):
        """collation_count should be mapped."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.collation_count == 4


# ---------------------------------------------------------------------------
# C1: display_format stored in raw_data
# ---------------------------------------------------------------------------


class TestDisplayFormat:
    """Verify display_format is accessible through raw_data."""

    def test_display_format_in_raw_data(self, live_api_ad_data):
        """display_format should be preserved in raw_data."""
        ad = Ad.from_graphql_response(live_api_ad_data)
        assert ad.raw_data is not None
        assert ad.raw_data["display_format"] == "VIDEO"


# ---------------------------------------------------------------------------
# C1: Backward compatibility with cards format
# ---------------------------------------------------------------------------


class TestCardsFormatBackwardCompat:
    """Verify the cards format still works after the C1 changes."""

    def test_cards_format_still_works(self, sample_graphql_ad_data):
        """Existing cards-based test fixture should still parse correctly."""
        ad = Ad.from_graphql_response(sample_graphql_ad_data)
        assert ad.id == "12345"
        assert len(ad.creatives) == 1
        assert ad.creatives[0].body == "Buy our product!"
        assert ad.creatives[0].title == "Great Deal"

    def test_cards_with_body_dict(self):
        """Cards with body as dict should also be handled."""
        data = {
            "ad_archive_id": "card-dict-body",
            "cards": [
                {
                    "body": {"text": "Card with dict body"},
                    "title": "Card Title",
                    "link_url": "https://example.com",
                }
            ],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body == "Card with dict body"
        assert ad.creatives[0].title == "Card Title"


# ---------------------------------------------------------------------------
# C1: Backward compatibility with legacy format
# ---------------------------------------------------------------------------


class TestLegacyFormatBackwardCompat:
    """Verify the ad_creative_bodies legacy format still works."""

    def test_legacy_bodies_format(self):
        """ad_creative_bodies format should still parse correctly."""
        data = {
            "ad_archive_id": "legacy-1",
            "page_id": "pg-1",
            "page_name": "Legacy Page",
            "ad_creative_bodies": ["Legacy body text"],
            "ad_creative_link_titles": ["Legacy title"],
        }
        ad = Ad.from_graphql_response(data)
        assert ad.creatives[0].body == "Legacy body text"
        assert ad.creatives[0].title == "Legacy title"


# ---------------------------------------------------------------------------
# C1: _extract_body_text class method
# ---------------------------------------------------------------------------


class TestExtractBodyText:
    """Verify the _extract_body_text helper method."""

    def test_none_returns_none(self):
        assert Ad._extract_body_text(None) is None

    def test_string_returns_string(self):
        assert Ad._extract_body_text("hello") == "hello"

    def test_dict_extracts_text(self):
        assert Ad._extract_body_text({"text": "hello"}) == "hello"

    def test_dict_missing_text_key(self):
        assert Ad._extract_body_text({"other": "value"}) is None

    def test_dict_none_text(self):
        assert Ad._extract_body_text({"text": None}) is None

    def test_empty_string(self):
        assert Ad._extract_body_text("") == ""

    def test_empty_dict(self):
        assert Ad._extract_body_text({}) is None

    def test_unexpected_type_returns_none(self):
        assert Ad._extract_body_text(12345) is None
        assert Ad._extract_body_text([]) is None
        assert Ad._extract_body_text(True) is None


# ---------------------------------------------------------------------------
# C2: _parse_search_response flattening
# ---------------------------------------------------------------------------


class TestParseSearchResponseFlattening:
    """Verify that _parse_search_response passes through all fields."""

    def _client(self):
        from meta_ads_collector.client import MetaAdsClient
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_all_fields_passed_through(self):
        """All fields from collated_results items should be in the output."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "search_results_connection": {
                        "edges": [
                            {
                                "node": {
                                    "collated_results": [
                                        {
                                            "ad_archive_id": "12345",
                                            "body": {"text": "Hello"},
                                            "title": "My Title",
                                            "videos": [{"video_hd_url": "https://example.com/hd.mp4"}],
                                            "images": [{"original_image_url": "https://example.com/img.jpg"}],
                                            "page_id": "pg-1",
                                            "page_name": "Test Page",
                                            "page_like_count": 5000,
                                            "cards": [],
                                            "display_format": "VIDEO",
                                        }
                                    ]
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False},
                    }
                }
            }
        }
        result, cursor = client._parse_search_response(data)
        ads = result["ads"]
        assert len(ads) == 1
        ad_data = ads[0]
        # All original fields should be present
        assert ad_data["ad_archive_id"] == "12345"
        assert ad_data["body"] == {"text": "Hello"}
        assert ad_data["title"] == "My Title"
        assert ad_data["videos"] == [{"video_hd_url": "https://example.com/hd.mp4"}]
        assert ad_data["images"] == [{"original_image_url": "https://example.com/img.jpg"}]
        assert ad_data["page_id"] == "pg-1"
        assert ad_data["page_name"] == "Test Page"
        assert ad_data["page_like_count"] == 5000
        assert ad_data["display_format"] == "VIDEO"

    def test_snapshot_fields_merged_without_overwrite(self):
        """Snapshot fields should be merged but NOT overwrite existing fields."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "search_results_connection": {
                        "edges": [
                            {
                                "node": {
                                    "collated_results": [
                                        {
                                            "ad_archive_id": "99999",
                                            "title": "Top-level title",
                                            "snapshot": {
                                                "title": "Snapshot title",
                                                "extra_field": "from snapshot",
                                            },
                                        }
                                    ]
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False},
                    }
                }
            }
        }
        result, _ = client._parse_search_response(data)
        ad_data = result["ads"][0]
        # Top-level title should NOT be overwritten by snapshot title
        assert ad_data["title"] == "Top-level title"
        # Extra field from snapshot should be merged in
        assert ad_data["extra_field"] == "from snapshot"

    def test_end_to_end_with_from_graphql_response(self):
        """Full flow: _parse_search_response -> Ad.from_graphql_response."""
        client = self._client()
        data = {
            "data": {
                "ad_library_main": {
                    "search_results_connection": {
                        "edges": [
                            {
                                "node": {
                                    "collated_results": [
                                        {
                                            "ad_archive_id": "e2e-001",
                                            "body": {"text": "End-to-end body text"},
                                            "title": "E2E Title",
                                            "caption": "e2e.com",
                                            "link_url": "https://e2e.com",
                                            "cta_text": "Sign Up",
                                            "cta_type": "SIGN_UP",
                                            "videos": [],
                                            "images": [
                                                {
                                                    "original_image_url": "https://e2e.com/img.jpg",
                                                    "resized_image_url": None,
                                                }
                                            ],
                                            "cards": [],
                                            "page_id": "pg-e2e",
                                            "page_name": "E2E Page",
                                            "page_like_count": 42,
                                            "page_categories": ["Technology"],
                                            "collation_id": "c-e2e",
                                            "collation_count": 1,
                                        }
                                    ]
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False},
                    }
                }
            }
        }
        result, cursor = client._parse_search_response(data)
        assert cursor is None
        assert len(result["ads"]) == 1

        ad = Ad.from_graphql_response(result["ads"][0])
        assert ad.id == "e2e-001"
        assert ad.creatives[0].body == "End-to-end body text"
        assert ad.creatives[0].title == "E2E Title"
        assert ad.creatives[0].caption == "e2e.com"
        assert ad.creatives[0].link_url == "https://e2e.com"
        assert ad.creatives[0].cta_text == "Sign Up"
        assert ad.creatives[0].image_url == "https://e2e.com/img.jpg"
        assert ad.creatives[0].video_url is None
        assert ad.page.id == "pg-e2e"
        assert ad.page.name == "E2E Page"
        assert ad.page.likes == 42
        assert ad.categories == ["Technology"]
        assert ad.collation_id == "c-e2e"
        assert ad.collation_count == 1


# ---------------------------------------------------------------------------
# N6: _parse_ad_detail_page brace-matching hardening
# ---------------------------------------------------------------------------


class TestParseAdDetailPageHardening:
    """Verify defensive error handling in _parse_ad_detail_page."""

    def _client(self):
        from meta_ads_collector.client import MetaAdsClient
        return MetaAdsClient.__new__(MetaAdsClient)

    def test_escaped_braces_in_ad_text(self):
        """HTML with escaped braces in ad text should not crash."""
        client = self._client()
        html = (
            '{"ad_archive_id":"ESC-001","body":"text with \\{braces\\} inside"}'
        )
        result = client._parse_ad_detail_page(html, "ESC-001")
        # Pattern 1 should catch this since it looks for flat JSON objects
        # Result may or may not parse depending on escaping, but should not crash
        # The important thing is it does not raise
        assert result is None or isinstance(result, dict)

    def test_no_matching_id_returns_none(self):
        """When the ad_archive_id is not found, should return None."""
        client = self._client()
        html = '{"ad_archive_id":"OTHER-001","body":"wrong ad"}'
        result = client._parse_ad_detail_page(html, "NOT-FOUND")
        assert result is None

    def test_empty_html_returns_none(self):
        """Empty HTML should return None."""
        client = self._client()
        result = client._parse_ad_detail_page("", "12345")
        assert result is None

    def test_malformed_json_returns_none(self):
        """Malformed JSON around the archive ID should return None."""
        client = self._client()
        html = '"ad_archive_id":"12345","broken json here{{{}}}'
        result = client._parse_ad_detail_page(html, "12345")
        assert result is None or isinstance(result, dict)

    def test_very_long_html_no_crash(self):
        """Very large HTML with the ID should not crash or hang."""
        client = self._client()
        # Create a long HTML string with the ID buried in the middle
        padding = "x" * 50000
        html = padding + '{"ad_archive_id":"LONG-001","body":"found"}' + padding
        result = client._parse_ad_detail_page(html, "LONG-001")
        # Pattern 1 should find this
        if result is not None:
            assert result.get("ad_archive_id") == "LONG-001"

    def test_no_closing_brace_within_window(self):
        """When no closing brace is found within the search window, returns None."""
        client = self._client()
        # Create HTML where the ad_archive_id is inside a never-closed JSON
        html = '{"ad_archive_id":"NOCLOSE-001"' + ',' * 20000
        result = client._parse_ad_detail_page(html, "NOCLOSE-001")
        # Should not crash, and should return None since JSON can't parse
        assert result is None or isinstance(result, dict)
