# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.3] - 2026-10-01

### Fixed
- Mark yielded ads as seen before returning them to callers, and do not advance the persistent last-run time for interrupted, failed, or result-limited searches.
- Make `max_results=0` return no ads without a request; reject negative and non-integer result limits.
- Propagate progress callback exceptions instead of misclassifying them as ad parse failures and silently dropping ads.
- Run async collector unit tests without an unrelated `httpx` installation gate.

## [1.4.2] - 2026-09-29

### Fixed
- Escape unsupported Unicode characters in page-search CLI output so Windows consoles with legacy encodings can print every page result without failing.

## [1.4.1] - 2026-09-29

### Fixed
- Added `requests` to the development extras so the proxy parsing tests can run after installing `.[dev]`.

## [1.4.0] - 2026-07-22

### Fixed
- **Collector completely broken by Meta Ad Library page gating.** Meta now serves HTTP 403 with a JS challenge for `GET /ads/library/` to non-browser HTTP clients, so the session bootstrap could no longer scrape tokens from that page. Every search then failed on the first request with the misleading error `1675004 "Rate limit exceeded"` because the client was submitting *fabricated* tokens (random `lsd`, stale hardcoded `__dyn`/`__csr`).
- **New session bootstrap: facebook.com homepage.** `initialize()` now mines the session from `GET https://www.facebook.com/`, which still returns 200 logged-out: the response sets the real session cookies (`datr`, `fr`, `sb` — "cookie mining") and its HTML embeds a genuine `lsd` token, build revision, and `hsi`. The Ad Library GraphQL API works fully logged-out with these mined tokens — verified live (search, cursor pagination, typeahead, page enumeration).
- **Fail loudly instead of poisoning requests.** A missing `lsd` now raises `AuthenticationError` at init rather than silently generating a random one (the root cause of the bogus "rate limit" errors). `fb_dtsg`, `__dyn`, and `__csr` are never fabricated; they are only sent when genuinely extracted, and the logged-out GraphQL endpoint does not require them.
- **`get_ad_details`** now uses the page-scoped GraphQL search as its primary path (the ad detail HTML page also 403s non-browser clients); the HTML scrape remains as a best-effort fallback.

### Added
- **Bring-your-own cookies.** `MetaAdsClient`, `MetaAdsCollector`, `AsyncMetaAdsClient`, and `AsyncMetaAdsCollector` accept a new optional `cookies` parameter (`{name: value}` dict or `"k=v; ..."` string) to reuse cookies from a logged-in browser session. Fresh tokens are still mined automatically via the homepage bootstrap, and the cookies are re-applied after every session refresh.

### Changed
- Same fixes applied to the async client (`AsyncMetaAdsClient`), keeping it in mirror with the sync client.
- Deprecated the unused `FALLBACK_DYN` / `FALLBACK_CSR` constants (no longer sent in payloads).
- Tests: 21 new tests covering the homepage bootstrap, token non-fabrication, and the `cookies` parameter (788 passed total).

## [1.3.0] - 2026-02-21

### Changed
- **curl_cffi is now the sole HTTP dependency.** Removed `requests` and `httpx` entirely. Facebook blocks any HTTP client without Chrome-like TLS fingerprints, so `curl_cffi` (with `impersonate="chrome"`) is the only backend that actually works. Both `requests` and `httpx` were dead-weight fallbacks that failed with HTTP 403.
- **Simplified installation.** `pip install meta-ads-collector` now includes everything -- no more `[stealth]` or `[async]` extras needed.
- **Async client simplified.** Removed the `_AsyncResponse` wrapper and httpx fallback code paths. The async client now uses `curl_cffi.AsyncSession` directly.
- Renamed `ProxyPool.get_requests_proxies()` to `get_proxy_dict()`.

### Removed
- `requests` dependency (was required, now removed)
- `httpx` dependency and `[async]` optional extra
- `[stealth]` optional extra (curl_cffi is now always installed)
- `types-requests` from dev dependencies

## [1.2.0] - 2026-02-21

### Fixed
- **Async client**: Rewrote to use `curl_cffi.AsyncSession` for TLS fingerprint impersonation, fixing 403 blocks from Facebook. Falls back to `httpx.AsyncClient` when curl_cffi is not installed.
- **Async client**: Added 403 verification challenge handling (same as sync client), enabling the async client to work without proxies.
- **Political ads parsing**: Fixed `'str' object has no attribute 'get'` crash when parsing political ads where `spend` is a string (e.g., `"$9K-$10K"`) instead of a dict.
- **Impression text parsing**: Handle `impressions_with_index` format (`{"impressions_text": ">1M", "impressions_index": 39}`) returned for political ads.
- **Publisher platform**: Added `publisher_platform` (singular) key lookup alongside plural `publisher_platforms`.
- **Delivery dates**: Added `start_date`/`end_date` key lookups for delivery times.
- **Reach parsing**: Added `_parse_reach` classmethod to handle `reach`/`reach_estimate` in string and dict formats.
- **Audience distributions**: Added `isinstance(item, dict)` guards for demographic and region distribution parsing.
- **Estimated audience size**: Added `isinstance(dict)` check before calling `.get()`.

### Changed
- **Python 3.9 compatibility**: Added `from __future__ import annotations` to `models.py` and modernized all type annotations from `Optional[X]` to `X | None`.
- **Async transport**: The async client now prefers `curl_cffi.AsyncSession` over `httpx.AsyncClient` when both are installed, matching the sync client's TLS impersonation behavior.

## [1.1.0] - 2026-02-21

### Changed
- Version bump for PyPI release.

## [1.0.0] - 2026-02-08

### Added

#### Core
- `MetaAdsCollector` high-level interface with `search()`, `collect()`, and export methods
- `MetaAdsClient` low-level HTTP client with session management and GraphQL request handling
- Browser fingerprint randomization across Chrome versions, platforms, viewports, and DPR values
- Dynamic `doc_id` extraction from Ad Library page HTML with hardcoded fallbacks
- Token extraction (LSD, CSRF, session IDs) with verification and fallback generation
- Automatic session refresh on 403 responses with configurable max refresh attempts
- Session staleness detection with 30-minute max age
- Challenge/verification handling for Facebook's bot detection

#### Search & Collection
- Keyword search, exact phrase search, and page-level search modes
- Page-level collection by URL (`collect_by_page_url`), by name (`collect_by_page_name`), and by ID (`collect_by_page_id`)
- Typeahead page search (`search_pages`) for resolving page names to IDs
- URL parser for extracting page IDs from Ad Library URLs, profile URLs, and numeric paths
- Pagination with cursor-based traversal
- Configurable page size, max results, sort order, and country
- Ad type filtering: all, political, housing, employment, credit
- Status filtering: active, inactive, all
- Ad enrichment via detail/snapshot endpoint (`enrich_ad`)
- Stream mode yielding lifecycle events alongside ads (`stream`)

#### Filtering
- `FilterConfig` dataclass with 11 filter fields
- Impression range filters (min/max using conservative bound logic)
- Spend range filters (min/max)
- Date range filters (start_date, end_date)
- Media type filter (image, video, meme, none)
- Publisher platform filter (facebook, instagram, messenger, audience_network)
- Language filter
- Boolean filters: has_video, has_image
- AND logic across all filters with missing-data-inclusive policy

#### Deduplication
- `DeduplicationTracker` with two modes: in-memory and persistent (SQLite)
- `has_seen()` and `mark_seen()` for ad ID tracking
- `get_last_collection_time()` and `update_collection_time()` for incremental collection
- Context manager protocol with automatic save on exit
- `count()` and `clear()` utility methods

#### Media Downloads
- `MediaDownloader` for downloading images, videos, and thumbnails from ad creatives
- `MediaDownloadResult` frozen dataclass with success/failure details
- File extension detection from URL path and Content-Type headers
- Retry with exponential backoff on download failures
- Skip-existing-file optimization
- `collect_with_media()` convenience method on the collector
- `download_ad_media()` for single-ad media downloads

#### Events & Webhooks
- `EventEmitter` with synchronous callback dispatch and exception isolation
- 7 lifecycle event types: collection_started, ad_collected, page_fetched, error_occurred, rate_limited, session_refreshed, collection_finished
- `Event` dataclass with event_type, data payload, and UTC timestamp
- Convenience callback registration via `callbacks` parameter on collector init
- `WebhookSender` for POSTing ad data to external HTTP endpoints
- Retry with exponential backoff on webhook failures
- Optional batch mode for webhook sends

#### Async Support
- `AsyncMetaAdsClient` with `curl_cffi.AsyncSession`
- `AsyncMetaAdsCollector` mirroring the sync API with `async for` generators
- Async `search()`, `collect()`, `collect_to_json()`, `collect_to_csv()`, `search_pages()`

#### Proxy Support
- Single proxy configuration (host:port or host:port:user:pass)
- `ProxyPool` with round-robin selection across multiple proxies
- Per-proxy failure tracking with configurable max failures threshold
- Dead proxy cooldown with automatic revival
- `ProxyPool.from_file()` for loading proxies from text files
- Proxy URL format detection (plain, URL, SOCKS5)

#### Export
- JSON export with metadata envelope (query, country, stats, timestamps)
- CSV export with 25-column flattened schema
- JSONL export (one JSON object per line)
- Export methods: `collect_to_json()`, `collect_to_csv()`, `collect_to_jsonl()`

#### Logging & Reporting
- `setup_logging()` with text or JSON format selection
- `JSONFormatter` producing single-line JSON log records
- Optional file handler with automatic directory creation
- `CollectionReport` dataclass with throughput metrics
- `format_report()` for human-readable summary text
- `format_report_json()` for machine-readable JSON output

#### Data Models
- `Ad` dataclass with 30+ fields covering all Ad Library data
- `AdCreative` with body, title, description, link URL, image/video URLs, CTA
- `PageInfo` with ID, name, profile picture, URL, likes, verification status
- `PageSearchResult` for typeahead search results
- `ImpressionRange` and `SpendRange` with lower/upper bounds
- `AudienceDistribution` for demographic and regional data
- `SearchResult` for paginated result sets
- `Ad.from_graphql_response()` parser handling multiple response formats

#### CLI
- Full CLI with 35+ flags via argparse
- All search parameters, filtering, proxy, dedup, media, enrichment, webhook, logging, and reporting flags
- `python -m meta_ads_collector` entry point
- `meta-ads-collector` console script
- Page search mode (`--search-pages`)
- Page collection modes (`--page-url`, `--page-name`)

#### Exceptions
- `MetaAdsError` base exception
- `AuthenticationError` for session/token failures
- `RateLimitError` with retry_after attribute
- `SessionExpiredError` for unrecoverable session failures
- `ProxyError` for proxy configuration issues
- `InvalidParameterError` with param name, value, and allowed values

#### Infrastructure
- PEP 561 `py.typed` marker for type checking support
- CI pipeline with Python 3.9-3.13 matrix testing
- Automated PyPI publishing on GitHub release
- 642 tests covering all modules

[1.0.0]: https://github.com/Yossef/meta-ads-collector/releases/tag/v1.0.0
