"""Tests for meta_ads_collector.fingerprint."""

import re

import pytest

from meta_ads_collector.fingerprint import (
    CHROME_VERSIONS,
    DPR_VALUES,
    VIEWPORTS,
    generate_fingerprint,
)


class TestFingerprintConsistency:
    """Verify that generated fingerprints are internally consistent."""

    def test_chrome_version_matches_ua_and_sec_ch_ua(self):
        """Chrome major version in the UA must match sec-ch-ua."""
        fp = generate_fingerprint()
        # Extract version from UA  (Chrome/XXX.0.0.0)
        ua_match = re.search(r"Chrome/(\d+)\.", fp.user_agent)
        assert ua_match is not None
        ua_version = ua_match.group(1)

        # sec-ch-ua must contain the same version
        assert f'"Google Chrome";v="{ua_version}"' in fp.sec_ch_ua
        assert f'"Chromium";v="{ua_version}"' in fp.sec_ch_ua
        assert ua_version == fp.chrome_major

    def test_full_version_in_full_version_list(self):
        """The full Chrome version appears in sec-ch-ua-full-version-list."""
        fp = generate_fingerprint()
        assert fp.chrome_full in fp.sec_ch_ua_full_version_list

    def test_windows_platform_consistency(self):
        """If platform is Windows, the UA must contain 'Windows NT'."""
        for _ in range(50):
            fp = generate_fingerprint()
            if fp.platform_name == "windows":
                assert "Windows NT" in fp.user_agent
                assert fp.sec_ch_ua_platform == '"Windows"'
                assert "Macintosh" not in fp.user_agent
                return
        pytest.skip("No Windows fingerprint generated after 50 tries")

    def test_macos_platform_consistency(self):
        """If platform is macOS, the UA must contain 'Macintosh'."""
        for _ in range(50):
            fp = generate_fingerprint()
            if fp.platform_name == "macos":
                assert "Macintosh" in fp.user_agent
                assert fp.sec_ch_ua_platform == '"macOS"'
                assert "Windows NT" not in fp.user_agent
                return
        pytest.skip("No macOS fingerprint generated after 50 tries")


class TestFingerprintValueRanges:
    """Verify generated values fall within realistic ranges."""

    def test_viewport_is_realistic(self):
        fp = generate_fingerprint()
        valid_widths = {w for w, _ in VIEWPORTS}
        valid_heights = {h for _, h in VIEWPORTS}
        assert fp.viewport_width in valid_widths
        assert fp.viewport_height in valid_heights

    def test_dpr_is_valid(self):
        fp = generate_fingerprint()
        assert fp.dpr in DPR_VALUES

    def test_chrome_version_is_from_pool(self):
        fp = generate_fingerprint()
        valid_majors = {m for m, _ in CHROME_VERSIONS}
        assert fp.chrome_major in valid_majors

    def test_sec_ch_ua_mobile_is_zero(self):
        fp = generate_fingerprint()
        assert fp.sec_ch_ua_mobile == "?0"


class TestFingerprintVariation:
    """Verify that repeated generations produce variation."""

    def test_not_always_identical(self):
        """Over 20 generations we should see at least two distinct UAs."""
        user_agents = {generate_fingerprint().user_agent for _ in range(20)}
        assert len(user_agents) > 1, "All 20 fingerprints had the same User-Agent"


class TestFingerprintHeaders:
    """Verify the header dictionaries returned by a fingerprint."""

    def test_default_headers_required_fields(self):
        fp = generate_fingerprint()
        headers = fp.get_default_headers()

        required = [
            "accept",
            "accept-language",
            "cache-control",
            "dpr",
            "sec-ch-ua",
            "sec-ch-ua-full-version-list",
            "sec-ch-ua-mobile",
            "sec-ch-ua-model",
            "sec-ch-ua-platform",
            "sec-ch-ua-platform-version",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
            "sec-fetch-user",
            "upgrade-insecure-requests",
            "user-agent",
            "viewport-width",
        ]

        for field in required:
            assert field in headers, f"Missing header: {field}"
            assert headers[field], f"Empty header: {field}"

    def test_graphql_headers_required_fields(self):
        fp = generate_fingerprint()
        headers = fp.get_graphql_headers()

        required = [
            "accept",
            "accept-language",
            "content-type",
            "origin",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "sec-ch-ua-platform",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
            "user-agent",
            "x-asbd-id",
        ]

        for field in required:
            assert field in headers, f"Missing header: {field}"
            assert headers[field], f"Empty header: {field}"

    def test_graphql_content_type(self):
        fp = generate_fingerprint()
        headers = fp.get_graphql_headers()
        assert headers["content-type"] == "application/x-www-form-urlencoded"

    def test_default_headers_dpr_matches_fingerprint(self):
        fp = generate_fingerprint()
        headers = fp.get_default_headers()
        assert headers["dpr"] == str(fp.dpr)

    def test_default_headers_viewport_matches_fingerprint(self):
        fp = generate_fingerprint()
        headers = fp.get_default_headers()
        assert headers["viewport-width"] == str(fp.viewport_width)
