"""Generic Meta CDN host fallback inside the media retry budget."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CffiConnectionError
from curl_cffi.requests.exceptions import HTTPError as CffiHTTPError

from meta_ads_collector.media import MediaDownloader, fallback_media_url

REGIONAL = "https://scontent.fcai19-2.fna.fbcdn.net/v/t39.35426-6/5170_n.jpg?stp=dst-jpg_s600x600_tt6&_nc_cat=108&oh=00_abc&oe=6ADF"
GENERIC = "https://scontent.xx.fbcdn.net/v/t39.35426-6/5170_n.jpg?stp=dst-jpg_s600x600_tt6&_nc_cat=108&oh=00_abc&oe=6ADF"


def _ok_response(payload=b"meta-media-bytes"):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "image/jpeg"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = iter([payload])
    return response


@pytest.mark.parametrize("url, expected", [
    (REGIONAL, GENERIC),
    ("https://scontent-dus1-1.xx.fbcdn.net/v/a.jpg?oh=1", "https://scontent.xx.fbcdn.net/v/a.jpg?oh=1"),
    ("https://video.fcai19-2.fna.fbcdn.net/o1/v/t2/clip.mp4?efg=x", "https://video.xx.fbcdn.net/o1/v/t2/clip.mp4?efg=x"),
    ("https://video-dus1-1.xx.fbcdn.net/o1/v/t2/clip.mp4", "https://video.xx.fbcdn.net/o1/v/t2/clip.mp4"),
    (GENERIC, None),
    ("https://video.xx.fbcdn.net/o1/v/t2/clip.mp4", None),
    ("https://cdn.example.com/image.jpg", None),
    ("https://fbcdn.net.evil.example/image.jpg", None),
    ("https://scontent.fcai19-2.fna.fbcdn.net:8443/v/a.jpg", None),
    ("not a url", None),
])
def test_fallback_media_url_targets_the_generic_meta_cdn_host_only(url, expected):
    assert fallback_media_url(url) == expected


def test_download_recovers_on_the_generic_host_after_a_regional_edge_failure(tmp_path):
    session = MagicMock()
    session.get.side_effect = [CffiConnectionError("CONNECT tunnel failed, response 590", code=7), _ok_response()]
    downloader = MediaDownloader(tmp_path, session=session, max_retries=2)

    success, error, size = downloader._download_file(REGIONAL, tmp_path / "ad_0_image.jpg")

    assert (success, error, size) == (True, None, len(b"meta-media-bytes"))
    assert [call.args[0] for call in session.get.call_args_list] == [REGIONAL, GENERIC]
    assert (tmp_path / "ad_0_image.jpg").read_bytes() == b"meta-media-bytes"


def test_download_alternates_hosts_within_the_configured_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("meta_ads_collector.media.time.sleep", lambda _seconds: None)
    session = MagicMock()
    session.get.side_effect = CffiConnectionError("CONNECT tunnel failed, response 590", code=7)
    downloader = MediaDownloader(tmp_path, session=session, max_retries=3)

    success, error, size = downloader._download_file(REGIONAL, tmp_path / "ad_0_image.jpg")

    assert success is False and size is None
    assert "590" in error
    assert [call.args[0] for call in session.get.call_args_list] == [REGIONAL, GENERIC, REGIONAL]
    assert not list(tmp_path.iterdir())


def test_download_keeps_the_original_host_for_non_meta_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("meta_ads_collector.media.time.sleep", lambda _seconds: None)
    session = MagicMock()
    session.get.side_effect = [CffiConnectionError("reset", code=56), _ok_response()]
    downloader = MediaDownloader(tmp_path, session=session, max_retries=2)
    url = "https://cdn.example.com/image.jpg"

    assert downloader._download_file(url, tmp_path / "ad_0_image.jpg")[0] is True
    assert [call.args[0] for call in session.get.call_args_list] == [url, url]


def test_expired_url_does_not_retry_on_the_generic_host(tmp_path):
    response = MagicMock(status_code=403)
    error = CffiHTTPError("403 Forbidden")
    error.response = response
    response.raise_for_status.side_effect = error
    session = MagicMock()
    session.get.return_value = response
    downloader = MediaDownloader(tmp_path, session=session, max_retries=3)

    success, message, _size = downloader._download_file(REGIONAL, tmp_path / "ad_0_image.jpg")

    assert success is False and "403" in message
    assert session.get.call_count == 1
