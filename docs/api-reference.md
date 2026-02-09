# API Reference

Complete reference for all public classes, methods, and functions in `meta-ads-collector`.

## Table of Contents

- [Collector](#collector)
- [Async Collector](#async-collector)
- [Client](#client)
- [Async Client](#async-client)
- [Data Models](#data-models)
- [Filtering](#filtering)
- [Deduplication](#deduplication)
- [Events](#events)
- [Webhooks](#webhooks)
- [Media](#media)
- [Proxy Pool](#proxy-pool)
- [URL Parser](#url-parser)
- [Logging](#logging)
- [Reporting](#reporting)
- [Exceptions](#exceptions)
- [Constants](#constants)

---

## Collector

**Module:** `meta_ads_collector.collector`

### class MetaAdsCollector

High-level interface for searching and collecting ads from the Meta Ad Library.

Supports context manager protocol (`with` statement) for automatic resource cleanup.

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test"):
        print(ad.id)
```

#### `__init__(proxy, rate_limit_delay, jitter, timeout, max_retries, callbacks)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `proxy` | `str \| list[str] \| ProxyPool \| None` | `None` | Proxy configuration |
| `rate_limit_delay` | `float` | `2.0` | Base delay between requests (seconds) |
| `jitter` | `float` | `1.0` | Random jitter added to delay (seconds) |
| `timeout` | `int` | `30` | Request timeout (seconds) |
| `max_retries` | `int` | `3` | Maximum retry attempts per request |
| `callbacks` | `dict[str, Callable] \| None` | `None` | Event callbacks mapping `{event_type: callback}` |

#### `search(query, country, ad_type, status, search_type, page_ids, sort_by, max_results, page_size, progress_callback, filter_config, dedup_tracker) -> Iterator[Ad]`

Search for ads and yield results as an iterator.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | `""` | Search query string |
| `country` | `str` | `"US"` | ISO 3166-1 alpha-2 country code |
| `ad_type` | `str` | `"ALL"` | Ad type filter (`"ALL"`, `"POLITICAL_AND_ISSUE_ADS"`, `"HOUSING_ADS"`, `"EMPLOYMENT_ADS"`, `"CREDIT_ADS"`) |
| `status` | `str` | `"ACTIVE"` | Status filter (`"ACTIVE"`, `"INACTIVE"`, `"ALL"`) |
| `search_type` | `str` | `"KEYWORD_EXACT_PHRASE"` | Search type (`"KEYWORD_EXACT_PHRASE"`, `"KEYWORD_UNORDERED"`, `"PAGE"`) |
| `page_ids` | `list[str] \| None` | `None` | Filter by specific page IDs |
| `sort_by` | `str \| None` | `"SORT_BY_TOTAL_IMPRESSIONS"` | Sort order (`"SORT_BY_TOTAL_IMPRESSIONS"` or `None` for relevancy) |
| `max_results` | `int \| None` | `None` | Maximum ads to collect (`None` = no limit) |
| `page_size` | `int` | `10` | Results per API request (max ~30) |
| `progress_callback` | `Callable[[int, int], None] \| None` | `None` | Callback `(collected, total)` for progress |
| `filter_config` | `FilterConfig \| None` | `None` | Client-side filter configuration |
| `dedup_tracker` | `DeduplicationTracker \| None` | `None` | Deduplication tracker |

**Returns:** `Iterator[Ad]`

#### `collect(query, country, ad_type, status, search_type, page_ids, sort_by, max_results, page_size) -> list[Ad]`

Same as `search()` but returns all results as a list.

#### `collect_to_json(output_path, ..., include_raw, indent) -> int`

Collect ads and save to a JSON file. Returns the number of ads collected. All search parameters from `search()` are accepted.

Additional parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_path` | `str` | (required) | Path to the output JSON file |
| `include_raw` | `bool` | `False` | Include raw API response data |
| `indent` | `int` | `2` | JSON indentation |

#### `collect_to_csv(output_path, ...) -> int`

Collect ads and save to a CSV file. Returns the number of ads collected.

#### `collect_to_jsonl(output_path, ..., include_raw) -> int`

Collect ads and save to a JSON Lines file (one JSON object per line). Returns the number of ads collected.

#### `search_pages(query, country) -> list[PageSearchResult]`

Search for Facebook pages by name using the typeahead endpoint.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | (required) | Page name to search for |
| `country` | `str` | `"US"` | Country code |

**Returns:** `list[PageSearchResult]`

#### `collect_by_page_id(page_id, **kwargs) -> Iterator[Ad]`

Collect all ads from a specific page by its numeric ID.

#### `collect_by_page_url(url, **kwargs) -> Iterator[Ad]`

Collect all ads from a Facebook page identified by URL. Parses the URL to extract the page ID.

#### `collect_by_page_name(page_name, country, **kwargs) -> Iterator[Ad]`

Search for a page by name, then collect its ads.

#### `collect_with_media(media_output_dir, ...) -> Iterator[tuple[Ad, list[MediaDownloadResult]]]`

Search for ads and download their media files. Yields `(ad, download_results)` tuples.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `media_output_dir` | `str \| Path` | `"./ad_media"` | Directory for downloaded media |

#### `download_ad_media(ad, output_dir) -> list[MediaDownloadResult]`

Download media files for a single ad.

#### `enrich_ad(ad) -> Ad`

Fetch additional detail data from the ad detail endpoint and merge into the ad object. Returns the original ad unchanged on failure.

#### `stream(query, ...) -> Iterator[tuple[str, dict[str, Any]]]`

Stream lifecycle events as `(event_type, data)` tuples. Provides both ad data and metadata events in a single iterator.

#### `get_stats() -> dict[str, Any]`

Return collection statistics including `requests_made`, `ads_collected`, `pages_fetched`, `errors`, `start_time`, `end_time`, `duration_seconds`, `ads_per_second`.

#### `close() -> None`

Close the collector and release resources.

#### Class Constants

| Constant | Value |
|---|---|
| `AD_TYPE_ALL` | `"ALL"` |
| `AD_TYPE_POLITICAL` | `"POLITICAL_AND_ISSUE_ADS"` |
| `AD_TYPE_HOUSING` | `"HOUSING_ADS"` |
| `AD_TYPE_EMPLOYMENT` | `"EMPLOYMENT_ADS"` |
| `AD_TYPE_CREDIT` | `"CREDIT_ADS"` |
| `STATUS_ACTIVE` | `"ACTIVE"` |
| `STATUS_INACTIVE` | `"INACTIVE"` |
| `STATUS_ALL` | `"ALL"` |
| `SEARCH_KEYWORD` | `"KEYWORD_EXACT_PHRASE"` |
| `SEARCH_EXACT` | `"KEYWORD_EXACT_PHRASE"` |
| `SEARCH_UNORDERED` | `"KEYWORD_UNORDERED"` |
| `SEARCH_PAGE` | `"PAGE"` |
| `SORT_RELEVANCY` | `None` |
| `SORT_IMPRESSIONS` | `"SORT_BY_TOTAL_IMPRESSIONS"` |

---

## Async Collector

**Module:** `meta_ads_collector.async_collector`

**Requires:** `pip install meta-ads-collector[async]`

### class AsyncMetaAdsCollector

Async mirror of `MetaAdsCollector`. All methods are `async def` and iterators are `async for`.

```python
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async with AsyncMetaAdsCollector() as collector:
    async for ad in collector.search(query="test"):
        print(ad.id)
```

#### Methods

All methods mirror `MetaAdsCollector` with async signatures:

| Method | Return Type |
|---|---|
| `async search(...)` | `AsyncIterator[Ad]` |
| `async collect(...)` | `list[Ad]` |
| `async collect_to_json(...)` | `int` |
| `async collect_to_csv(...)` | `int` |
| `async search_pages(...)` | `list[PageSearchResult]` |
| `async close()` | `None` |
| `get_stats()` | `dict[str, Any]` (sync) |

---

## Client

**Module:** `meta_ads_collector.client`

### class MetaAdsClient

Low-level HTTP client for the Meta Ad Library. Manages sessions, tokens, and GraphQL requests.

#### `__init__(proxy, timeout, max_retries, retry_delay, max_refresh_attempts)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `proxy` | `str \| list[str] \| ProxyPool \| None` | `None` | Proxy configuration |
| `timeout` | `int` | `30` | Request timeout (seconds) |
| `max_retries` | `int` | `3` | Maximum retries |
| `retry_delay` | `float` | `2.0` | Base retry delay (exponential backoff) |
| `max_refresh_attempts` | `int` | `3` | Max consecutive session refresh failures |

#### `initialize() -> bool`

Initialize the client by loading the Ad Library page and extracting tokens. Returns `True` on success.

#### `search_ads(query, country, ad_type, active_status, media_type, search_type, page_ids, cursor, first, sort_direction, sort_mode, session_id, collation_token) -> tuple[dict, str | None]`

Search for ads via the GraphQL API. Returns `(response_data, next_cursor)`.

#### `search_pages(query, country) -> list[dict]`

Search for pages using the typeahead endpoint. Returns a list of page dicts.

#### `get_ad_details(ad_archive_id, page_id) -> dict`

Fetch detailed ad data. Tries the detail page first, then a page-scoped search.

#### `close() -> None`

Close the session.

---

## Async Client

**Module:** `meta_ads_collector.async_client`

**Requires:** `pip install meta-ads-collector[async]`

### class AsyncMetaAdsClient

Async mirror of `MetaAdsClient` using `httpx.AsyncClient`. All HTTP methods are async, while pure-logic methods are delegated to the sync client.

Same method signatures as `MetaAdsClient` with `async def`.

---

## Data Models

**Module:** `meta_ads_collector.models`

### class Ad

Complete ad schema with all available fields from the Meta Ad Library.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Ad Archive ID (primary identifier) |
| `ad_library_id` | `str \| None` | Ad Library ID |
| `page` | `PageInfo \| None` | Page running the ad |
| `is_active` | `bool \| None` | Whether the ad is currently active |
| `ad_status` | `str \| None` | Status string (`"ACTIVE"`, `"INACTIVE"`) |
| `delivery_start_time` | `datetime \| None` | When ad delivery started |
| `delivery_stop_time` | `datetime \| None` | When ad delivery stopped |
| `creatives` | `list[AdCreative]` | Creative content variations |
| `snapshot_url` | `str \| None` | Snapshot URL |
| `ad_snapshot_url` | `str \| None` | Alternative snapshot URL |
| `impressions` | `ImpressionRange \| None` | Impression count range |
| `spend` | `SpendRange \| None` | Spend amount range |
| `reach` | `ImpressionRange \| None` | Reach range |
| `currency` | `str \| None` | Currency code |
| `age_gender_distribution` | `list[AudienceDistribution]` | Demographic distribution |
| `region_distribution` | `list[AudienceDistribution]` | Geographic distribution |
| `targeting` | `TargetingInfo \| None` | Targeting information |
| `estimated_audience_size_lower` | `int \| None` | Estimated audience lower bound |
| `estimated_audience_size_upper` | `int \| None` | Estimated audience upper bound |
| `publisher_platforms` | `list[str]` | Platforms (facebook, instagram, etc.) |
| `languages` | `list[str]` | Content languages |
| `bylines` | `list[str]` | Political ad bylines |
| `funding_entity` | `str \| None` | Who paid for the ad |
| `disclaimer` | `str \| None` | Ad disclaimer text |
| `ad_type` | `str \| None` | Ad category type |
| `categories` | `list[str]` | Ad categories |
| `beneficiary_payers` | `list[str]` | EU transparency beneficiary/payer info |
| `collation_id` | `str \| None` | Collation group ID |
| `collation_count` | `int \| None` | Number of collated variants |
| `raw_data` | `dict \| None` | Raw API response (excluded from repr) |
| `collected_at` | `datetime` | When the ad was collected |
| `collection_source` | `str` | Always `"meta_ads_library"` |

#### Methods

| Method | Description |
|---|---|
| `to_dict(include_raw=False)` | Convert to JSON-serializable dict |
| `to_json(include_raw=False, indent=2)` | Convert to JSON string |
| `Ad.from_graphql_response(data)` | (classmethod) Parse from GraphQL response dict |

### class AdCreative

| Field | Type | Description |
|---|---|---|
| `body` | `str \| None` | Ad body text |
| `caption` | `str \| None` | Link caption |
| `description` | `str \| None` | Link description |
| `title` | `str \| None` | Creative title |
| `link_url` | `str \| None` | Destination URL |
| `image_url` | `str \| None` | Image URL |
| `video_url` | `str \| None` | Video URL (best quality) |
| `video_hd_url` | `str \| None` | HD video URL |
| `video_sd_url` | `str \| None` | SD video URL |
| `thumbnail_url` | `str \| None` | Video thumbnail URL |
| `cta_text` | `str \| None` | Call-to-action text |
| `cta_type` | `str \| None` | CTA type identifier |

### class PageInfo

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `str` | (required) | Page ID |
| `name` | `str` | (required) | Page name |
| `profile_picture_url` | `str \| None` | `None` | Profile picture URL |
| `page_url` | `str \| None` | `None` | Page URL |
| `likes` | `int \| None` | `None` | Like count |
| `verified` | `bool` | `False` | Verification status |

### class PageSearchResult

| Field | Type | Description |
|---|---|---|
| `page_id` | `str` | Numeric page ID |
| `page_name` | `str` | Page display name |
| `page_profile_uri` | `str \| None` | Profile URI |
| `page_alias` | `str \| None` | Page alias/vanity URL |
| `page_logo_url` | `str \| None` | Logo/profile picture URL |
| `page_verified` | `bool \| None` | Whether page is verified |
| `page_like_count` | `int \| None` | Like count |
| `category` | `str \| None` | Page category |

### class ImpressionRange

| Field | Type | Description |
|---|---|---|
| `lower_bound` | `int \| None` | Lower bound of impression range |
| `upper_bound` | `int \| None` | Upper bound of impression range |

### class SpendRange

| Field | Type | Description |
|---|---|---|
| `lower_bound` | `int \| None` | Lower bound of spend range |
| `upper_bound` | `int \| None` | Upper bound of spend range |
| `currency` | `str \| None` | Currency code |

### class AudienceDistribution

| Field | Type | Description |
|---|---|---|
| `category` | `str` | Category label (e.g. `"25-34_female"`, region name) |
| `percentage` | `float` | Distribution percentage |

### class TargetingInfo

| Field | Type | Description |
|---|---|---|
| `age_min` | `int \| None` | Minimum target age |
| `age_max` | `int \| None` | Maximum target age |
| `genders` | `list[str]` | Target genders |
| `locations` | `list[str]` | Target locations |
| `location_types` | `list[str]` | Location types |
| `interests` | `list[str]` | Target interests |
| `excluded_locations` | `list[str]` | Excluded locations |

### class SearchResult

| Field | Type | Description |
|---|---|---|
| `ads` | `list[Ad]` | List of ads |
| `total_count` | `int \| None` | Total count from server |
| `has_next_page` | `bool` | Whether more pages exist |
| `end_cursor` | `str \| None` | Pagination cursor |
| `search_id` | `str \| None` | Search session ID |

---

## Filtering

**Module:** `meta_ads_collector.filters`

### class FilterConfig

Client-side ad filtering configuration. All fields default to `None` (disabled). All enabled filters are ANDed together.

| Field | Type | Description |
|---|---|---|
| `min_impressions` | `int \| None` | Minimum impressions (uses upper_bound >= min) |
| `max_impressions` | `int \| None` | Maximum impressions (uses lower_bound <= max) |
| `min_spend` | `int \| None` | Minimum spend |
| `max_spend` | `int \| None` | Maximum spend |
| `start_date` | `datetime \| None` | Ad must have started on or after this date |
| `end_date` | `datetime \| None` | Ad must have started on or before this date |
| `media_type` | `str \| None` | Media type (`"VIDEO"`, `"IMAGE"`, `"MEME"`, `"NONE"`, `"ALL"`) |
| `publisher_platforms` | `list[str] \| None` | Required platforms (at least one must match) |
| `languages` | `list[str] \| None` | Required languages (at least one must match) |
| `has_video` | `bool \| None` | Whether ad must (True) or must not (False) have video |
| `has_image` | `bool \| None` | Whether ad must (True) or must not (False) have image |

#### `is_empty() -> bool`

Returns `True` when no filters are configured.

### `passes_filter(ad, config) -> bool`

Test whether an ad passes all criteria in a FilterConfig. Returns `True` if the ad satisfies every enabled filter.

**Missing data policy:** If a filter is set but the ad lacks the corresponding data, the ad is included (passes the filter).

---

## Deduplication

**Module:** `meta_ads_collector.dedup`

### class DeduplicationTracker

Track which ads have already been collected. Supports context manager protocol.

#### `__init__(mode, db_path)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mode` | `str` | `"memory"` | `"memory"` for in-process tracking, `"persistent"` for SQLite |
| `db_path` | `str \| None` | `None` | Path to SQLite database (required for persistent mode) |

#### Methods

| Method | Description |
|---|---|
| `has_seen(ad_id) -> bool` | Check if an ad ID has been recorded |
| `mark_seen(ad_id, timestamp=None)` | Record an ad ID as seen |
| `get_last_collection_time() -> datetime \| None` | Get timestamp of last completed run |
| `update_collection_time()` | Record current time as latest run |
| `save()` | Persist changes to disk (persistent mode) |
| `load()` | Load state from disk (persistent mode) |
| `count() -> int` | Number of unique ad IDs seen |
| `clear()` | Remove all tracked state |
| `close()` | Close the database connection |

---

## Events

**Module:** `meta_ads_collector.events`

### Event Type Constants

| Constant | Value | Emitted When |
|---|---|---|
| `COLLECTION_STARTED` | `"collection_started"` | Before the first API request |
| `AD_COLLECTED` | `"ad_collected"` | After each ad passes filters |
| `PAGE_FETCHED` | `"page_fetched"` | After each API page is retrieved |
| `ERROR_OCCURRED` | `"error_occurred"` | On any error |
| `RATE_LIMITED` | `"rate_limited"` | On rate limit response |
| `SESSION_REFRESHED` | `"session_refreshed"` | When session is refreshed |
| `COLLECTION_FINISHED` | `"collection_finished"` | After collection ends |
| `ALL_EVENT_TYPES` | `frozenset` | Set of all event type strings |

### class Event

| Field | Type | Description |
|---|---|---|
| `event_type` | `str` | One of the event type constants |
| `data` | `dict[str, Any]` | Event-specific payload |
| `timestamp` | `datetime` | When the event was created (UTC) |

### class EventEmitter

Synchronous event emitter with exception isolation.

| Method | Description |
|---|---|
| `on(event_type, callback)` | Register a callback |
| `off(event_type, callback)` | Remove a callback |
| `emit(event_type, data=None) -> Event` | Fire all callbacks for event type |
| `has_listeners(event_type) -> bool` | Check if callbacks are registered |
| `listener_count(event_type) -> int` | Number of registered callbacks |

Callbacks receive an `Event` argument. Exceptions in callbacks are logged but never propagate.

---

## Webhooks

**Module:** `meta_ads_collector.webhooks`

### class WebhookSender

POST collected ad data to an external HTTP endpoint.

#### `__init__(url, retries, batch_size, timeout)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | (required) | Webhook endpoint URL |
| `retries` | `int` | `3` | Maximum retry attempts |
| `batch_size` | `int` | `1` | Ads to buffer before sending (`1` = immediate) |
| `timeout` | `int` | `10` | HTTP timeout (seconds) |

#### Methods

| Method | Description |
|---|---|
| `send(data) -> bool` | POST a single JSON payload |
| `send_batch(items) -> bool` | POST an array of items |
| `flush() -> bool` | Send buffered ads immediately |
| `as_callback() -> Callable` | Return callback for `EventEmitter.on()` |

All methods are safe -- they never raise exceptions.

---

## Media

**Module:** `meta_ads_collector.media`

### class MediaDownloader

Download images, videos, and thumbnails from ad creatives.

#### `__init__(output_dir, session, timeout, max_retries)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_dir` | `str \| Path` | (required) | Download directory |
| `session` | `requests.Session \| None` | `None` | HTTP session to reuse |
| `timeout` | `int` | `30` | Per-request timeout |
| `max_retries` | `int` | `2` | Retry attempts per download |

#### `download_ad_media(ad) -> list[MediaDownloadResult]`

Download all media from all creatives of an ad. Never raises.

### class MediaDownloadResult (frozen dataclass)

| Field | Type | Description |
|---|---|---|
| `ad_id` | `str` | Ad archive ID |
| `creative_index` | `int` | Zero-based creative index |
| `media_type` | `str` | `"image"`, `"video_hd"`, `"video_sd"`, or `"thumbnail"` |
| `url` | `str` | Source URL |
| `local_path` | `str \| None` | Path to downloaded file |
| `success` | `bool` | Whether download succeeded |
| `error` | `str \| None` | Error message on failure |
| `file_size` | `int \| None` | Bytes written on success |

File naming convention: `{ad_id}_{creative_index}_{media_type}.{ext}`

---

## Proxy Pool

**Module:** `meta_ads_collector.proxy_pool`

### class ProxyPool

Round-robin proxy pool with failure tracking and cooldown recovery.

#### `__init__(proxies, max_failures, cooldown)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `proxies` | `list[str]` | (required) | List of proxy strings |
| `max_failures` | `int` | `3` | Failures before proxy is marked dead |
| `cooldown` | `float` | `300.0` | Seconds before dead proxy is retried |

#### Methods

| Method | Description |
|---|---|
| `ProxyPool.from_file(filepath)` | (classmethod) Load proxies from a text file |
| `get_next() -> str` | Get next proxy in round-robin order |
| `mark_success(proxy)` | Record successful request |
| `mark_failure(proxy)` | Record failed request |
| `reset()` | Reset all counters and revive all proxies |
| `get_requests_proxies(proxy_url) -> dict` | Convert to `requests`-compatible proxy dict |

#### Properties

| Property | Type | Description |
|---|---|---|
| `alive_proxies` | `list[str]` | Proxies that are alive or past cooldown |

### `parse_proxy(proxy_string) -> str`

Parse a proxy string into a standard URL. Supports `host:port`, `host:port:user:pass`, and URL formats.

---

## URL Parser

**Module:** `meta_ads_collector.url_parser`

### `extract_page_id_from_url(url) -> str | None`

Extract a numeric page ID from a Facebook URL. Supports:

- Ad Library URLs: `?view_all_page_id=123456`
- Profile URLs: `?id=123456`
- Numeric path URLs: `facebook.com/123456`
- Bare numeric strings: `"123456"`

Returns `None` for vanity URLs that cannot be resolved without a network call.

---

## Logging

**Module:** `meta_ads_collector.logging_config`

### class JSONFormatter

Log formatter that emits records as single-line JSON objects with `timestamp`, `level`, `logger`, `message`, and any extra attributes.

### `setup_logging(level, fmt, log_file)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `level` | `str` | `"INFO"` | Log level |
| `fmt` | `str` | `"text"` | Format: `"text"` or `"json"` |
| `log_file` | `str \| None` | `None` | Optional log file path (in addition to console) |

---

## Reporting

**Module:** `meta_ads_collector.reporting`

### class CollectionReport

| Field | Type | Default | Description |
|---|---|---|---|
| `total_collected` | `int` | `0` | Ads successfully collected |
| `duplicates_skipped` | `int` | `0` | Ads skipped by dedup |
| `filtered_out` | `int` | `0` | Ads excluded by filters |
| `errors` | `int` | `0` | Errors encountered |
| `duration_seconds` | `float` | `0.0` | Collection duration |
| `start_time` | `datetime \| None` | `None` | Start timestamp |
| `end_time` | `datetime \| None` | `None` | End timestamp |

### `format_report(report) -> str`

Format a CollectionReport as a human-readable multi-line string.

### `format_report_json(report) -> str`

Format a CollectionReport as a JSON string.

---

## Exceptions

**Module:** `meta_ads_collector.exceptions`

| Exception | Parent | Description |
|---|---|---|
| `MetaAdsError` | `Exception` | Base exception for all errors |
| `AuthenticationError` | `MetaAdsError` | Session init or token extraction failed |
| `RateLimitError` | `MetaAdsError` | API rate limit hit. Has `retry_after: float` attribute |
| `SessionExpiredError` | `MetaAdsError` | Session expired and auto-refresh failed |
| `ProxyError` | `MetaAdsError` | Invalid proxy config or unreachable proxy |
| `InvalidParameterError` | `MetaAdsError` | Invalid parameter value. Has `param`, `value`, `allowed` attributes |

---

## Constants

**Module:** `meta_ads_collector.constants`

### Request Defaults

| Constant | Value | Description |
|---|---|---|
| `DEFAULT_TIMEOUT` | `30` | Request timeout (seconds) |
| `DEFAULT_MAX_RETRIES` | `3` | Max retries per request |
| `DEFAULT_RETRY_DELAY` | `2.0` | Base retry delay (seconds) |
| `DEFAULT_RATE_LIMIT_DELAY` | `2.0` | Delay between requests (seconds) |
| `DEFAULT_JITTER` | `1.0` | Random jitter (seconds) |
| `DEFAULT_PAGE_SIZE` | `10` | Results per API request |
| `MAX_SESSION_AGE` | `1800` | Session lifetime (30 minutes) |

### Ad Types

| Constant | Value |
|---|---|
| `AD_TYPE_ALL` | `"ALL"` |
| `AD_TYPE_POLITICAL` | `"POLITICAL_AND_ISSUE_ADS"` |
| `AD_TYPE_HOUSING` | `"HOUSING_ADS"` |
| `AD_TYPE_EMPLOYMENT` | `"EMPLOYMENT_ADS"` |
| `AD_TYPE_CREDIT` | `"CREDIT_ADS"` |

### Statuses

| Constant | Value |
|---|---|
| `STATUS_ACTIVE` | `"ACTIVE"` |
| `STATUS_INACTIVE` | `"INACTIVE"` |
| `STATUS_ALL` | `"ALL"` |

### Search Types

| Constant | Value |
|---|---|
| `SEARCH_KEYWORD` | `"KEYWORD_EXACT_PHRASE"` |
| `SEARCH_EXACT` | `"KEYWORD_EXACT_PHRASE"` |
| `SEARCH_UNORDERED` | `"KEYWORD_UNORDERED"` |
| `SEARCH_PAGE` | `"PAGE"` |

### Sort Modes

| Constant | Value |
|---|---|
| `SORT_RELEVANCY` | `None` |
| `SORT_IMPRESSIONS` | `"SORT_BY_TOTAL_IMPRESSIONS"` |
