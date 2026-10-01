"""Live I/O checks using real public Meta Ad Library results and media URLs.

These are deliberately bounded and run only with the integration suite.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from meta_ads_collector.media import MediaDownloader

pytestmark = pytest.mark.integration


def _one_live_thumbnail_or_image(collected_ads):
    """Keep one actual small asset returned by Meta for bounded downloads."""
    for original in collected_ads:
        for creative in original.creatives:
            url = creative.thumbnail_url or creative.image_url
            if url:
                from meta_ads_collector.models import Ad, AdCreative

                return Ad(id=original.id, creatives=[AdCreative(image_url=url)])
    pytest.skip("Meta returned no image or thumbnail for this live sample")


def test_live_relative_media_directory_reports_an_absolute_path(tmp_path, monkeypatch, collected_ads):
    """Reproduce the documented path contract using a real Meta CDN transfer."""
    ad = _one_live_thumbnail_or_image(collected_ads)
    monkeypatch.chdir(tmp_path)
    downloader = MediaDownloader("relative-live-media", timeout=30)
    try:
        result = downloader.download_ad_media(ad)[0]
    finally:
        downloader.session.close()
    assert result.success, result.error
    assert result.local_path is not None
    assert Path(result.local_path).is_absolute()


@pytest.mark.parametrize("failures", [1, 3], ids=["recovers", "exhausts"])
def test_live_meta_media_with_controlled_proxy_connect_590_is_bounded(
    collected_ads, tmp_path, monkeypatch, failures,
):
    """Inject the observed proxy failure; recovery transfers actual Meta bytes."""
    from curl_cffi.requests.exceptions import ConnectionError

    ad = _one_live_thumbnail_or_image(collected_ads)
    downloader = MediaDownloader(tmp_path / "proxy-590", timeout=30, max_retries=3)
    real_get = downloader.session.get
    requests = []

    def first_proxy_failure_then_real_meta(url, **kwargs):
        requests.append(url)
        if len(requests) <= failures:
            raise ConnectionError("CONNECT tunnel failed, response 590", code=7)
        return real_get(url, **kwargs)

    monkeypatch.setattr(downloader.session, "get", first_proxy_failure_then_real_meta)
    try:
        result = downloader.download_ad_media(ad)[0]
    finally:
        downloader.session.close()
    assert all(url == ad.creatives[0].image_url for url in requests)
    if failures == 1:
        assert len(requests) == 2
        assert result.success, result.error
        assert result.file_size == Path(result.local_path).stat().st_size > 0
    else:
        assert len(requests) == 3
        assert not result.success
        assert "CONNECT tunnel failed, response 590" in result.error
        assert not list(downloader.output_dir.iterdir())


def test_live_page_collection_downloads_media_when_cli_flag_is_set(tmp_path, collected_ads):
    """Request a real Meta page and verify its returned creative is downloaded."""
    source = next(ad for ad in collected_ads if ad.page and ad.page.id)
    page_url = f"https://www.facebook.com/ads/library/?view_all_page_id={source.page.id}"
    output = tmp_path / "page-with-media.json"
    media_dir = tmp_path / "page-media"
    command = _run_cli(output, "--page-url", page_url, "--download-media", "--media-dir", str(media_dir))
    assert command.returncode == 0, command.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ads"]
    urls = [creative.get(key) for ad in payload["ads"] for creative in ad["creatives"]
            for key in ("image_url", "video_hd_url", "video_sd_url", "thumbnail_url") if creative.get(key)]
    if not urls:
        pytest.skip("Meta returned no downloadable creative for the selected page")
    assert media_dir.is_dir(), "CLI ignored --download-media for a real page with downloadable creative URLs"
    assert list(media_dir.iterdir())


def _run_cli(output: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "meta_ads_collector", *args, "--max-results", "1", "-o", str(output)],
        capture_output=True,
        text=True,
        # An ad can contain several real media assets; the subprocess budget
        # covers their individual retry/transfer budgets as well as search.
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("extension", ["json", "csv", "jsonl"])
def test_live_cli_exports_real_meta_ads_in_supported_formats(
    tmp_path: Path, extension: str,
) -> None:
    """Each CLI export format writes a bounded result from a real query."""
    output = tmp_path / f"nike.{extension}"
    result = _run_cli(output, "--query", "Nike", "--country", "US")

    assert result.returncode == 0, result.stderr
    assert output.exists()
    if extension == "json":
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["metadata"]["total_count"] == 1
        assert payload["ads"][0]["id"]
    elif extension == "jsonl":
        rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["id"]
    else:
        with output.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1
        assert rows[0]["id"]


def test_live_cli_page_url_exports_ads_for_a_real_meta_page(tmp_path: Path, collected_ads) -> None:
    ad = next((candidate for candidate in collected_ads if candidate.page and candidate.page.id), None)
    if ad is None:
        pytest.skip("live sample has no page ID for page-url collection")
    output = tmp_path / "page.json"
    page_url = f"https://www.facebook.com/ads/library/?view_all_page_id={ad.page.id}"

    result = _run_cli(output, "--page-url", page_url)

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert 1 <= payload["total_count"] <= 1
    assert payload["ads"][0]["page"]["id"] == ad.page.id


def test_live_cli_media_flag_runs_against_real_meta_search(tmp_path: Path) -> None:
    output = tmp_path / "with-media.json"
    media_dir = tmp_path / "media"

    result = _run_cli(
        output,
        "--query", "Nike", "--country", "US", "--download-media",
        "--media-dir", str(media_dir),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert 1 <= payload["total_count"] <= 1
    assert "Media download summary" in result.stderr
    # Meta may return an ad with no downloadable creative, so directory
    # existence is guaranteed by MediaDownloader while file success is
    # verified separately from the live fixture URL below.
    assert media_dir.is_dir()


def test_live_cli_enrichment_runs_for_a_real_meta_ad(tmp_path: Path) -> None:
    output = tmp_path / "enriched.json"

    result = _run_cli(output, "--query", "Nike", "--country", "US", "--enrich")

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert 1 <= payload["total_count"] <= 1
    assert payload["ads"][0]["id"]


def test_live_meta_media_download_is_cached_with_an_absolute_real_path(
    tmp_path: Path, collected_ads,
) -> None:
    """Download one real CDN asset, then verify the existing-file cache path."""
    ad = next(
        (
            candidate for candidate in collected_ads
            if any(
                creative.image_url or creative.video_hd_url or creative.video_sd_url or creative.thumbnail_url
                for creative in candidate.creatives
            )
        ),
        None,
    )
    if ad is None:
        pytest.skip("live sample contains no downloadable media URL")

    # Keep one real URL so this test performs one bounded CDN transfer.
    ad = deepcopy(ad)
    chosen = None
    for creative in ad.creatives:
        for field in ("image_url", "video_hd_url", "video_sd_url", "thumbnail_url"):
            url = getattr(creative, field)
            if chosen is None and url:
                chosen = (creative, field, url)
            elif url:
                setattr(creative, field, None)
    assert chosen is not None
    downloader = MediaDownloader(tmp_path / "live-media", timeout=45)
    try:
        first = downloader.download_ad_media(ad)
        assert len(first) == 1
        assert first[0].success is True, first[0].error
        assert first[0].local_path is not None
        local_path = Path(first[0].local_path)
        assert local_path.is_absolute()
        assert local_path.is_file()
        assert local_path.stat().st_size == first[0].file_size
        assert local_path.stat().st_size > 0

        with pytest.MonkeyPatch.context() as monkeypatch:
            real_get = downloader.session.get
            calls = 0

            def counted_get(*args, **kwargs):
                nonlocal calls
                calls += 1
                return real_get(*args, **kwargs)

            monkeypatch.setattr(downloader.session, "get", counted_get)
            second = downloader.download_ad_media(ad)

        assert second[0].success is True
        assert Path(second[0].local_path or "") == local_path
        assert calls == 0
    finally:
        downloader.session.close()

