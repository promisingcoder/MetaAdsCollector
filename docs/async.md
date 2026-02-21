# Async Usage Guide

`meta-ads-collector` provides a full async API for use with `asyncio`. The async client uses the same TLS fingerprint impersonation as the sync client to avoid detection.

## Installation

The async client uses `curl_cffi` (recommended) for TLS fingerprint impersonation, or falls back to `httpx`:

```bash
# Recommended: uses curl_cffi (same TLS fingerprinting as sync client)
pip install meta-ads-collector[stealth]

# Alternative: uses httpx (may get blocked by Facebook's TLS fingerprint detection)
pip install meta-ads-collector[async]
```

If both `curl_cffi` and `httpx` are installed, `curl_cffi` is preferred automatically.

## AsyncMetaAdsCollector

The async collector mirrors the sync `MetaAdsCollector` API with `async def` methods and `async for` generators.

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector() as collector:
        async for ad in collector.search(query="solar panels", country="US", max_results=10):
            print(f"{ad.page.name}: {ad.id}")

asyncio.run(main())
```

## Available methods

| Method | Returns | Description |
|---|---|---|
| `search(...)` | `AsyncIterator[Ad]` | Search for ads (async generator) |
| `collect(...)` | `list[Ad]` | Collect all results into a list |
| `collect_to_json(path, ...)` | `int` | Export to JSON file |
| `collect_to_csv(path, ...)` | `int` | Export to CSV file |
| `search_pages(query, country)` | `list[PageSearchResult]` | Search for pages by name |
| `get_stats()` | `dict` | Collection statistics |
| `close()` | `None` | Clean up resources |

All methods accept the same parameters as their sync counterparts.

## Examples

### Export to file

```python
async with AsyncMetaAdsCollector() as collector:
    count = await collector.collect_to_json(
        "output.json",
        query="AI startups",
        country="US",
        max_results=200,
    )
    print(f"Saved {count} ads")
```

### With proxy

```python
async with AsyncMetaAdsCollector(proxy="host:port:user:pass") as collector:
    async for ad in collector.search(query="test"):
        print(ad.id)
```

### With proxy pool

```python
from meta_ads_collector import ProxyPool

pool = ProxyPool(["proxy1:8080", "proxy2:8080", "proxy3:8080"])
async with AsyncMetaAdsCollector(proxy=pool) as collector:
    async for ad in collector.search(query="test"):
        print(ad.id)
```

### Search pages

```python
async with AsyncMetaAdsCollector() as collector:
    pages = await collector.search_pages("Nike", country="US")
    for page in pages:
        print(f"{page.page_name} (ID: {page.page_id})")
```

### With event callbacks

```python
from meta_ads_collector import AD_COLLECTED

def on_ad(event):
    print(f"Collected: {event.data['ad'].id}")

async with AsyncMetaAdsCollector(callbacks={"ad_collected": on_ad}) as collector:
    async for ad in collector.search(query="test", max_results=5):
        pass
```

### With filtering and deduplication

```python
from meta_ads_collector import FilterConfig, DeduplicationTracker

filters = FilterConfig(min_impressions=1000, has_video=True)
tracker = DeduplicationTracker(mode="memory")

async with AsyncMetaAdsCollector() as collector:
    async for ad in collector.search(
        query="tech",
        filter_config=filters,
        dedup_tracker=tracker,
    ):
        print(ad.id)
```

## AsyncMetaAdsClient

For lower-level control, use `AsyncMetaAdsClient` directly:

```python
from meta_ads_collector.async_client import AsyncMetaAdsClient

async with AsyncMetaAdsClient() as client:
    await client.initialize()

    data, cursor = await client.search_ads(
        query="test",
        country="US",
        first=10,
    )

    for ad_data in data.get("ads", []):
        print(ad_data.get("ad_archive_id"))
```

## Notes

- The async client prefers `curl_cffi.AsyncSession` for TLS fingerprint impersonation, falling back to `httpx.AsyncClient` if curl_cffi is not installed
- Facebook's 403 verification challenges are handled automatically (same as the sync client)
- Rate limiting uses `asyncio.sleep()` instead of `time.sleep()`
- Session initialization is performed asynchronously on the first request
- Event callbacks are still synchronous (they run in the event loop thread)
- Proxy rotation with `ProxyPool` works the same way as in the sync client
