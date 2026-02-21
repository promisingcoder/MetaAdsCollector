# meta-ads-collector

[![PyPI version](https://img.shields.io/pypi/v/meta-ads-collector)](https://pypi.org/project/meta-ads-collector/)
[![Python versions](https://img.shields.io/pypi/pyversions/meta-ads-collector)](https://pypi.org/project/meta-ads-collector/)
[![CI](https://img.shields.io/github/actions/workflow/status/promisingcoder/MetaAdsCollector/ci.yml?branch=main&label=tests)](https://github.com/promisingcoder/MetaAdsCollector/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/promisingcoder/MetaAdsCollector/blob/main/LICENSE)

**No API key required.** Collect ads from the [Meta Ad Library](https://www.facebook.com/ads/library/) using Python. No developer account, no identity verification, no rate-limited official API. Just install and search.

`meta-ads-collector` reverse-engineers Meta's internal GraphQL API to give you programmatic access to **all ad types** in **all countries** -- commercial ads, political ads, housing, employment, credit -- with full creative content, spend data, impression ranges, and audience demographics.

## Why not the official API?

| Feature | meta-ads-collector | Official Meta Ad Library API |
|---|---|---|
| API key required | **No** | Yes (requires developer account) |
| Identity verification | **No** | Yes (physical mail verification) |
| Ad types available | **All** (commercial, political, housing, employment, credit) | Political/issue ads only (+ EU) |
| Countries | **All** | Limited |
| Creative content | **Full** (text, images, videos, CTAs) | Partial |
| Spend & impression data | **Yes** | Limited |
| Audience demographics | **Yes** | Limited |
| Rate limits | Managed automatically | Strict, enforced |
| Setup time | **< 60 seconds** | Days to weeks |

## Quick Start

### Python

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad in collector.search(query="solar panels", country="US", max_results=10):
        print(f"{ad.page.name}: {ad.id}")
        print(f"  Impressions: {ad.impressions}")
        print(f"  Spend: {ad.spend}")
```

### CLI

```bash
meta-ads-collector -q "solar panels" -c US -n 10 -o ads.json
```

## Installation

```bash
pip install meta-ads-collector
```

With stealth TLS fingerprinting (recommended, also enables async support):

```bash
pip install meta-ads-collector[stealth]
```

With async support only (uses [httpx](https://www.python-httpx.org/)):

```bash
pip install meta-ads-collector[async]
```

From source:

```bash
git clone https://github.com/promisingcoder/MetaAdsCollector.git
cd meta-ads-collector
pip install -e ".[dev,async,stealth]"
```

**Requirements:** Python 3.9+

## Features

- **Search & Collection** -- keyword search, exact phrase, page-level collection by URL/name/ID
- **Advanced Filtering** -- 11 client-side filters: impressions, spend, dates, media type, platforms, languages
- **Deduplication** -- in-memory or persistent SQLite mode for incremental collection across runs
- **Media Downloads** -- download images, videos, and thumbnails from ad creatives
- **Ad Enrichment** -- fetch additional detail data from the ad snapshot endpoint
- **Events & Webhooks** -- 7 lifecycle events with callback registration, webhook POST integration
- **Async Support** -- full async/await API using curl_cffi (preferred) or httpx (fallback)
- **Proxy Support** -- single proxy, proxy rotation with failure tracking and dead-proxy cooldown
- **Structured Logging** -- text or JSON log format, optional file output
- **Collection Reporting** -- summary statistics with throughput metrics
- **Export Formats** -- JSON, CSV, JSONL
- **Stream Mode** -- yield lifecycle events alongside ads through a single iterator
- **Detection Avoidance** -- browser fingerprint randomization, TLS fingerprint impersonation (via `curl_cffi`), dynamic token extraction, session management

---

## Search & Collection

### Basic search

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    # Iterator-based (memory efficient)
    for ad in collector.search(query="fitness", country="US", max_results=100):
        print(ad.id, ad.page.name)

    # List-based
    ads = collector.collect(query="fitness", country="US", max_results=50)
```

### Page-level collection

```python
# By Facebook page URL
for ad in collector.collect_by_page_url("https://www.facebook.com/ads/library/?view_all_page_id=123456"):
    print(ad.id)

# By page name (uses typeahead search, selects first match)
for ad in collector.collect_by_page_name("Coca-Cola", country="US"):
    print(ad.id)

# By numeric page ID
for ad in collector.collect_by_page_id("123456", country="US"):
    print(ad.id)

# Search for pages first
pages = collector.search_pages("Nike", country="US")
for page in pages:
    print(f"{page.page_name} (ID: {page.page_id})")
```

### Export to file

```python
# JSON (with metadata envelope)
collector.collect_to_json("output.json", query="AI", country="US", max_results=200)

# CSV (flattened, 25 columns)
collector.collect_to_csv("output.csv", query="AI", country="US", max_results=200)

# JSONL (one object per line, streaming-friendly)
collector.collect_to_jsonl("output.jsonl", query="AI", country="US", max_results=200)
```

### Search parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | `""` | Search query string |
| `country` | `str` | `"US"` | ISO 3166-1 alpha-2 country code |
| `ad_type` | `str` | `AD_TYPE_ALL` | `ALL`, `POLITICAL_AND_ISSUE_ADS`, `HOUSING_ADS`, `EMPLOYMENT_ADS`, `CREDIT_ADS` |
| `status` | `str` | `STATUS_ACTIVE` | `ACTIVE`, `INACTIVE`, `ALL` |
| `search_type` | `str` | `SEARCH_KEYWORD` | `KEYWORD_EXACT_PHRASE`, `KEYWORD_UNORDERED`, `PAGE` |
| `page_ids` | `list[str]` | `None` | Filter by specific page IDs |
| `sort_by` | `str` | `SORT_IMPRESSIONS` | `SORT_BY_TOTAL_IMPRESSIONS` or `None` (relevancy) |
| `max_results` | `int` | `None` | Maximum ads to collect (None = unlimited) |
| `page_size` | `int` | `10` | Results per API request (max ~30) |
| `filter_config` | `FilterConfig` | `None` | Client-side filter configuration |
| `dedup_tracker` | `DeduplicationTracker` | `None` | Deduplication tracker |

---

## Filtering

Apply client-side filters to refine results beyond what the API supports. All filters use AND logic.

```python
from meta_ads_collector import MetaAdsCollector, FilterConfig
from datetime import datetime

filters = FilterConfig(
    min_impressions=1000,
    max_impressions=100000,
    min_spend=100,
    max_spend=5000,
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    media_type="VIDEO",
    publisher_platforms=["facebook", "instagram"],
    languages=["en"],
    has_video=True,
    has_image=None,  # None = don't filter on this
)

with MetaAdsCollector() as collector:
    for ad in collector.search(query="tech", filter_config=filters):
        print(ad.id)
```

| Filter Field | Type | Description |
|---|---|---|
| `min_impressions` | `int` | Minimum impressions (uses upper_bound >= value) |
| `max_impressions` | `int` | Maximum impressions (uses lower_bound <= value) |
| `min_spend` | `int` | Minimum spend amount |
| `max_spend` | `int` | Maximum spend amount |
| `start_date` | `datetime` | Only ads starting on or after this date |
| `end_date` | `datetime` | Only ads starting on or before this date |
| `media_type` | `str` | `ALL`, `IMAGE`, `VIDEO`, `MEME`, `NONE` |
| `publisher_platforms` | `list[str]` | Filter by platform (facebook, instagram, messenger, audience_network) |
| `languages` | `list[str]` | Filter by language code |
| `has_video` | `bool` | Only ads with/without video |
| `has_image` | `bool` | Only ads with/without images |

Ads with missing data for a filtered field are **included** by default (conservative approach).

---

## Deduplication

### In-memory (single run)

```python
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker

tracker = DeduplicationTracker(mode="memory")

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", dedup_tracker=tracker):
        print(ad.id)  # Guaranteed unique within this run

print(f"Unique ads seen: {tracker.count()}")
```

### Persistent (across runs)

```python
tracker = DeduplicationTracker(mode="persistent", db_path="collection_state.db")

with MetaAdsCollector() as collector:
    # Only collect ads not seen in previous runs
    for ad in collector.search(query="test", dedup_tracker=tracker):
        print(ad.id)

# State is automatically saved on context manager exit
```

### Incremental collection

```python
# Use with --since-last-run in CLI, or manually:
tracker = DeduplicationTracker(mode="persistent", db_path="state.db")
last_run = tracker.get_last_collection_time()

filters = FilterConfig(start_date=last_run) if last_run else None

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", filter_config=filters, dedup_tracker=tracker):
        process(ad)

tracker.update_collection_time()
tracker.save()
```

---

## Media Downloads

Download images, videos, and thumbnails from ad creatives.

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    # Collect ads and download media simultaneously
    for ad, media_results in collector.collect_with_media(
        query="fashion",
        country="US",
        max_results=20,
        media_output_dir="./downloaded_media",
    ):
        print(f"Ad {ad.id}:")
        for result in media_results:
            if result.success:
                print(f"  Downloaded {result.media_type}: {result.local_path} ({result.file_size} bytes)")
            else:
                print(f"  Failed {result.media_type}: {result.error}")

    # Or download media for a single ad
    ad = next(collector.search(query="test", max_results=1))
    results = collector.download_ad_media(ad, output_dir="./media")
```

Files are saved as `{ad_id}_{creative_index}_{media_type}.{ext}` (e.g., `123456_0_image.jpg`).

---

## Ad Enrichment

Fetch additional detail data from the ad snapshot endpoint to fill in missing fields.

```python
with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", max_results=5):
        enriched = collector.enrich_ad(ad)
        # enriched may contain additional creative URLs, funding entity, demographics, etc.
        print(enriched.funding_entity, enriched.disclaimer)
```

Enrichment is failure-safe: if the detail endpoint returns an error, the original ad is returned unchanged.

---

## Events & Webhooks

### Event callbacks

```python
from meta_ads_collector import MetaAdsCollector, EventEmitter, AD_COLLECTED, COLLECTION_FINISHED

def on_ad(event):
    ad = event.data["ad"]
    print(f"Collected: {ad.id}")

def on_finished(event):
    print(f"Done! {event.data['total_ads']} ads in {event.data['duration_seconds']:.1f}s")

with MetaAdsCollector() as collector:
    collector.event_emitter.on(AD_COLLECTED, on_ad)
    collector.event_emitter.on(COLLECTION_FINISHED, on_finished)

    for ad in collector.search(query="test", max_results=10):
        pass  # Events fire automatically
```

Or register callbacks at init:

```python
collector = MetaAdsCollector(callbacks={
    "ad_collected": on_ad,
    "collection_finished": on_finished,
})
```

### Event types

| Event | Data Keys | Description |
|---|---|---|
| `collection_started` | `query`, `country`, `ad_type`, `status`, `search_type`, `page_ids`, `max_results` | Emitted when search begins |
| `ad_collected` | `ad` | Emitted for each collected ad |
| `page_fetched` | `page_number`, `ads_on_page`, `has_next_page` | Emitted after each API page |
| `error_occurred` | `exception`, `context` | Emitted on errors |
| `rate_limited` | `wait_seconds`, `retry_count` | Emitted on rate limiting |
| `session_refreshed` | `reason` | Emitted on session refresh |
| `collection_finished` | `total_ads`, `total_pages`, `duration_seconds` | Emitted when search completes |

### Stream mode

Yield events and ads through a single iterator:

```python
with MetaAdsCollector() as collector:
    for event_type, data in collector.stream(query="test", max_results=10):
        if event_type == "ad_collected":
            print(f"Ad: {data['ad'].id}")
        elif event_type == "page_fetched":
            print(f"Page {data['page_number']}: {data['ads_on_page']} ads")
        elif event_type == "collection_finished":
            print(f"Done: {data['total_ads']} ads")
```

### Webhooks

POST each collected ad to an external endpoint:

```python
from meta_ads_collector import MetaAdsCollector, WebhookSender, AD_COLLECTED

sender = WebhookSender(
    url="https://hooks.example.com/ads",
    retries=3,
    batch_size=1,
    timeout=10,
)

with MetaAdsCollector() as collector:
    collector.event_emitter.on(AD_COLLECTED, sender.as_callback())
    for ad in collector.search(query="test", max_results=10):
        pass  # Ads are POSTed to the webhook automatically
```

---

## Async Support

Full async API with the same TLS fingerprint impersonation as the sync client.

```bash
# Recommended: uses curl_cffi for TLS fingerprinting (same as sync client)
pip install meta-ads-collector[stealth]

# Alternative: uses httpx (may be detected by Facebook)
pip install meta-ads-collector[async]
```

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector() as collector:
        async for ad in collector.search(query="test", country="US", max_results=10):
            print(ad.id, ad.page.name)

        # Export
        count = await collector.collect_to_json("async_output.json", query="test", max_results=50)
        print(f"Saved {count} ads")

asyncio.run(main())
```

The async collector mirrors the sync API: `search()`, `collect()`, `collect_to_json()`, `collect_to_csv()`, `search_pages()`, `get_stats()`. When `curl_cffi` is installed, the async client uses `curl_cffi.AsyncSession` with Chrome TLS impersonation. Otherwise it falls back to `httpx.AsyncClient`.

---

## Proxy Support

### Single proxy

```python
collector = MetaAdsCollector(proxy="host:port:user:pass")
# or
collector = MetaAdsCollector(proxy="host:port")
```

### Proxy rotation

```python
from meta_ads_collector import MetaAdsCollector, ProxyPool

# From a list
pool = ProxyPool([
    "host1:port1:user1:pass1",
    "host2:port2:user2:pass2",
    "host3:port3:user3:pass3",
], max_failures=3, cooldown=300)

collector = MetaAdsCollector(proxy=pool)
```

```python
# From a file (one proxy per line)
pool = ProxyPool.from_file("proxies.txt")
collector = MetaAdsCollector(proxy=pool)
```

The proxy pool provides round-robin selection with failure tracking. Proxies that fail `max_failures` times consecutively are excluded for a `cooldown` period (default 300 seconds), then automatically retried.

### Environment variable

```bash
export META_ADS_PROXY="host:port:user:pass"
meta-ads-collector -q "test" -o ads.json
```

---

## Logging & Reporting

### Structured logging

```python
from meta_ads_collector import setup_logging

# Human-readable text format
setup_logging(level="INFO")

# JSON format (for log aggregation)
setup_logging(level="DEBUG", fmt="json", log_file="/var/log/collector.log")
```

### Collection reporting

```python
from meta_ads_collector.reporting import CollectionReport, format_report

with MetaAdsCollector() as collector:
    ads = collector.collect(query="test", max_results=50)
    stats = collector.get_stats()

    report = CollectionReport(
        total_collected=len(ads),
        duplicates_skipped=0,
        filtered_out=0,
        errors=stats.get("errors", 0),
        duration_seconds=stats.get("duration_seconds", 0),
    )
    print(format_report(report))
```

---

## Export Formats

| Format | Extension | Description | Use Case |
|---|---|---|---|
| **JSON** | `.json` | Full metadata envelope + ads array, pretty-printed | Complete datasets, debugging |
| **CSV** | `.csv` | Flattened schema (25 columns), one row per ad | Spreadsheets, BI tools |
| **JSONL** | `.jsonl` | One JSON object per line | Streaming, large datasets, log processing |

---

## CLI Reference

```
meta-ads-collector [OPTIONS]
```

### Search Parameters

| Flag | Description | Default |
|---|---|---|
| `-q, --query` | Search query string | `""` (all ads) |
| `-c, --country` | ISO 3166-1 alpha-2 country code | `US` |
| `-t, --ad-type` | `all`, `political`, `housing`, `employment`, `credit` | `all` |
| `-s, --status` | `active`, `inactive`, `all` | `active` |
| `--search-type` | `keyword`, `exact`, `page` | `keyword` |
| `--sort-by` | `relevancy`, `impressions` | `impressions` |
| `--page-ids` | Filter by specific page IDs (space-separated) | |

### Page-Level Collection

| Flag | Description |
|---|---|
| `--search-pages QUERY` | Search for pages by name, print results and exit |
| `--page-url URL` | Collect ads from a Facebook page by URL |
| `--page-name NAME` | Search for a page by name, then collect its ads |

### Output

| Flag | Description | Default |
|---|---|---|
| `-o, --output` | Output file path (`.json`, `.csv`, `.jsonl`) | **required** |
| `-n, --max-results` | Maximum ads to collect | unlimited |
| `--page-size` | Results per API request | `10` |
| `--include-raw` | Include raw API response data in JSON output | `false` |

### Filtering

| Flag | Description |
|---|---|
| `--min-impressions N` | Minimum impressions |
| `--max-impressions N` | Maximum impressions |
| `--min-spend N` | Minimum spend amount |
| `--max-spend N` | Maximum spend amount |
| `--start-date DATE` | Only ads starting on or after this date (ISO 8601) |
| `--end-date DATE` | Only ads starting on or before this date (ISO 8601) |
| `--media-type TYPE` | `all`, `image`, `video`, `meme`, `none` |
| `--publisher-platform PLATFORM` | Filter by platform (repeatable) |
| `--language LANG` | Filter by language code (repeatable) |
| `--has-video` | Only ads with video |
| `--has-image` | Only ads with images |

### Connection

| Flag | Description | Default |
|---|---|---|
| `--proxy` | Proxy (`host:port:user:pass`) | `META_ADS_PROXY` env |
| `--proxy-file PATH` | File with one proxy per line (for rotation) | |
| `--timeout` | Request timeout (seconds) | `30` |
| `--delay` | Delay between requests (seconds) | `2.0` |
| `--no-proxy` | Disable proxy usage | `false` |

### Media

| Flag | Description | Default |
|---|---|---|
| `--download-media` | Download images/videos/thumbnails | `false` |
| `--no-download-media` | Explicitly disable media downloading | |
| `--media-dir PATH` | Directory for downloaded files | `./ad_media` |

### Enrichment

| Flag | Description | Default |
|---|---|---|
| `--enrich` | Fetch additional detail data for each ad | `false` |
| `--no-enrich` | Explicitly disable enrichment | |

### Deduplication

| Flag | Description | Default |
|---|---|---|
| `--deduplicate, --dedup` | Enable in-memory deduplication | `false` |
| `--state-file PATH` | SQLite file for persistent deduplication | |
| `--since-last-run` | Only collect ads newer than last run (requires `--state-file`) | `false` |

### Webhooks

| Flag | Description |
|---|---|
| `--webhook-url URL` | POST each collected ad to this webhook URL |

### Logging

| Flag | Description | Default |
|---|---|---|
| `--log-format` | `text` or `json` | `text` |
| `--log-file PATH` | Also write logs to this file | |
| `-v, --verbose` | Enable debug logging | `false` |

### Reporting

| Flag | Description | Default |
|---|---|---|
| `--report` | Print collection report to stdout | `false` |
| `--report-file PATH` | Save report as JSON to this file | |

### CLI Examples

```bash
# Search for real estate ads in the US, export as JSON
meta-ads-collector -q "real estate" -c US -o ads.json

# Political ads from Egypt as CSV
meta-ads-collector -c EG -t political -o egypt.csv

# High-spend video ads with proxy rotation
meta-ads-collector -q "SaaS" --min-spend 500 --has-video --proxy-file proxies.txt -o saas.json

# Incremental collection with deduplication
meta-ads-collector -q "crypto" --state-file crypto.db --since-last-run -o new_crypto.jsonl

# Download media alongside ad data
meta-ads-collector -q "fashion" --download-media --media-dir ./fashion_media -o fashion.json

# Page-level collection
meta-ads-collector --page-url "https://www.facebook.com/ads/library/?view_all_page_id=123456" -o page_ads.json

# Search for pages
meta-ads-collector --search-pages "Nike" -c US

# JSON structured logging with report
meta-ads-collector -q "test" --log-format json --report -o test.json
```

---

## Python API Reference

### MetaAdsCollector

The main entry point. Supports context manager protocol.

```python
collector = MetaAdsCollector(
    proxy=None,              # str, list[str], ProxyPool, or None
    rate_limit_delay=2.0,    # seconds between requests
    jitter=1.0,              # random jitter added to delay
    timeout=30,              # request timeout (seconds)
    max_retries=3,           # retry attempts per request
    callbacks=None,          # dict[str, Callable] for event registration
)
```

| Method | Returns | Description |
|---|---|---|
| `search(...)` | `Iterator[Ad]` | Search for ads (lazy iterator) |
| `collect(...)` | `list[Ad]` | Search and return all results as a list |
| `collect_to_json(path, ...)` | `int` | Export to JSON file, returns count |
| `collect_to_csv(path, ...)` | `int` | Export to CSV file, returns count |
| `collect_to_jsonl(path, ...)` | `int` | Export to JSONL file, returns count |
| `collect_by_page_url(url, ...)` | `Iterator[Ad]` | Collect ads from a page URL |
| `collect_by_page_name(name, ...)` | `Iterator[Ad]` | Search page by name, collect its ads |
| `collect_by_page_id(page_id, ...)` | `Iterator[Ad]` | Collect ads by numeric page ID |
| `search_pages(query, country)` | `list[PageSearchResult]` | Search for pages by name |
| `collect_with_media(media_output_dir, ...)` | `Iterator[tuple[Ad, list[MediaDownloadResult]]]` | Collect ads with media downloads |
| `download_ad_media(ad, output_dir)` | `list[MediaDownloadResult]` | Download media for a single ad |
| `enrich_ad(ad)` | `Ad` | Fetch additional detail data |
| `stream(...)` | `Iterator[tuple[str, dict]]` | Yield lifecycle events |
| `get_stats()` | `dict` | Collection statistics |
| `close()` | `None` | Clean up resources |

### Ad Model

```python
@dataclass
class Ad:
    id: str                                    # Ad Archive ID
    ad_library_id: Optional[str]
    page: Optional[PageInfo]                   # .id, .name, .profile_picture_url, .page_url, .likes, .verified
    is_active: Optional[bool]
    ad_status: Optional[str]                   # ACTIVE, INACTIVE
    delivery_start_time: Optional[datetime]
    delivery_stop_time: Optional[datetime]
    creatives: list[AdCreative]                # .body, .title, .description, .link_url, .image_url, .video_url, ...
    snapshot_url: Optional[str]
    ad_snapshot_url: Optional[str]
    impressions: Optional[ImpressionRange]     # .lower_bound, .upper_bound
    spend: Optional[SpendRange]                # .lower_bound, .upper_bound, .currency
    reach: Optional[ImpressionRange]
    currency: Optional[str]
    age_gender_distribution: list[AudienceDistribution]
    region_distribution: list[AudienceDistribution]
    publisher_platforms: list[str]
    languages: list[str]
    funding_entity: Optional[str]
    disclaimer: Optional[str]
    ad_type: Optional[str]
    categories: list[str]
    beneficiary_payers: list[str]
    bylines: list[str]
    collation_id: Optional[str]
    collation_count: Optional[int]
    collected_at: datetime
    raw_data: Optional[dict]                   # Full API response (with include_raw=True)
```

### Exceptions

All exceptions inherit from `MetaAdsError`.

| Exception | When |
|---|---|
| `AuthenticationError` | Session initialization or token extraction fails |
| `RateLimitError` | API rate limit hit |
| `SessionExpiredError` | Session expired and automatic refresh failed |
| `ProxyError` | Invalid proxy format or unreachable proxy |
| `InvalidParameterError` | Invalid parameter value (bad country code, ad type, etc.) |

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest

# Lint
python -m ruff check .

# Type check
python -m mypy meta_ads_collector/ --ignore-missing-imports

# Format
python -m ruff format .
```

## License

[MIT](LICENSE)
