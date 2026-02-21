# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- `AsyncMetaAdsClient` with `curl_cffi.AsyncSession` (preferred) or `httpx.AsyncClient` (fallback)
- `AsyncMetaAdsCollector` mirroring the sync API with `async for` generators
- Async `search()`, `collect()`, `collect_to_json()`, `collect_to_csv()`, `search_pages()`
- Optional dependency: `pip install meta-ads-collector[stealth]` (recommended) or `pip install meta-ads-collector[async]`

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
