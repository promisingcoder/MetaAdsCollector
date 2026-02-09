"""Tests for media download integration in collector and CLI."""

import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from meta_ads_collector.cli import parse_args
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.events import EventEmitter
from meta_ads_collector.media import MediaDownloadResult
from meta_ads_collector.models import Ad, AdCreative, PageInfo

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Create a MetaAdsCollector with a mocked client."""
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    collector.client.session = MagicMock(spec=requests.Session)
    collector.rate_limit_delay = 0
    collector.jitter = 0
    collector.event_emitter = EventEmitter()
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
def sample_ads():
    """Create a few sample ads with media URLs."""
    return [
        Ad(
            id="AD100",
            page=PageInfo(id="pg-1", name="Page One"),
            creatives=[
                AdCreative(
                    body="Test ad 1",
                    image_url="https://cdn.facebook.com/img1.jpg",
                ),
            ],
        ),
        Ad(
            id="AD200",
            page=PageInfo(id="pg-2", name="Page Two"),
            creatives=[
                AdCreative(
                    body="Test ad 2",
                    image_url="https://cdn.facebook.com/img2.png",
                    video_hd_url="https://cdn.facebook.com/vid2.mp4",
                ),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# collect_with_media
# ---------------------------------------------------------------------------


class TestCollectWithMedia:
    def test_yields_ad_and_results_tuples(self, mock_client, sample_ads, tmp_path):
        """collect_with_media should yield (Ad, list[MediaDownloadResult]) tuples."""
        # Make search_ads return our sample data
        ad_data_list = [{"ad_archive_id": ad.id, "page_id": "pg-1", "page_name": "Test"} for ad in sample_ads]
        mock_client.client.search_ads.return_value = (
            {"ads": ad_data_list, "page_info": {}},
            None,  # no next cursor
        )

        # Mock the MediaDownloader to avoid real downloads
        with patch("meta_ads_collector.collector.MediaDownloader") as MockDownloader:
            mock_dl = MagicMock()
            mock_dl.download_ad_media.return_value = [
                MediaDownloadResult(
                    ad_id="test",
                    creative_index=0,
                    media_type="image",
                    url="https://example.com/img.jpg",
                    success=True,
                    local_path=str(tmp_path / "img.jpg"),
                    file_size=100,
                ),
            ]
            MockDownloader.return_value = mock_dl

            results = list(mock_client.collect_with_media(
                media_output_dir=str(tmp_path),
                max_results=2,
            ))

            assert len(results) == 2
            for ad, download_results in results:
                assert isinstance(ad, Ad)
                assert isinstance(download_results, list)
                assert len(download_results) == 1
                assert download_results[0].success is True

    def test_yields_ad_even_if_media_fails(self, mock_client, tmp_path):
        """If media download crashes unexpectedly, ad data is not lost."""
        ad_data = [{"ad_archive_id": "CRASH_AD", "page_id": "pg-1", "page_name": "Test"}]
        mock_client.client.search_ads.return_value = (
            {"ads": ad_data, "page_info": {}},
            None,
        )

        with patch("meta_ads_collector.collector.MediaDownloader") as MockDownloader:
            mock_dl = MagicMock()
            mock_dl.download_ad_media.side_effect = RuntimeError("Unexpected crash!")
            MockDownloader.return_value = mock_dl

            results = list(mock_client.collect_with_media(
                media_output_dir=str(tmp_path),
                max_results=1,
            ))

            assert len(results) == 1
            ad, download_results = results[0]
            assert isinstance(ad, Ad)
            assert download_results == []  # empty list, not crash


# ---------------------------------------------------------------------------
# download_ad_media
# ---------------------------------------------------------------------------


class TestDownloadAdMedia:
    def test_download_ad_media_convenience(self, mock_client, sample_ads, tmp_path):
        """download_ad_media is a simple wrapper that returns results."""
        with patch("meta_ads_collector.collector.MediaDownloader") as MockDownloader:
            mock_dl = MagicMock()
            mock_dl.download_ad_media.return_value = [
                MediaDownloadResult(
                    ad_id="AD100",
                    creative_index=0,
                    media_type="image",
                    url="https://cdn.facebook.com/img1.jpg",
                    success=True,
                    local_path=str(tmp_path / "AD100_0_image.jpg"),
                    file_size=200,
                ),
            ]
            MockDownloader.return_value = mock_dl

            results = mock_client.download_ad_media(sample_ads[0], output_dir=str(tmp_path))
            assert len(results) == 1
            assert results[0].success is True
            assert results[0].ad_id == "AD100"

    def test_download_ad_media_never_raises(self, mock_client, sample_ads, tmp_path):
        """download_ad_media should never raise even if internals crash."""
        with patch("meta_ads_collector.collector.MediaDownloader") as MockDownloader:
            MockDownloader.side_effect = RuntimeError("Constructor crashed!")

            results = mock_client.download_ad_media(sample_ads[0], output_dir=str(tmp_path))
            assert results == []


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------


class TestCLIMediaFlags:
    def test_download_media_flag_present(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--download-media"]):
            args = parse_args()
            assert args.download_media is True

    def test_download_media_flag_absent(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.download_media is False

    def test_no_download_media_flag(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--no-download-media"]):
            args = parse_args()
            assert args.no_download_media is True

    def test_media_dir_default(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.media_dir == "./ad_media"

    def test_media_dir_custom(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--media-dir", "/tmp/my_media"]):
            args = parse_args()
            assert args.media_dir == "/tmp/my_media"

    def test_enrich_flag_present(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--enrich"]):
            args = parse_args()
            assert args.enrich is True

    def test_enrich_flag_absent(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json"]):
            args = parse_args()
            assert args.enrich is False

    def test_no_enrich_flag(self):
        with patch.object(sys, "argv", ["prog", "-o", "out.json", "--no-enrich"]):
            args = parse_args()
            assert args.no_enrich is True

    def test_all_media_flags_together(self):
        with patch.object(sys, "argv", [
            "prog", "-o", "out.json",
            "--download-media",
            "--media-dir", "/data/media",
            "--enrich",
        ]):
            args = parse_args()
            assert args.download_media is True
            assert args.media_dir == "/data/media"
            assert args.enrich is True
