"""
Browser fingerprint generation for Meta Ads Collector.

Generates randomized but internally-consistent browser identity data
to avoid detection by Meta's anti-bot systems.
"""

import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chrome version pool (recent major versions)
# ---------------------------------------------------------------------------
# Each entry: (major_version, full_version)
CHROME_VERSIONS: list[tuple[str, str]] = [
    ("125", "125.0.6422.113"),
    ("126", "126.0.6478.127"),
    ("127", "127.0.6533.100"),
    ("128", "128.0.6613.120"),
    ("129", "129.0.6668.90"),
    ("130", "130.0.6723.117"),
    ("131", "131.0.6778.140"),
    ("132", "132.0.6834.83"),
]

# ---------------------------------------------------------------------------
# Platform definitions
# ---------------------------------------------------------------------------
# Each platform has: (platform_name, ua_os_string, sec_ch_ua_platform,
#                      platform_version)

PLATFORMS: list[dict[str, str]] = [
    {
        "name": "windows",
        "ua_os": "Windows NT 10.0; Win64; x64",
        "sec_ch_ua_platform": '"Windows"',
        "platform_version": '"15.0.0"',
    },
    {
        "name": "macos",
        "ua_os": "Macintosh; Intel Mac OS X 10_15_7",
        "sec_ch_ua_platform": '"macOS"',
        "platform_version": '"14.5.0"',
    },
    {
        "name": "macos",
        "ua_os": "Macintosh; Intel Mac OS X 10_15_7",
        "sec_ch_ua_platform": '"macOS"',
        "platform_version": '"13.6.0"',
    },
    {
        "name": "windows",
        "ua_os": "Windows NT 10.0; Win64; x64",
        "sec_ch_ua_platform": '"Windows"',
        "platform_version": '"10.0.0"',
    },
]

# ---------------------------------------------------------------------------
# Viewport and DPR pools
# ---------------------------------------------------------------------------
VIEWPORTS: list[tuple[int, int]] = [
    (1366, 768),
    (1440, 900),
    (1536, 864),
    (1920, 1080),
    (2560, 1440),
    (1680, 1050),
    (1280, 720),
    (1600, 900),
]

DPR_VALUES: list[float] = [1, 1.25, 1.5, 2, 3]

# ---------------------------------------------------------------------------
# "Not A Brand" hint variations
# ---------------------------------------------------------------------------
NOT_A_BRAND_HINTS: list[tuple[str, str]] = [
    ("Not_A Brand", "24"),
    ("Not/A)Brand", "8"),
    ("Not.A/Brand", "8"),
    ("Not A(Brand", "99"),
]


@dataclass
class BrowserFingerprint:
    """Represents a consistent browser fingerprint for a session.

    All fields are internally consistent: the Chrome version in the User-Agent
    matches the version in sec-ch-ua, and the platform in the UA matches
    sec-ch-ua-platform.
    """

    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_full_version_list: str
    sec_ch_ua_platform: str
    sec_ch_ua_platform_version: str
    sec_ch_ua_mobile: str
    viewport_width: int
    viewport_height: int
    dpr: float
    platform_name: str
    chrome_major: str
    chrome_full: str

    def get_default_headers(self) -> dict[str, str]:
        """Return headers suitable for a page-load (navigation) request.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "max-age=0",
            "dpr": str(self.dpr),
            "sec-ch-prefers-color-scheme": "light",
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-full-version-list": self.sec_ch_ua_full_version_list,
            "sec-ch-ua-mobile": self.sec_ch_ua_mobile,
            "sec-ch-ua-model": '""',
            "sec-ch-ua-platform": self.sec_ch_ua_platform,
            "sec-ch-ua-platform-version": self.sec_ch_ua_platform_version,
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": self.user_agent,
            "viewport-width": str(self.viewport_width),
        }

    def get_graphql_headers(self) -> dict[str, str]:
        """Return headers suitable for a GraphQL XHR request.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://www.facebook.com",
            "sec-ch-prefers-color-scheme": "light",
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-mobile": self.sec_ch_ua_mobile,
            "sec-ch-ua-platform": self.sec_ch_ua_platform,
            "sec-ch-ua-platform-version": self.sec_ch_ua_platform_version,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": self.user_agent,
            "x-asbd-id": "359341",
        }


def generate_fingerprint() -> BrowserFingerprint:
    """Generate a randomized but internally-consistent browser fingerprint.

    The fingerprint includes a User-Agent, client-hint headers, viewport
    dimensions, and DPR -- all matching the same Chrome version and OS
    platform.

    Returns:
        A BrowserFingerprint instance.
    """
    # Pick random Chrome version
    chrome_major, chrome_full = random.choice(CHROME_VERSIONS)

    # Pick random platform
    platform = random.choice(PLATFORMS)

    # Pick viewport and DPR
    viewport_width, viewport_height = random.choice(VIEWPORTS)
    dpr = random.choice(DPR_VALUES)

    # Pick a "Not a Brand" variant
    nab_name, nab_version = random.choice(NOT_A_BRAND_HINTS)

    # Build User-Agent
    user_agent = (
        f"Mozilla/5.0 ({platform['ua_os']}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"
    )

    # Build sec-ch-ua
    sec_ch_ua = (
        f'"Google Chrome";v="{chrome_major}", '
        f'"Chromium";v="{chrome_major}", '
        f'"{nab_name}";v="{nab_version}"'
    )

    # Build sec-ch-ua-full-version-list
    sec_ch_ua_full_version_list = (
        f'"Google Chrome";v="{chrome_full}", '
        f'"Chromium";v="{chrome_full}", '
        f'"{nab_name}";v="{nab_version}.0.0.0"'
    )

    fingerprint = BrowserFingerprint(
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        sec_ch_ua_full_version_list=sec_ch_ua_full_version_list,
        sec_ch_ua_platform=platform["sec_ch_ua_platform"],
        sec_ch_ua_platform_version=platform["platform_version"],
        sec_ch_ua_mobile="?0",
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        dpr=dpr,
        platform_name=platform["name"],
        chrome_major=chrome_major,
        chrome_full=chrome_full,
    )

    logger.debug(
        "Generated fingerprint: Chrome/%s %s %sx%s DPR=%s",
        chrome_major,
        platform["name"],
        viewport_width,
        viewport_height,
        dpr,
    )

    return fingerprint
