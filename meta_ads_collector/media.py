"""Media downloading infrastructure for Meta Ad Library creatives.

Provides :class:`MediaDownloader` for downloading images, videos, and
thumbnails referenced in :class:`~meta_ads_collector.models.AdCreative`
objects.  Every public method in this module is designed to **never raise
exceptions** to the caller.  Download failures are captured as structured
:class:`MediaDownloadResult` objects so that the core collection pipeline
is never disrupted.
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from curl_cffi.requests import Session as CffiSession
from curl_cffi.requests.exceptions import ConnectionError as CffiConnectionError
from curl_cffi.requests.exceptions import HTTPError as CffiHTTPError
from curl_cffi.requests.exceptions import Timeout as CffiTimeout

from .models import Ad

logger = logging.getLogger(__name__)

# ── Extension helpers ────────────────────────────────────────────────────

# Recognised file extensions that can be detected from URL paths.
_URL_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
    ".mp4", ".webm", ".avi", ".mov", ".m4v", ".mkv",
})

# Content-Type header to file extension mapping.
_CONTENT_TYPE_MAP: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
    "application/octet-stream": ".bin",
}

# Mapping from AdCreative field names to media type labels.
_MEDIA_FIELDS: list[tuple[str, str]] = [
    ("image_url", "image"),
    ("video_hd_url", "video_hd"),
    ("video_sd_url", "video_sd"),
    ("thumbnail_url", "thumbnail"),
]

# Streaming chunk size (64 KiB).
_CHUNK_SIZE: int = 65_536


def detect_extension_from_url(url: str) -> str | None:
    """Detect a file extension from the URL path.

    Parses the URL to extract the path component, then checks for a
    recognisable extension.  Query strings, fragments, and CDN path
    prefixes are handled correctly.

    Args:
        url: The URL to inspect.

    Returns:
        A lowercase extension string (e.g. ``".jpg"``) or ``None`` if no
        recognisable extension was found.
    """
    try:
        parsed = urlparse(url)
        path = parsed.path
        # Extract the last component of the path
        if "." in path:
            # Handle cases like /path/to/image.jpg?token=abc
            ext = Path(path).suffix.lower()
            if ext in _URL_EXTENSIONS:
                return ext
    except Exception:
        pass
    return None


def detect_extension_from_content_type(content_type: str | None) -> str | None:
    """Map a Content-Type header value to a file extension.

    Args:
        content_type: The ``Content-Type`` header value (may include
            charset parameters, e.g. ``"image/jpeg; charset=utf-8"``).

    Returns:
        A lowercase extension string or ``None`` if the content type is
        not recognised.
    """
    if not content_type:
        return None
    # Strip parameters (e.g. "; charset=utf-8")
    mime = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_MAP.get(mime)


# ── Result dataclass ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class MediaDownloadResult:
    """Structured result of a single media download attempt.

    Attributes:
        ad_id: The archive ID of the ad.
        creative_index: Zero-based index of the creative within the ad.
        media_type: One of ``'image'``, ``'video_hd'``, ``'video_sd'``,
            ``'thumbnail'``.
        url: The source URL that was attempted.
        local_path: Absolute path to the downloaded file, or ``None`` on
            failure.
        success: Whether the download completed successfully.
        error: Human-readable error message on failure, ``None`` on
            success.
        file_size: Number of bytes written on success, ``None`` on
            failure.
    """

    ad_id: str
    creative_index: int
    media_type: str
    url: str
    local_path: str | None = None
    success: bool = False
    error: str | None = None
    file_size: int | None = None


# ── Downloader class ─────────────────────────────────────────────────────


class MediaDownloader:
    """Downloads media files referenced in ad creatives.

    Designed to be used alongside
    :class:`~meta_ads_collector.collector.MetaAdsCollector`.  When a
    ``session`` is provided the downloader shares cookies, proxies, and
    headers with the collector for consistency.

    Args:
        output_dir: Directory where downloaded files are stored.  Created
            automatically if it does not exist.
        session: An optional ``curl_cffi`` :class:`Session` to reuse.
            When ``None`` a fresh session is created.
        timeout: Per-request timeout in seconds.
        max_retries: Maximum retry attempts for a single download.
    """

    def __init__(
        self,
        output_dir: str | Path,
        session: CffiSession | None = None,
        timeout: int = 30,
        max_retries: int = 2,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or CffiSession(impersonate="chrome")
        self.timeout = timeout
        self.max_retries = max_retries

    # ── Internal helpers ─────────────────────────────────────────────

    def _resolve_extension(self, url: str, response: Any = None) -> str:
        """Determine the file extension for a downloaded resource.

        Priority order:
        1. Recognisable extension in the URL path.
        2. ``Content-Type`` header from *response*.
        3. Fallback: ``".bin"``.
        """
        ext = detect_extension_from_url(url)
        if ext:
            return ext
        if response is not None:
            ext = detect_extension_from_content_type(response.headers.get("Content-Type"))
            if ext:
                return ext
        return ".bin"

    def _build_filename(self, ad_id: str, creative_index: int, media_type: str, ext: str) -> str:
        """Build the local filename for a media download.

        Convention: ``{ad_id}_{creative_index}_{media_type}.{ext}``
        """
        return f"{ad_id}_{creative_index}_{media_type}{ext}"

    def _download_file(
        self,
        url: str,
        local_path: Path,
    ) -> tuple[bool, str | None, int | None]:
        """Download a single file from *url* to *local_path*.

        Returns:
            A tuple of ``(success, error_message, file_size)``.  **Never
            raises** -- all exceptions are caught and returned as error
            strings.
        """
        # Skip if file already exists with non-zero size
        try:
            if local_path.exists() and local_path.stat().st_size > 0:
                size = local_path.stat().st_size
                logger.debug("Skipping existing file: %s (%d bytes)", local_path, size)
                return True, None, size
        except Exception as exc:
            # Stat failures should not prevent a download attempt
            logger.debug("Could not stat existing file %s: %s", local_path, exc)

        last_error: str | None = None

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    url, stream=True, timeout=self.timeout, allow_redirects=True,
                )
                response.raise_for_status()

                # Resolve extension *after* the first response so we can
                # use Content-Type.  If the extension changed, update the
                # local_path accordingly.
                ext = self._resolve_extension(url, response)
                if local_path.suffix != ext:
                    local_path = local_path.with_suffix(ext)

                bytes_written = 0
                with open(local_path, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                        if chunk:
                            fh.write(chunk)
                            bytes_written += len(chunk)

                if bytes_written == 0:
                    last_error = "Downloaded file is empty (0 bytes)"
                    logger.warning("Empty download for %s", url)
                    # Remove the empty file
                    with contextlib.suppress(Exception):
                        local_path.unlink(missing_ok=True)
                    continue

                logger.debug("Downloaded %s (%d bytes)", local_path, bytes_written)
                return True, None, bytes_written

            except CffiHTTPError as exc:
                status = getattr(exc, "response", None)
                status = getattr(status, "status_code", None) if status else None
                last_error = f"HTTP {status}: {exc}"
                if status == 403:
                    logger.warning("URL likely expired (403 Forbidden): %s", url)
                    # No point retrying an expired token
                    return False, last_error, None
                logger.warning(
                    "HTTP error on attempt %d/%d for %s: %s",
                    attempt + 1, self.max_retries, url, exc,
                )
            except CffiConnectionError as exc:
                last_error = f"Connection error: {exc}"
                logger.warning(
                    "Connection error on attempt %d/%d for %s: %s",
                    attempt + 1, self.max_retries, url, exc,
                )
            except CffiTimeout as exc:
                last_error = f"Timeout: {exc}"
                logger.warning(
                    "Timeout on attempt %d/%d for %s: %s",
                    attempt + 1, self.max_retries, url, exc,
                )
            except OSError as exc:
                last_error = f"IO error: {exc}"
                logger.warning("IO error writing %s: %s", local_path, exc)
                # IO errors are unlikely to resolve with retries
                return False, last_error, None
            except Exception as exc:
                last_error = f"Unexpected error: {exc}"
                logger.warning(
                    "Unexpected error on attempt %d/%d for %s: %s",
                    attempt + 1, self.max_retries, url, exc,
                )

            # Exponential backoff between retries
            if attempt < self.max_retries - 1:
                backoff = 1.0 * (2 ** attempt)
                time.sleep(backoff)

        return False, last_error, None

    # ── Public API ───────────────────────────────────────────────────

    def download_ad_media(self, ad: Ad) -> list[MediaDownloadResult]:
        """Download all available media from all creatives of an ad.

        Iterates over each creative in ``ad.creatives`` and attempts to
        download every available media URL (image, video HD, video SD,
        thumbnail).  Skips ``None`` or empty URLs.

        Args:
            ad: An :class:`~meta_ads_collector.models.Ad` instance.

        Returns:
            A list of :class:`MediaDownloadResult` objects (one per
            attempted download).  Both successes and failures are
            included.  **Never raises.**
        """
        results: list[MediaDownloadResult] = []

        try:
            for idx, creative in enumerate(ad.creatives):
                for field_name, media_type in _MEDIA_FIELDS:
                    url = getattr(creative, field_name, None)
                    if not url:
                        continue

                    try:
                        # Pre-resolve extension from URL for the initial filename
                        ext = detect_extension_from_url(url) or ".bin"
                        filename = self._build_filename(ad.id, idx, media_type, ext)
                        local_path = self.output_dir / filename

                        success, error, file_size = self._download_file(url, local_path)

                        # The actual local_path may have changed extension
                        # after Content-Type resolution.  Check what exists.
                        actual_path: str | None = None
                        if success:
                            # Find the file (extension may have changed)
                            pattern = f"{ad.id}_{idx}_{media_type}.*"
                            matches = list(self.output_dir.glob(pattern))
                            actual_path = str(matches[0]) if matches else str(local_path)

                        results.append(MediaDownloadResult(
                            ad_id=ad.id,
                            creative_index=idx,
                            media_type=media_type,
                            url=url,
                            local_path=actual_path,
                            success=success,
                            error=error,
                            file_size=file_size,
                        ))

                    except Exception as exc:
                        logger.warning(
                            "Failed to process media %s for ad %s creative %d: %s",
                            media_type, ad.id, idx, exc,
                        )
                        results.append(MediaDownloadResult(
                            ad_id=ad.id,
                            creative_index=idx,
                            media_type=media_type,
                            url=url,
                            success=False,
                            error=f"Processing error: {exc}",
                        ))

        except Exception as exc:
            logger.warning("Failed to iterate creatives for ad %s: %s", ad.id, exc)

        return results
