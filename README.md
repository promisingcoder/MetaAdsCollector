# meta-ads-collector

[![PyPI version](https://img.shields.io/pypi/v/meta-ads-collector)](https://pypi.org/project/meta-ads-collector/)
[![Python versions](https://img.shields.io/pypi/pyversions/meta-ads-collector)](https://pypi.org/project/meta-ads-collector/)
[![CI](https://img.shields.io/github/actions/workflow/status/promisingcoder/MetaAdsCollector/ci.yml?branch=main&label=tests)](https://github.com/promisingcoder/MetaAdsCollector/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/promisingcoder/MetaAdsCollector/blob/main/LICENSE)

**No Meta API key required.** Search ads in the [Meta Ad Library](https://www.facebook.com/ads/library/) with a Python library or command-line tool. MetaAdsCollector does not call Meta's official Ad Library API. It relies on internal Meta endpoints, which Meta can change, restrict, or block at any time.

`meta-ads-collector` searches the Ad Library for commercial, political, housing, employment, and credit ads in countries supported by Meta's site. Returned creative and transparency details depend on what Meta makes available for each ad.

## About

MetaAdsCollector is a Python package published on [PyPI](https://pypi.org/project/meta-ads-collector/). Visit the [documentation website](https://promisingcoder.github.io/MetaAdsCollector/) for the [beginner's guide](https://promisingcoder.github.io/MetaAdsCollector/quickstart/) and the complete guides and API reference.

## Availability and limitations

MetaAdsCollector uses internal Meta endpoints, not the supported Graph API. It does not require a Meta API key, but it is not an official Meta product or API. Meta can change the endpoints or access rules without notice; requests may fail, be challenged, or return incomplete results. Fields such as spend, impressions, and audience distributions are only present when Meta returns them for an ad. Review Meta's [Ad Library](https://www.facebook.com/ads/library/) and applicable terms before use.

## Quick Start

### Beginner's quick start (no programming required)

Follow these steps to collect ads into a spreadsheet. You do not need to write or understand any code.

1. **Install Python.** Download Python from [python.org/downloads](https://www.python.org/downloads/). On Windows, check **"Add Python to PATH"** in the installer before selecting **Install Now**.
2. **Open a command window.** On Windows, open **PowerShell** from the Start menu. On macOS, open **Terminal** from Applications → Utilities. On Linux, open your Terminal app.
3. **Install MetaAdsCollector.** Copy the command for your system, paste it into the command window, and press Enter:

   **Windows:**
   ```powershell
   py -m pip install --upgrade meta-ads-collector
   ```

   **macOS or Linux:**
   ```bash
   python3 -m pip install --upgrade meta-ads-collector
   ```

4. **Search and save results as a spreadsheet file.** Replace `solar panels` with the product, brand, or topic you want to research. Run the command for your system:

   **Windows:**
   ```powershell
   py -m meta_ads_collector -q "solar panels" -c US -n 25 -o ads.csv
   ```

   **macOS or Linux:**
   ```bash
   python3 -m meta_ads_collector -q "solar panels" -c US -n 25 -o ads.csv
   ```

   This searches ads delivered in the United States and saves up to 25 results in `ads.csv` in the current folder. Change `US` to another country code, such as `GB` or `EG`, if needed.
5. **Open the results.** Find `ads.csv` in the current folder and open it with Excel, Numbers, or another spreadsheet app.

If your computer says the `meta-ads-collector` command cannot be found after installation, close and reopen the command window, then try again. For more options, see the [CLI guide](https://github.com/promisingcoder/MetaAdsCollector/blob/main/docs/cli.md).

### Python

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad in collector.search(query="solar panels", country="US", max_results=10):
        page_name = ad.page.name if ad.page is not None else "Unknown page"
        print(f"{page_name}: {ad.id}")
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

From source:

```bash
git clone https://github.com/promisingcoder/MetaAdsCollector.git
cd MetaAdsCollector
pip install -e ".[dev]"
```

**Declared requirement:** Python 3.9+ (`pyproject.toml`). The current test report was run on Python 3.12; compatibility has not been verified here on every declared Python version.

`curl_cffi` is installed automatically and provides browser TLS impersonation for HTTP compatibility. It does not guarantee that requests will avoid Meta's verification or blocking.

## Features

- **Search & Collection** -- keyword search, exact phrase, page-level collection by URL/name/ID
- **Advanced Filtering** -- 11 client-side filters: impressions, spend, dates, media type, platforms, languages
- **Deduplication** -- in-memory or persistent SQLite mode for incremental collection across runs
- **Media Downloads** -- download images, videos, and thumbnails from ad creatives
- **Ad Enrichment** -- fetch additional details through the ad detail flow; fields depend on Meta's response
- **Events & Webhooks** -- 7 lifecycle events with callback registration, webhook POST integration
- **Async Support** -- async search, collection, JSON/CSV export, page search, statistics, and cleanup using curl_cffi
- **Proxy Support** -- single proxy, proxy rotation with failure tracking and dead-proxy cooldown
- **Structured Logging** -- text or JSON log format, optional file output
- **Collection Reporting** -- summary statistics with throughput metrics
- **Export Formats** -- JSON, CSV, JSONL
- **Stream Mode** -- yield lifecycle events alongside ads through a single iterator
- **Request/session handling** -- browser-style TLS impersonation via `curl_cffi`, token extraction, and session refresh; Meta may still challenge or block requests

---

## Search & Collection

### Basic search

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    # Iterator-based (memory efficient)
    for ad in collector.search(query="fitness", country="US", max_results=100):
        print(ad.id, ad.page.name if ad.page is not None else "Unknown page")

    # List-based
    ads = collector.collect(query="fitness", country="US", max_results=50)
```

### Page-level collection

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
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
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    # JSON (with metadata envelope)
    collector.collect_to_json("output.json", query="AI", country="US", max_results=200)

    # CSV (flattened)
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
| `max_results` | `int` | `None` | Maximum ads to collect (`None` = unlimited, `0` = return no ads; negative or non-integer values raise `InvalidParameterError`) |
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
        print(ad.id)  # This ID is recorded before the ad is yielded.

print(f"Unique ads seen: {tracker.count()}")
```

### Persistent (across runs)

```python
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker

tracker = DeduplicationTracker(mode="persistent", db_path="collection_state.db")
with MetaAdsCollector() as collector:
    # Only collect ads not seen in previous runs. Yielded IDs are recorded
    # immediately; the last-run timestamp advances only after a complete search.
    for ad in collector.search(query="test", dedup_tracker=tracker):
        print(ad.id)
tracker.close()
```

### Incremental collection

```python
# Use with --since-last-run in the CLI, or manually:
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker, FilterConfig

tracker = DeduplicationTracker(mode="persistent", db_path="state.db")
last_run = tracker.get_last_collection_time()

filters = FilterConfig(start_date=last_run) if last_run else None

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", filter_config=filters, dedup_tracker=tracker):
        print(ad.id)  # Replace this with your application's processing code.
tracker.close()
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
    ad = next(collector.search(query="test", max_results=1), None)
    if ad is None:
        print("No ads found")
    else:
        results = collector.download_ad_media(ad, output_dir="./media")
```

Files are saved as `{ad_id}_{creative_index}_{media_type}.{ext}` (e.g., `123456_0_image.jpg`).

---

## Ad Enrichment

Fetch additional details through the ad detail flow, which tries an ad detail page and then a page-scoped search. The fields returned depend on Meta's response and may not include every field for every ad.

```python
from meta_ads_collector import MetaAdsCollector

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
from meta_ads_collector import MetaAdsCollector

def on_ad(event):
    print(f"Collected: {event.data['ad'].id}")

def on_finished(event):
    print(f"Done: {event.data['total_ads']} ads")

with MetaAdsCollector(callbacks={"ad_collected": on_ad, "collection_finished": on_finished}) as collector:
    for ad in collector.search(query="test", max_results=10):
        pass
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
from meta_ads_collector import MetaAdsCollector

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

Async collection with the same TLS fingerprint impersonation as the sync client. Available async methods do not cover every sync collector feature.

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector() as collector:
        async for ad in collector.search(query="test", country="US", max_results=10):
            print(ad.id, ad.page.name if ad.page is not None else "Unknown page")

        # Export
        count = await collector.collect_to_json("async_output.json", query="test", max_results=50)
        print(f"Saved {count} ads")

asyncio.run(main())
```

The async collector currently provides `search()`, `collect()`, `collect_to_json()`, `collect_to_csv()`, `search_pages()`, `get_stats()`, and `close()`. It does not currently provide JSONL export, media, ad enrichment, page-specific collection, or stream mode. The async client uses `curl_cffi.AsyncSession` with Chrome TLS impersonation.

---

## Proxy Support

### Single proxy

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector(proxy="host:port:user:pass") as collector:
    for ad in collector.search(query="test", max_results=10):
        print(ad.id)

# For an unauthenticated proxy, use proxy="host:port" in the constructor.
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
from meta_ads_collector import MetaAdsCollector, ProxyPool

# From a file (one proxy per line)
pool = ProxyPool.from_file("proxies.txt")
with MetaAdsCollector(proxy=pool) as collector:
    for ad in collector.search(query="test", max_results=10):
        print(ad.id)
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
setup_logging(level="DEBUG", fmt="json", log_file="collector.log")
```

### Collection reporting

```python
from meta_ads_collector import MetaAdsCollector
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
from meta_ads_collector import MetaAdsCollector, ProxyPool

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

`Ad` is the normalized data model returned by collection methods. See the [data model reference](docs/api-reference.md#data-models) for its fields and types. Values can be absent when Meta does not provide them; the model reference describes the schema, not guaranteed populated data.

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
# Install with dev dependencies (curl_cffi is included automatically)
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
