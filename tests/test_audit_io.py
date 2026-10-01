"""Focused regression reproductions for media, CLI, webhook, and proxy I/O.

Failing assertions in this file document observed correctness/security bugs;
passing cases cover end-to-end behavior that already works.
"""

from __future__ import annotations

import errno
import json
import logging
import sys
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CffiConnectionError

from meta_ads_collector.cli import main
from meta_ads_collector.events import AD_COLLECTED, Event
from meta_ads_collector.media import MediaDownloader
from meta_ads_collector.models import Ad, AdCreative
from meta_ads_collector.proxy_pool import ProxyPool, parse_proxy
from meta_ads_collector.webhooks import WebhookSender

from .audit_meta_samples import CAPTURED_ADS


def _captured_ad() -> Ad:
    """Parse one captured real public ad with a video URL."""
    for row in CAPTURED_ADS:
        snapshot = row.get("snapshot") or {}
        if any(v.get("video_hd_url") or v.get("video_sd_url") for v in snapshot.get("videos", [])):
            merged = {**row, **snapshot}
            merged["page_id"] = row.get("page_id")
            merged["page_name"] = snapshot.get("page_name") or row.get("page_name")
            return Ad.from_graphql_response(merged)
    pytest.skip("Meta capture contains no ad with a video media URL")


def _captured_raw_ads() -> list[dict]:
    return deepcopy(CAPTURED_ADS)


def _ad(ad_id: str | None = None, video_url: str | None = None) -> Ad:
    ad = deepcopy(_captured_ad())
    if ad_id is not None:
        ad.id = ad_id
    for creative in ad.creatives:
        creative.image_url = creative.video_url = creative.video_hd_url = None
        creative.video_sd_url = creative.thumbnail_url = None
    if video_url is not None:
        ad.creatives[0].video_hd_url = video_url
    return ad


def _captured_video_url() -> str:
    ad = _captured_ad()
    for creative in ad.creatives:
        if creative.video_hd_url or creative.video_sd_url:
            # Keep the real CDN host/path but redact the signed query token;
            # controlled regression tests mock the downloader session.
            url = creative.video_hd_url or creative.video_sd_url or ""
            return url.split("?", 1)[0]
    pytest.skip("Meta capture contains no usable video URL")


def _ok_media_response(chunks: list[bytes]) -> MagicMock:
    response = MagicMock()
    response.headers = {"Content-Type": "image/jpeg"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = iter(chunks)
    return response


def test_failed_partial_media_download_is_not_reused_as_success(tmp_path: Path) -> None:
    """A partial file from a failed stream must be retried on a later run."""
    out = tmp_path / "media"
    session = MagicMock()

    def interrupted_stream():
        yield b"partial"
        raise CffiConnectionError("connection lost mid-stream")

    broken = _ok_media_response([])
    broken.iter_content.return_value = interrupted_stream()
    session.get.side_effect = [broken, _ok_media_response([b"complete-media"])]
    downloader = MediaDownloader(out, session=session, max_retries=1)
    ad = _ad(video_url=_captured_video_url())

    first = downloader.download_ad_media(ad)
    assert first[0].success is False
    assert not list(out.glob("*.part"))
    assert not (out / f"{ad.id}_0_video_hd.mp4").exists()
    second = downloader.download_ad_media(ad)

    assert session.get.call_count == 2
    assert second[0].success is True
    assert Path(second[0].local_path or "").read_bytes() == b"complete-media"


def test_media_ad_id_cannot_escape_output_directory(tmp_path: Path) -> None:
    """Ad identifiers are data and must not become path components."""
    out = tmp_path / "media"
    session = MagicMock()
    session.get.return_value = _ok_media_response([b"image"])
    downloader = MediaDownloader(out, session=session, max_retries=1)

    results = downloader.download_ad_media(
        _ad(ad_id="../925321173274919", video_url=_captured_video_url())
    )

    assert not (tmp_path / "925321173274919_0_video_hd.mp4").exists()
    # Rejecting the identifier is valid; if the operation succeeds, its
    # reported destination must still remain inside the configured directory.
    if results[0].success:
        assert Path(results[0].local_path or "").resolve().is_relative_to(out.resolve())


def test_page_collection_honors_download_media_flag(tmp_path: Path) -> None:
    """The page collection CLI path should download media when requested."""
    ad = _ad(video_url=_captured_video_url())

    class FakeCollector:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def collect_by_page_url(self, *_args, **_kwargs):
            return iter([ad])

        def download_ad_media(self, *_args, **kwargs):
            self.download_call = (ad.id, kwargs.get("output_dir", kwargs.get("media_output_dir")))
            return []

        def get_stats(self):
            return {"requests_made": 0, "pages_fetched": 0, "errors": 0}

    fake = FakeCollector()
    output = tmp_path / "page.json"
    page_url = f"https://facebook.com/ads/library/?view_all_page_id={ad.page.id}"
    with (
        patch.object(sys, "argv", [
            "prog", "--page-url", page_url,
            "--download-media", "--media-dir", str(tmp_path / "media"),
            "-o", str(output),
        ]),
        patch("meta_ads_collector.cli.MetaAdsCollector", return_value=fake),
    ):
        assert main() == 0

    assert getattr(fake, "download_call", None) == (ad.id, str(tmp_path / "media"))
    assert json.loads(output.read_text(encoding="utf-8"))["total_count"] == 1


def test_enrich_and_download_media_downloads_enriched_creative_urls(tmp_path: Path) -> None:
    """Media download should see creative URLs added by the requested enrichment."""
    raw_ad = _ad()
    enriched_url = _captured_video_url()
    for creative in raw_ad.creatives:
        creative.image_url = creative.video_url = creative.video_hd_url = None
        creative.video_sd_url = creative.thumbnail_url = None

    class FakeCollector:
        def __init__(self):
            self.downloaded_urls: list[str | None] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def search(self, **_kwargs):
            return iter([raw_ad])

        def enrich_ad(self, _ad):
            return Ad(
                id=raw_ad.id,
                page=raw_ad.page,
                creatives=[AdCreative(video_hd_url=enriched_url)],
            )

        def download_ad_media(self, ad, output_dir):
            self.downloaded_urls.append(ad.creatives[0].video_hd_url)
            return []

        def get_stats(self):
            return {"requests_made": 0, "pages_fetched": 0, "errors": 0}

    fake = FakeCollector()
    output = tmp_path / "enriched.json"
    with (
        patch.object(sys, "argv", [
            "prog", "-q", "test", "--download-media", "--enrich",
            "--media-dir", str(tmp_path / "media"), "-o", str(output),
        ]),
        patch("meta_ads_collector.cli.MetaAdsCollector", return_value=fake),
    ):
        assert main() == 0

    assert fake.downloaded_urls == [enriched_url]


def test_report_counts_duplicate_and_filtered_real_ads_from_search(tmp_path: Path) -> None:
    """The real collector search loop must report skipped duplicate/filter inputs."""
    from meta_ads_collector.collector import MetaAdsCollector as RealMetaAdsCollector
    from meta_ads_collector.filters import FilterConfig, passes_filter

    raw_ads = _captured_raw_ads()
    video_ad = next(
        (row for row in raw_ads if (row.get("snapshot") or {}).get("videos")), None,
    )
    no_video_ad = next(
        (row for row in raw_ads if not (row.get("snapshot") or {}).get("videos")), None,
    )
    if video_ad is None or no_video_ad is None:
        pytest.skip("capture needs one real video ad and one real non-video ad")

    def flatten(row: dict) -> dict:
        return {**row, **(row.get("snapshot") or {}), "page_id": row.get("page_id")}

    duplicate_row = flatten(video_ad)
    filtered_row = flatten(no_video_ad)
    search_inputs = [duplicate_row, deepcopy(duplicate_row), filtered_row]

    class ScriptedClient:
        def search_ads(self, **_kwargs):
            return {"ads": search_inputs}, None

        def close(self):
            pass

    def real_collector_factory(**kwargs):
        collector = RealMetaAdsCollector(**kwargs)
        collector.client = ScriptedClient()
        return collector

    for name in (
        "AD_TYPE_ALL", "AD_TYPE_POLITICAL", "AD_TYPE_HOUSING", "AD_TYPE_EMPLOYMENT",
        "AD_TYPE_CREDIT", "STATUS_ACTIVE", "STATUS_INACTIVE", "STATUS_ALL",
        "SEARCH_KEYWORD", "SEARCH_EXACT", "SEARCH_PAGE", "SORT_RELEVANCY",
        "SORT_IMPRESSIONS",
    ):
        setattr(real_collector_factory, name, getattr(RealMetaAdsCollector, name))

    config = FilterConfig(has_video=True)
    expected_duplicates = 1
    expected_filtered = sum(
        1 for raw in (duplicate_row, filtered_row)
        if not passes_filter(Ad.from_graphql_response(raw), config)
    )
    assert expected_filtered == 1
    report_path = tmp_path / "report.json"
    output = tmp_path / "ads.json"
    with (
        patch.object(sys, "argv", [
            "prog", "-q", "Nike", "--has-video", "--deduplicate",
            "--report-file", str(report_path), "-o", str(output),
        ]),
        patch("meta_ads_collector.cli.MetaAdsCollector", new=real_collector_factory),
    ):
        assert main() == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["duplicates_skipped"] == expected_duplicates
    assert report["filtered_out"] == expected_filtered


def test_proxy_file_configuration_failure_returns_cli_error(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing-proxies.txt"
    with patch.object(sys, "argv", [
        "prog", "-o", str(tmp_path / "ads.json"), "--proxy-file", str(missing_file),
    ]):
        assert main() == 1


def test_since_last_run_requires_state_file(tmp_path: Path) -> None:
    """The documented prerequisite must be enforced instead of ignored."""
    class FakeCollector:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def collect_to_json(self, output_path, **_kwargs):
            Path(output_path).write_text(json.dumps({"ads": [], "total_count": 0}))
            return 0

        def get_stats(self):
            return {"requests_made": 0, "pages_fetched": 0, "errors": 0}

    with patch.object(sys, "argv", [
        "prog", "-o", str(tmp_path / "ads.json"), "--since-last-run",
    ]), patch("meta_ads_collector.cli.MetaAdsCollector", return_value=FakeCollector()):
        assert main() == 1


def test_relative_output_directory_result_path_is_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful MediaDownloadResult paths are documented as absolute."""
    monkeypatch.chdir(tmp_path)
    session = MagicMock()
    session.get.return_value = _ok_media_response([b"jpeg-bytes"])
    downloader = MediaDownloader("relative-media", session=session, max_retries=1)

    result = downloader.download_ad_media(
        _ad(video_url=_captured_video_url())
    )[0]

    assert result.success is True
    assert result.local_path is not None
    assert Path(result.local_path).is_absolute()


def test_extensionless_content_type_media_reuses_resolved_cache_path(tmp_path: Path) -> None:
    """A Content-Type-derived extension should be recognized on later calls."""
    source_url = _captured_video_url()
    # Preserve a real Meta CDN host and captured asset path while dropping
    # only the suffix so the mocked Content-Type response exercises fallback.
    extensionless_url = source_url.rsplit(".", 1)[0]
    ad = _ad(video_url=extensionless_url)
    session = MagicMock()
    response = _ok_media_response([b"captured-meta-asset"])
    session.get.return_value = response
    downloader = MediaDownloader(tmp_path / "extensionless", session=session, max_retries=1)

    first = downloader.download_ad_media(ad)[0]
    second = downloader.download_ad_media(ad)[0]

    assert first.success is True
    assert second.success is True
    assert Path(first.local_path or "").suffix == ".jpg"
    assert second.local_path == first.local_path
    assert session.get.call_count == 1


def test_extensionless_media_does_not_cache_stale_partial_file(tmp_path: Path) -> None:
    """An interrupted Content-Type-named sibling is not a completed cache hit."""
    extensionless_url = _captured_video_url().rsplit(".", 1)[0]
    ad = _ad(video_url=extensionless_url)
    session = MagicMock()
    session.get.return_value = _ok_media_response([b"complete-meta-media"])
    out = tmp_path / "partial-cache"
    downloader = MediaDownloader(out, session=session, max_retries=1)
    stem = Path(downloader._build_filename(ad.id, 0, "video_hd", ".bin")).stem
    stale_part = out / f"{stem}.jpg.part"
    stale_part.write_bytes(b"interrupted-prefix")

    result = downloader.download_ad_media(ad)[0]

    assert session.get.call_count == 1
    assert result.success is True
    assert Path(result.local_path or "").read_bytes() == b"complete-meta-media"


def test_media_write_does_not_follow_preexisting_part_symlink(tmp_path: Path) -> None:
    """Atomic writes use a unique temp file instead of following a `.part` link."""
    ad = _ad(video_url=_captured_video_url())
    out = tmp_path / "symlink-part"
    downloader = MediaDownloader(out, session=MagicMock(), max_retries=1)
    destination = out / downloader._build_filename(ad.id, 0, "video_hd", ".mp4")
    stale_part = destination.with_name(destination.name + ".part")
    outside = tmp_path / "outside-part-target"
    outside.write_bytes(b"must-remain-unchanged")
    try:
        stale_part.symlink_to(outside)
    except (PermissionError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    except OSError as exc:
        if (
            exc.errno in {errno.ENOSYS, errno.EOPNOTSUPP}
            or getattr(exc, "winerror", None) == 1314
        ):
            pytest.skip(f"symlinks unavailable: {exc}")
        raise

    downloader.session.get.return_value = _ok_media_response([b"complete-meta-media"])
    result = downloader.download_ad_media(ad)[0]

    assert result.success is True
    assert outside.read_bytes() == b"must-remain-unchanged"
    assert Path(result.local_path or "").resolve().is_relative_to(out.resolve())


def test_media_cache_does_not_trust_symlink_outside_output_directory(tmp_path: Path) -> None:
    """An outside-target cache symlink is replaced without reporting its target."""
    ad = _ad(video_url=_captured_video_url())
    out = tmp_path / "symlink-cache"
    downloader = MediaDownloader(out, session=MagicMock(), max_retries=1)
    destination = out / downloader._build_filename(ad.id, 0, "video_hd", ".mp4")
    outside = tmp_path / "outside-cached-media"
    outside.write_bytes(b"outside-cache")
    try:
        destination.symlink_to(outside)
    except (PermissionError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    except OSError as exc:
        if (
            exc.errno in {errno.ENOSYS, errno.EOPNOTSUPP}
            or getattr(exc, "winerror", None) == 1314
        ):
            pytest.skip(f"symlinks unavailable: {exc}")
        raise

    downloader.session.get.return_value = _ok_media_response([b"fresh-media"])
    result = downloader.download_ad_media(ad)[0]

    assert downloader.session.get.call_count == 1
    assert result.success is True
    assert outside.read_bytes() == b"outside-cache"
    assert Path(result.local_path or "").read_bytes() == b"fresh-media"
    assert Path(result.local_path or "").resolve().is_relative_to(out.resolve())


def test_webhook_flush_keeps_real_payload_after_delivery_failure() -> None:
    """A failed localhost delivery leaves the captured ad available to retry."""
    received: list[dict] = []
    request_count = 0

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal request_count
            request_count += 1
            size = int(self.headers.get("Content-Length", "0"))
            received.append(json.loads(self.rfile.read(size)))
            self.send_response(503 if request_count == 1 else 200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    with patch("meta_ads_collector.webhooks.CffiSession"):
        sender = WebhookSender(
            f"http://127.0.0.1:{server.server_port}/ads", batch_size=10, retries=1,
        )

        # Exercise WebhookSender's actual HTTP request against localhost.
        from curl_cffi.requests import Session

        sender._session = Session(impersonate="chrome")
        real_ad = _ad().to_dict()
        callback = sender.as_callback()
        event = Event(event_type=AD_COLLECTED, data={"ad": real_ad})

        try:
            callback(event)
            callback(event)
            assert len(sender._buffer) == 2
            assert sender.flush() is False
            assert len(sender._buffer) == 2
            assert sender.flush() is True
            assert sender._buffer == []
            assert received[0] == {"ads": [real_ad, real_ad], "count": 2}
            assert received[1] == received[0]
        finally:
            sender._session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)


def test_page_collection_without_optional_features_exports_json(tmp_path: Path) -> None:
    """The regular page-url CLI path writes its yielded ads to JSON."""
    ad = _ad("925321173274919")

    class FakeCollector:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def collect_by_page_url(self, *_args, **_kwargs):
            return iter([ad])

        def get_stats(self):
            return {"requests_made": 1, "pages_fetched": 1, "errors": 0}

    output = tmp_path / "page-ads.json"
    page_url = f"https://facebook.com/ads/library/?view_all_page_id={ad.page.id}"
    with (
        patch.object(sys, "argv", [
            "prog", "--page-url", page_url,
            "-o", str(output),
        ]),
        patch("meta_ads_collector.cli.MetaAdsCollector", return_value=FakeCollector()),
    ):
        assert main() == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["total_count"] == 1
    assert payload["ads"][0]["id"] == ad.id




def test_proxy_failure_logs_do_not_disclose_credentials(caplog: pytest.LogCaptureFixture) -> None:
    proxy = "http://audit-user:audit-password@127.0.0.1:8123"
    pool = ProxyPool([proxy], max_failures=1)

    with caplog.at_level(logging.DEBUG, logger="meta_ads_collector.proxy_pool"):
        pool.mark_failure(proxy)
        pool.mark_success(proxy)

    assert "audit-user" not in caplog.text
    assert "audit-password" not in caplog.text


def test_proxy_url_preserves_percent_encoded_reserved_credentials() -> None:
    """The documented URL form can carry reserved credential characters."""
    proxy = "http://audit-user:p%40ss%3Aword@127.0.0.1:8123"

    assert parse_proxy(proxy) == proxy


def test_legacy_proxy_credentials_with_reserved_characters_are_encoded() -> None:
    proxy = "127.0.0.1:8123:audit@user:p@ss/word#frag:tail"

    assert parse_proxy(proxy) == (
        "http://audit%40user:p%40ss%2Fword%23frag%3Atail@127.0.0.1:8123"
    )


@pytest.mark.parametrize(
    ("proxy", "secrets"),
    [
        ("gopher://audit-user:audit-password@proxy.example:8080", ("audit-user", "audit-password")),
        ("http://audit-user:audit-password@proxy.example:not-a-port", ("audit-user", "audit-password")),
        ("http://audit-user:audit-password@proxy.example:70000", ("audit-user", "audit-password")),
        ("http://audit-user:audit-password@/missing-host:8080", ("audit-user", "audit-password")),
    ],
)
def test_proxy_url_validation_errors_do_not_include_credentials(
    proxy: str, secrets: tuple[str, str],
) -> None:
    from meta_ads_collector.exceptions import ProxyError

    with pytest.raises(ProxyError) as exc_info:
        parse_proxy(proxy)

    assert all(secret not in str(exc_info.value) for secret in secrets)


def test_invalid_proxy_format_error_redacts_embedded_credentials() -> None:
    from meta_ads_collector.exceptions import ProxyError

    with pytest.raises(ProxyError) as exc_info:
        parse_proxy("audit-user:audit-password:extra")

    assert "audit-user" not in str(exc_info.value)
    assert "audit-password" not in str(exc_info.value)


def test_webhook_batching_sends_all_ads_in_stable_batches() -> None:
    """A local receiver gets all batches with one real Meta ad payload."""
    received: list[dict] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            received.append(json.loads(self.rfile.read(size)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    sender = WebhookSender(
        f"http://127.0.0.1:{server.server_port}/ads", batch_size=3, retries=1,
    )
    callback = sender.as_callback()
    real_ad = _ad().to_dict()

    try:
        for _ in range(12):
            callback(Event(event_type=AD_COLLECTED, data={"ad": real_ad}))

        assert [payload["count"] for payload in received] == [3, 3, 3, 3]
        assert [ad for payload in received for ad in payload["ads"]] == [real_ad] * 12
        assert sender._buffer == []
    finally:
        sender._session.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

