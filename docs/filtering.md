# Filtering Guide

`meta-ads-collector` supports 11 client-side filters through the `FilterConfig` dataclass. Filters are applied after ads are fetched from the API, letting you narrow results beyond what Meta's API natively supports.

## How filtering works

All enabled filters use **AND logic** -- an ad must satisfy every non-None filter to be included. Filters default to `None` (disabled).

**Missing data policy:** If a filter is set but the ad lacks the corresponding data (e.g., `min_impressions=1000` but `ad.impressions is None`), the ad is **included**. This prevents silently dropping ads with incomplete data.

## FilterConfig fields

| Field | Type | Description |
|---|---|---|
| `min_impressions` | `int` | Ad's impression upper_bound must be >= this value |
| `max_impressions` | `int` | Ad's impression lower_bound must be <= this value |
| `min_spend` | `int` | Ad's spend upper_bound must be >= this value |
| `max_spend` | `int` | Ad's spend lower_bound must be <= this value |
| `start_date` | `datetime` | Ad's delivery_start_time must be on or after this date |
| `end_date` | `datetime` | Ad's delivery_start_time must be on or before this date |
| `media_type` | `str` | `ALL`, `IMAGE`, `VIDEO`, `MEME`, or `NONE` |
| `publisher_platforms` | `list[str]` | At least one platform must match (e.g., `["facebook", "instagram"]`) |
| `languages` | `list[str]` | At least one language must match (e.g., `["en", "es"]`) |
| `has_video` | `bool` | `True` = only ads with video, `False` = only ads without video |
| `has_image` | `bool` | `True` = only ads with images, `False` = only ads without images |

## Python examples

### Basic filtering

```python
from meta_ads_collector import MetaAdsCollector, FilterConfig

filters = FilterConfig(
    min_impressions=5000,
    max_spend=10000,
)

with MetaAdsCollector() as collector:
    for ad in collector.search(query="SaaS", filter_config=filters):
        print(ad.id, ad.impressions, ad.spend)
```

### Date range filtering

```python
from datetime import datetime
from meta_ads_collector import MetaAdsCollector, FilterConfig

filters = FilterConfig(
    start_date=datetime(2024, 6, 1),
    end_date=datetime(2024, 12, 31),
)

with MetaAdsCollector() as collector:
    for ad in collector.search(query="summer sale", filter_config=filters):
        print(ad.id, ad.delivery_start_time)
```

### Video-only ads on Instagram

```python
from meta_ads_collector import MetaAdsCollector, FilterConfig

filters = FilterConfig(
    has_video=True,
    publisher_platforms=["instagram"],
)

with MetaAdsCollector() as collector:
    for ad in collector.search(query="workout", filter_config=filters):
        for creative in ad.creatives:
            if creative.video_url:
                print(f"Video: {creative.video_url}")
```

### Combining all filters

```python
from datetime import datetime
from meta_ads_collector import MetaAdsCollector, FilterConfig

filters = FilterConfig(
    min_impressions=1000,
    max_impressions=500000,
    min_spend=100,
    max_spend=50000,
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    media_type="VIDEO",
    publisher_platforms=["facebook", "instagram"],
    languages=["en"],
    has_video=True,
)

with MetaAdsCollector() as collector:
    for ad in collector.search(query="fintech", country="US", filter_config=filters):
        print(ad.id)
```

## CLI filtering

All filter fields are available as CLI flags:

```bash
# High-impression ads
meta-ads-collector -q "crypto" --min-impressions 10000 -o crypto.json

# Ads in a date range
meta-ads-collector -q "election" --start-date 2024-01-01 --end-date 2024-11-05 -o election.json

# Video ads on Instagram
meta-ads-collector -q "fitness" --has-video --publisher-platform instagram -o fitness_videos.json

# Combine multiple filters
meta-ads-collector -q "loans" \
    --min-spend 500 \
    --max-spend 50000 \
    --language en \
    --language es \
    --publisher-platform facebook \
    -o loans.json
```

## Using passes_filter directly

For custom pipelines, you can use the `passes_filter` function directly:

```python
from meta_ads_collector import FilterConfig, passes_filter

filters = FilterConfig(min_impressions=1000)

# Test any Ad object against the filter
if passes_filter(ad, filters):
    process(ad)
```

## Impression and spend filter logic

Meta reports impressions and spend as **ranges** (lower_bound, upper_bound). The filter uses a conservative approach:

- `min_impressions=1000`: passes if `ad.impressions.upper_bound >= 1000` (the ad *could* have at least 1000 impressions)
- `max_impressions=5000`: passes if `ad.impressions.lower_bound <= 5000` (the ad *could* have at most 5000 impressions)

The same logic applies to spend filters. This means filters are inclusive rather than exclusive when dealing with ranges.
