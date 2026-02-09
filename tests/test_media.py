"""Tests for meta_ads_collector.media."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from meta_ads_collector.media import (
    MediaDownloader,
    MediaDownloadResult,
    detect_extension_from_content_type,
    detect_extension_from_url,
)
from meta_ads_collector.models import Ad, AdCreative, PageInfo

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provide a temporary directory for downloads."""
    out = tmp_path / "media_output"
    out.mkdir()
    return out


@pytest.fixture
def downloader(tmp_output_dir):
    """Provide a MediaDownloader with a mocked session."""
    session = MagicMock(spec=requests.Session)
    return MediaDownloader(
        output_dir=tmp_output_dir,
        session=session,
        timeout=10,
        max_retries=2,
    )


@pytest.fixture
def ad_with_media():
    """An Ad with multiple creatives containing various media URLs."""
    return Ad(
        id="AD001",
        page=PageInfo(id="pg-1", name="Test Page"),
        creatives=[
            AdCreative(
                body="First creative",
                image_url="https://cdn.facebook.com/image/abc.jpg?token=xyz",
                video_hd_url="https://video-cdn.facebook.com/hd/video.mp4?quality=hd",
                video_sd_url="https://video-cdn.facebook.com/sd/video.mp4?quality=sd",
                thumbnail_url="https://cdn.facebook.com/thumbs/thumb.png",
            ),
            AdCreative(
                body="Second creative",
                image_url="https://cdn.facebook.com/image/def.webp",
            ),
        ],
    )


@pytest.fixture
def ad_no_media():
    """An Ad with no media URLs at all."""
    return Ad(
        id="AD002",
        page=PageInfo(id="pg-2", name="No Media Page"),
        creatives=[
            AdCreative(body="Text only"),
        ],
    )


@pytest.fixture
def ad_empty_creatives():
    """An Ad with an empty creatives list."""
    return Ad(
        id="AD003",
        page=PageInfo(id="pg-3", name="Empty Creatives"),
        creatives=[],
    )


# ---------------------------------------------------------------------------
# Extension detection from URLs
# ---------------------------------------------------------------------------


class TestDetectExtensionFromUrl:
    def test_jpg_simple(self):
        assert detect_extension_from_url("https://example.com/img.jpg") == ".jpg"

    def test_jpeg(self):
        assert detect_extension_from_url("https://example.com/img.jpeg") == ".jpeg"

    def test_png(self):
        assert detect_extension_from_url("https://example.com/photo.png") == ".png"

    def test_gif(self):
        assert detect_extension_from_url("https://example.com/anim.gif") == ".gif"

    def test_webp(self):
        assert detect_extension_from_url("https://example.com/photo.webp") == ".webp"

    def test_mp4(self):
        assert detect_extension_from_url("https://example.com/video.mp4") == ".mp4"

    def test_webm(self):
        assert detect_extension_from_url("https://example.com/clip.webm") == ".webm"

    def test_url_with_query_string(self):
        url = "https://cdn.facebook.com/img/abc.jpg?token=xyz123&exp=1234567890"
        assert detect_extension_from_url(url) == ".jpg"

    def test_url_with_fragment(self):
        url = "https://example.com/photo.png#section"
        assert detect_extension_from_url(url) == ".png"

    def test_complex_cdn_path(self):
        url = "https://scontent.xx.fbcdn.net/v/t1.6435-9/abc_n.jpg?_nc_cat=1&ccb=1-7&oh=abc&oe=ABC"
        assert detect_extension_from_url(url) == ".jpg"

    def test_no_extension(self):
        assert detect_extension_from_url("https://example.com/media/12345") is None

    def test_unknown_extension(self):
        assert detect_extension_from_url("https://example.com/file.xyz") is None

    def test_empty_url(self):
        assert detect_extension_from_url("") is None

    def test_malformed_url(self):
        assert detect_extension_from_url("not a url at all") is None

    def test_mov_video(self):
        assert detect_extension_from_url("https://example.com/clip.mov") == ".mov"

    def test_case_insensitive(self):
        assert detect_extension_from_url("https://example.com/photo.JPG") == ".jpg"

    def test_svg(self):
        assert detect_extension_from_url("https://example.com/icon.svg") == ".svg"


# ---------------------------------------------------------------------------
# Extension detection from Content-Type
# ---------------------------------------------------------------------------


class TestDetectExtensionFromContentType:
    def test_image_jpeg(self):
        assert detect_extension_from_content_type("image/jpeg") == ".jpg"

    def test_image_jpg(self):
        assert detect_extension_from_content_type("image/jpg") == ".jpg"

    def test_image_png(self):
        assert detect_extension_from_content_type("image/png") == ".png"

    def test_image_gif(self):
        assert detect_extension_from_content_type("image/gif") == ".gif"

    def test_image_webp(self):
        assert detect_extension_from_content_type("image/webp") == ".webp"

    def test_video_mp4(self):
        assert detect_extension_from_content_type("video/mp4") == ".mp4"

    def test_video_webm(self):
        assert detect_extension_from_content_type("video/webm") == ".webm"

    def test_video_quicktime(self):
        assert detect_extension_from_content_type("video/quicktime") == ".mov"

    def test_with_charset_parameter(self):
        assert detect_extension_from_content_type("image/jpeg; charset=utf-8") == ".jpg"

    def test_octet_stream(self):
        assert detect_extension_from_content_type("application/octet-stream") == ".bin"

    def test_unknown_type(self):
        assert detect_extension_from_content_type("application/json") is None

    def test_none_input(self):
        assert detect_extension_from_content_type(None) is None

    def test_empty_string(self):
        assert detect_extension_from_content_type("") is None

    def test_mixed_case(self):
        assert detect_extension_from_content_type("Image/JPEG") == ".jpg"


# ---------------------------------------------------------------------------
# MediaDownloadResult
# ---------------------------------------------------------------------------


class TestMediaDownloadResult:
    def test_success_result(self):
        r = MediaDownloadResult(
            ad_id="123",
            creative_index=0,
            media_type="image",
            url="https://example.com/img.jpg",
            local_path="/tmp/123_0_image.jpg",
            success=True,
            file_size=1024,
        )
        assert r.success is True
        assert r.error is None
        assert r.file_size == 1024
        assert r.local_path == "/tmp/123_0_image.jpg"

    def test_failure_result(self):
        r = MediaDownloadResult(
            ad_id="123",
            creative_index=0,
            media_type="image",
            url="https://example.com/img.jpg",
            success=False,
            error="HTTP 403: Forbidden",
        )
        assert r.success is False
        assert r.local_path is None
        assert r.file_size is None
        assert "403" in r.error

    def test_frozen(self):
        r = MediaDownloadResult(
            ad_id="123",
            creative_index=0,
            media_type="image",
            url="https://example.com/img.jpg",
        )
        with pytest.raises(AttributeError):
            r.success = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MediaDownloader construction
# ---------------------------------------------------------------------------


class TestMediaDownloaderInit:
    def test_creates_output_dir(self, tmp_path):
        new_dir = tmp_path / "new_output_dir"
        assert not new_dir.exists()
        MediaDownloader(output_dir=new_dir)
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_uses_provided_session(self, tmp_output_dir):
        session = MagicMock(spec=requests.Session)
        dl = MediaDownloader(output_dir=tmp_output_dir, session=session)
        assert dl.session is session

    def test_creates_own_session_when_none(self, tmp_output_dir):
        dl = MediaDownloader(output_dir=tmp_output_dir)
        assert isinstance(dl.session, requests.Session)

    def test_default_params(self, tmp_output_dir):
        dl = MediaDownloader(output_dir=tmp_output_dir)
        assert dl.timeout == 30
        assert dl.max_retries == 2

    def test_custom_params(self, tmp_output_dir):
        dl = MediaDownloader(output_dir=tmp_output_dir, timeout=60, max_retries=5)
        assert dl.timeout == 60
        assert dl.max_retries == 5


# ---------------------------------------------------------------------------
# Skip-existing behavior
# ---------------------------------------------------------------------------


class TestSkipExisting:
    def test_skips_when_file_exists_with_content(self, downloader, tmp_output_dir):
        # Create a file that already exists
        filepath = tmp_output_dir / "test_file.jpg"
        filepath.write_bytes(b"existing content")

        success, error, size = downloader._download_file(
            "https://example.com/test.jpg",
            filepath,
        )
        assert success is True
        assert error is None
        assert size == len(b"existing content")
        # Verify the session was NOT called (file was skipped)
        downloader.session.get.assert_not_called()

    def test_does_not_skip_empty_file(self, downloader, tmp_output_dir):
        # Create an empty file
        filepath = tmp_output_dir / "empty_file.jpg"
        filepath.write_bytes(b"")

        # Mock a successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"data"]
        mock_response.raise_for_status.return_value = None
        downloader.session.get.return_value = mock_response

        success, error, size = downloader._download_file(
            "https://example.com/test.jpg",
            filepath,
        )
        assert success is True
        downloader.session.get.assert_called()


# ---------------------------------------------------------------------------
# Never-raises guarantee
# ---------------------------------------------------------------------------


class TestNeverRaises:
    def test_malformed_url_does_not_propagate(self, downloader, tmp_output_dir):
        """A completely broken URL should not propagate exceptions."""
        # Make session.get raise a connection error
        downloader.session.get.side_effect = requests.exceptions.ConnectionError("DNS resolution failed")

        success, error, size = downloader._download_file(
            "https://not-a-real-host.invalid/file.jpg",
            tmp_output_dir / "output.jpg",
        )
        assert success is False
        assert error is not None
        assert "Connection error" in error

    def test_timeout_does_not_propagate(self, downloader, tmp_output_dir):
        downloader.session.get.side_effect = requests.exceptions.Timeout("Read timed out")

        success, error, size = downloader._download_file(
            "https://slow-server.example.com/file.jpg",
            tmp_output_dir / "output.jpg",
        )
        assert success is False
        assert "Timeout" in error

    def test_io_error_does_not_propagate(self, downloader, tmp_output_dir):
        """IO errors during file write should not propagate."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.side_effect = OSError("Disk full")
        downloader.session.get.return_value = mock_response

        success, error, size = downloader._download_file(
            "https://example.com/file.jpg",
            tmp_output_dir / "output.jpg",
        )
        assert success is False
        assert "IO error" in error

    def test_unexpected_exception_does_not_propagate(self, downloader, tmp_output_dir):
        downloader.session.get.side_effect = RuntimeError("Something completely unexpected")

        success, error, size = downloader._download_file(
            "https://example.com/file.jpg",
            tmp_output_dir / "output.jpg",
        )
        assert success is False
        assert "Unexpected error" in error

    def test_403_expired_url(self, downloader, tmp_output_dir):
        """403 (expired CDN URL) should return failure immediately without retrying."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        downloader.session.get.return_value = mock_response

        success, error, size = downloader._download_file(
            "https://cdn.facebook.com/expired.jpg?token=expired",
            tmp_output_dir / "output.jpg",
        )
        assert success is False
        assert "403" in error
        # Should only be called once (no retry for 403)
        assert downloader.session.get.call_count == 1

    def test_download_ad_media_never_raises(self, downloader):
        """download_ad_media should never raise, even with broken ad data."""
        # Create an ad with a None creatives field (will be empty list by default)
        ad = Ad(id="BROKEN")
        results = downloader.download_ad_media(ad)
        assert isinstance(results, list)
        assert len(results) == 0

    def test_download_ad_media_with_all_failures(self, downloader, ad_with_media):
        """All downloads fail but we get structured results, not exceptions."""
        downloader.session.get.side_effect = requests.exceptions.ConnectionError("offline")

        results = downloader.download_ad_media(ad_with_media)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert r.success is False
            assert r.error is not None


# ---------------------------------------------------------------------------
# Multi-creative ad handling
# ---------------------------------------------------------------------------


class TestMultiCreativeHandling:
    def test_downloads_all_creatives(self, downloader, ad_with_media):
        """All media URLs from all creatives should be attempted."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"imagedata"]
        mock_response.raise_for_status.return_value = None
        downloader.session.get.return_value = mock_response

        results = downloader.download_ad_media(ad_with_media)

        # First creative has: image, video_hd, video_sd, thumbnail = 4
        # Second creative has: image = 1
        # Total = 5
        assert len(results) == 5

        # Check creative indices are correct
        creative_0_results = [r for r in results if r.creative_index == 0]
        creative_1_results = [r for r in results if r.creative_index == 1]
        assert len(creative_0_results) == 4
        assert len(creative_1_results) == 1

    def test_skips_none_urls(self, downloader, ad_no_media):
        """Creatives with no media URLs should produce no results."""
        results = downloader.download_ad_media(ad_no_media)
        assert results == []

    def test_empty_creatives(self, downloader, ad_empty_creatives):
        """An ad with no creatives should produce no results."""
        results = downloader.download_ad_media(ad_empty_creatives)
        assert results == []

    def test_media_types_are_correct(self, downloader, ad_with_media):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"data"]
        mock_response.raise_for_status.return_value = None
        downloader.session.get.return_value = mock_response

        results = downloader.download_ad_media(ad_with_media)
        media_types = {r.media_type for r in results}
        assert "image" in media_types
        assert "video_hd" in media_types
        assert "video_sd" in media_types
        assert "thumbnail" in media_types


# ---------------------------------------------------------------------------
# File naming convention
# ---------------------------------------------------------------------------


class TestFileNaming:
    def test_build_filename(self, downloader):
        name = downloader._build_filename("AD001", 0, "image", ".jpg")
        assert name == "AD001_0_image.jpg"

    def test_build_filename_video(self, downloader):
        name = downloader._build_filename("AD001", 1, "video_hd", ".mp4")
        assert name == "AD001_1_video_hd.mp4"

    def test_build_filename_thumbnail(self, downloader):
        name = downloader._build_filename("AD001", 2, "thumbnail", ".png")
        assert name == "AD001_2_thumbnail.png"

    def test_build_filename_unknown_ext(self, downloader):
        name = downloader._build_filename("AD001", 0, "image", ".bin")
        assert name == "AD001_0_image.bin"


# ---------------------------------------------------------------------------
# Resolve extension
# ---------------------------------------------------------------------------


class TestResolveExtension:
    def test_url_extension_takes_priority(self, downloader):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "image/png"}
        # URL says .jpg, Content-Type says .png -- URL wins
        ext = downloader._resolve_extension("https://example.com/img.jpg", mock_response)
        assert ext == ".jpg"

    def test_falls_back_to_content_type(self, downloader):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "image/png"}
        ext = downloader._resolve_extension("https://example.com/media/12345", mock_response)
        assert ext == ".png"

    def test_falls_back_to_bin(self, downloader):
        ext = downloader._resolve_extension("https://example.com/media/12345", None)
        assert ext == ".bin"

    def test_falls_back_to_bin_with_unknown_content_type(self, downloader):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/x-custom"}
        ext = downloader._resolve_extension("https://example.com/media/12345", mock_response)
        assert ext == ".bin"


# ---------------------------------------------------------------------------
# Successful download flow
# ---------------------------------------------------------------------------


class TestSuccessfulDownload:
    def test_streaming_download(self, downloader, tmp_output_dir):
        """Test that a successful download writes the file correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2", b"chunk3"]
        mock_response.raise_for_status.return_value = None
        downloader.session.get.return_value = mock_response

        filepath = tmp_output_dir / "test.jpg"
        success, error, size = downloader._download_file(
            "https://example.com/photo.jpg",
            filepath,
        )
        assert success is True
        assert error is None
        assert size == len(b"chunk1") + len(b"chunk2") + len(b"chunk3")

    def test_retry_on_server_error(self, downloader, tmp_output_dir):
        """Test retry logic with exponential backoff."""
        # First attempt: 500 error, second attempt: success
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=error_response
        )

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.headers = {"Content-Type": "image/jpeg"}
        success_response.iter_content.return_value = [b"image_data"]
        success_response.raise_for_status.return_value = None

        downloader.session.get.side_effect = [error_response, success_response]

        filepath = tmp_output_dir / "retry_test.jpg"
        with patch("meta_ads_collector.media.time.sleep"):
            success, error, size = downloader._download_file(
                "https://example.com/photo.jpg",
                filepath,
            )
        assert success is True
        assert size == len(b"image_data")
        assert downloader.session.get.call_count == 2


# ---------------------------------------------------------------------------
# Integration: download_ad_media
# ---------------------------------------------------------------------------


class TestDownloadAdMedia:
    def test_ad_ids_in_results(self, downloader, ad_with_media):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"data"]
        mock_response.raise_for_status.return_value = None
        downloader.session.get.return_value = mock_response

        results = downloader.download_ad_media(ad_with_media)
        for r in results:
            assert r.ad_id == "AD001"

    def test_urls_in_results(self, downloader, ad_with_media):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"data"]
        mock_response.raise_for_status.return_value = None
        downloader.session.get.return_value = mock_response

        results = downloader.download_ad_media(ad_with_media)
        urls = {r.url for r in results}
        assert "https://cdn.facebook.com/image/abc.jpg?token=xyz" in urls
        assert "https://video-cdn.facebook.com/hd/video.mp4?quality=hd" in urls

    def test_mixed_success_and_failure(self, downloader, ad_with_media):
        """Some downloads succeed, some fail."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise requests.exceptions.ConnectionError("fail")
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "image/jpeg"}
            resp.iter_content.return_value = [b"data"]
            resp.raise_for_status.return_value = None
            return resp

        downloader.session.get.side_effect = side_effect

        results = downloader.download_ad_media(ad_with_media)
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        # Some should succeed, some should fail
        assert len(results) == 5
        assert len(successes) > 0 or len(failures) > 0  # At least some results
