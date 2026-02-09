# Quick Start Guide

Get from zero to collecting ads in under 60 seconds.

## Install

```bash
pip install meta-ads-collector
```

## Python API

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad in collector.search(query="solar panels", country="US", max_results=10):
        print(f"{ad.page.name}: {ad.id}")
        print(f"  Body: {ad.creatives[0].body[:80] if ad.creatives else 'N/A'}...")
        print(f"  Impressions: {ad.impressions}")
        print(f"  Spend: {ad.spend}")
```

## CLI

```bash
# Export to JSON
meta-ads-collector -q "solar panels" -c US -n 10 -o solar.json

# Export to CSV
meta-ads-collector -q "solar panels" -c US -n 100 -o solar.csv

# Export to JSONL (streaming-friendly)
meta-ads-collector -q "solar panels" -c US -o solar.jsonl
```

## Export to file (Python)

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    count = collector.collect_to_json("ads.json", query="fitness", country="US", max_results=200)
    print(f"Saved {count} ads")
```

## Collect ads from a specific page

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    # By page name (resolves via typeahead search)
    for ad in collector.collect_by_page_name("Coca-Cola", country="US", max_results=50):
        print(ad.id, ad.creatives[0].body[:50] if ad.creatives else "")

    # By page URL
    for ad in collector.collect_by_page_url(
        "https://www.facebook.com/ads/library/?view_all_page_id=123456"
    ):
        print(ad.id)
```

## With a proxy

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector(proxy="host:port:user:pass") as collector:
    for ad in collector.search(query="test", max_results=10):
        print(ad.id)
```

Or via the CLI:

```bash
meta-ads-collector -q "test" --proxy "host:port:user:pass" -o ads.json
```

## Next steps

- [Filtering guide](filtering.md) -- narrow results by impressions, spend, dates, media type
- [Deduplication guide](deduplication.md) -- avoid collecting the same ad twice
- [Media downloads](media.md) -- download images and videos from ad creatives
- [Events & webhooks](events.md) -- react to collection lifecycle events
- [Async usage](async.md) -- use with asyncio and httpx
- [Proxy configuration](proxy.md) -- proxy rotation and failure handling
- [CLI reference](cli.md) -- complete list of CLI flags
