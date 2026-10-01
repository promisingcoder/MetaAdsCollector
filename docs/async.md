# Async Usage Guide

`meta-ads-collector` provides an asynchronous collector for use with `asyncio`. The async client uses `curl_cffi.AsyncSession` with browser-style TLS impersonation. This does not guarantee requests will avoid Meta's verification or blocking.

## Installation

Async support is included out of the box -- no extra install required:

```bash
pip install meta-ads-collector
```

## AsyncMetaAdsCollector

The async collector provides an async search and collection interface. Its methods do not cover every sync collector feature.

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector() as collector:
        async for ad in collector.search(query="solar panels", country="US", max_results=10):
            page_name = ad.page.name if ad.page is not None else "Unknown page"
            print(f"{page_name}: {ad.id}")

asyncio.run(main())
```

## Methods shown in this guide

| Method | Returns | Description |
|---|---|---|
| `search(...)` | `AsyncIterator[Ad]` | Search for ads (async generator) |
| `collect(...)` | `list[Ad]` | Collect all results into a list |
| `collect_to_json(path, ...)` | `int` | Export to JSON file |
| `collect_to_csv(path, ...)` | `int` | Export to CSV file |
| `search_pages(query, country)` | `list[PageSearchResult]` | Search for pages by name |
| `get_stats()` | `dict` | Collection statistics (synchronous method) |
| `close()` | `None` | Close resources (await the method) |

The async collector has a similar interface to the synchronous collector, but not every method is available on both. Check the [API reference](api-reference.md) and the installed version before relying on a method.

## Examples

### Export to file

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector() as collector:
        count = await collector.collect_to_json(
            "output.json",
            query="AI startups",
            country="US",
            max_results=200,
        )
        print(f"Saved {count} ads")

asyncio.run(main())
```

### With proxy

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector(proxy="host:port:user:pass") as collector:
        async for ad in collector.search(query="test"):
            print(ad.id)

asyncio.run(main())
```

### With proxy pool

```python
import asyncio
from meta_ads_collector import ProxyPool
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    pool = ProxyPool(["proxy1:8080", "proxy2:8080", "proxy3:8080"])
    async with AsyncMetaAdsCollector(proxy=pool) as collector:
        async for ad in collector.search(query="test"):
            print(ad.id)

asyncio.run(main())
```

### Search pages

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    async with AsyncMetaAdsCollector() as collector:
        pages = await collector.search_pages("Nike", country="US")
        for page in pages:
            print(f"{page.page_name} (ID: {page.page_id})")

asyncio.run(main())
```

### With event callbacks

```python
import asyncio
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

def on_ad(event):
    print(f"Collected: {event.data['ad'].id}")

async def main():
    async with AsyncMetaAdsCollector(callbacks={"ad_collected": on_ad}) as collector:
        async for ad in collector.search(query="test", max_results=5):
            pass

asyncio.run(main())
```

### With filtering and deduplication

```python
import asyncio
from meta_ads_collector import FilterConfig, DeduplicationTracker
from meta_ads_collector.async_collector import AsyncMetaAdsCollector

async def main():
    filters = FilterConfig(min_impressions=1000, has_video=True)
    tracker = DeduplicationTracker(mode="memory")

    async with AsyncMetaAdsCollector() as collector:
        async for ad in collector.search(
            query="tech",
            filter_config=filters,
            dedup_tracker=tracker,
        ):
            print(ad.id)

asyncio.run(main())
```

## AsyncMetaAdsClient

For lower-level control, use `AsyncMetaAdsClient` directly:

```python
import asyncio
from meta_ads_collector.async_client import AsyncMetaAdsClient

async def main():
    async with AsyncMetaAdsClient() as client:
        await client.initialize()

        data, cursor = await client.search_ads(
            query="test",
            country="US",
            first=10,
        )

        for ad_data in data.get("ads", []):
            print(ad_data.get("ad_archive_id"))

asyncio.run(main())
```

## Notes

- The async client uses `curl_cffi.AsyncSession` with Chrome TLS fingerprint impersonation
- Requests can still receive verification challenges or be blocked; session refresh and retries do not guarantee access
- Rate limiting uses `asyncio.sleep()` instead of `time.sleep()`
- Session initialization is performed asynchronously on the first request
- Event callbacks are still synchronous (they run in the event loop thread)
- Proxy rotation with `ProxyPool` works the same way as in the sync client
