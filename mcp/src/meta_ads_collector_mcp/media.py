"""Bound downloads while delegating asset handling to the core downloader."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit


class MediaSession:
    def __init__(self, session, max_file_bytes: int, max_total_bytes: int, max_files: int = 100):
        self.session = session
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_files = max_files
        self.bytes = 0
        self.files = 0

    def get(self, url: str, **kwargs):
        kwargs["allow_redirects"] = False
        for _ in range(6):
            self.validate_url(url)
            if self.files >= self.max_files:
                raise ValueError("Media request budget reached")
            self.files += 1
            response = self.session.get(url, **kwargs)
            if getattr(response, "status_code", 200) not in (301, 302, 303, 307, 308):
                return BoundedResponse(response, self)
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("Media redirect has no destination")
            url = urljoin(url, location)
        raise ValueError("Media redirect budget reached")

    @staticmethod
    def validate_url(url):
        host = (urlsplit(url).hostname or "").lower()
        if urlsplit(url).scheme != "https" or not any(
            host == suffix or host.endswith("." + suffix) for suffix in ("fbcdn.net", "fbsbx.com", "facebook.com")
        ):
            raise ValueError("Only Meta-hosted HTTPS media is supported")


class BoundedResponse:
    def __init__(self, response, limits):
        self.response = response
        self.limits = limits

    def __getattr__(self, name):
        return getattr(self.response, name)

    def iter_content(self, chunk_size):
        size = 0
        try:
            for chunk in self.response.iter_content(chunk_size=chunk_size):
                size += len(chunk)
                self.limits.bytes += len(chunk)
                if size > self.limits.max_file_bytes or self.limits.bytes > self.limits.max_total_bytes:
                    raise ValueError("Media byte budget reached")
                yield chunk
        finally:
            self.response.close()
