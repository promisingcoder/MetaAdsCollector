# meta-ads-collector

A Python library and CLI tool for collecting ads from the [Meta Ad Library](https://www.facebook.com/ads/library/) (Facebook/Instagram).

Supports searching, filtering, pagination, and exporting ads to JSON, CSV, or JSONL.

## Installation

```bash
pip install meta-ads-collector
```

Or install from source:

```bash
git clone https://github.com/Yossef/meta-ads-collector.git
cd meta-ads-collector
pip install -e ".[dev]"
```

## Quick Start

### Python API

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector(proxy="host:port:user:pass") as collector:
    for ad in collector.search(
        query="real estate",
        country="US",
        ad_type=MetaAdsCollector.AD_TYPE_HOUSING,
        max_results=10,
    ):
        print(f"{ad.page.name}: {ad.id}")
        print(f"  Impressions: {ad.impressions}")
        print(f"  Spend: {ad.spend}")
```

### CLI

```bash
# Search for ads and export to JSON
meta-ads-collector --query "real estate" --country US --output ads.json

# Political ads from Egypt as CSV
meta-ads-collector --country EG --ad-type political --output egypt.csv

# Limit results and use exact phrase matching
meta-ads-collector --query "buy now" --search-type exact --max-results 500 --output results.jsonl
```

## Configuration

### Proxy

Set the `META_ADS_PROXY` environment variable or pass `--proxy` on the CLI:

```bash
export META_ADS_PROXY="host:port:user:pass"
```

Or create a `.env` file (see `.env.example`).

### CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `-q, --query` | Search query string | `""` (all ads) |
| `-c, --country` | ISO 3166-1 alpha-2 country code | `US` |
| `-t, --ad-type` | `all`, `political`, `housing`, `employment`, `credit` | `all` |
| `-s, --status` | `active`, `inactive`, `all` | `active` |
| `--search-type` | `keyword`, `exact`, `page` | `keyword` |
| `--sort-by` | `relevancy`, `impressions` | `impressions` |
| `-o, --output` | Output file path (`.json`, `.csv`, `.jsonl`) | **required** |
| `-n, --max-results` | Max ads to collect | unlimited |
| `--proxy` | Proxy (`host:port:user:pass`) | `META_ADS_PROXY` env |
| `--no-proxy` | Disable proxy | `false` |
| `--delay` | Delay between requests (seconds) | `2.0` |
| `--timeout` | Request timeout (seconds) | `30` |
| `-v, --verbose` | Debug logging | `false` |

## Python API Reference

### MetaAdsCollector

```python
from meta_ads_collector import MetaAdsCollector

collector = MetaAdsCollector(
    proxy="host:port:user:pass",   # optional
    rate_limit_delay=2.0,          # seconds between requests
    timeout=30,                    # request timeout
)
```

**Methods:**

- `search(...)` - Iterator yielding `Ad` objects
- `collect(...)` - Returns `list[Ad]`
- `collect_to_json(output_path, ...)` - Save to JSON file
- `collect_to_csv(output_path, ...)` - Save to CSV file
- `collect_to_jsonl(output_path, ...)` - Save to JSONL file
- `get_stats()` - Collection statistics

### Ad Model

Each `Ad` object contains:

- `id`, `page` (PageInfo), `is_active`, `ad_status`
- `creatives` (list of AdCreative with body, title, image_url, video_url, etc.)
- `impressions` (ImpressionRange), `spend` (SpendRange), `currency`
- `publisher_platforms`, `languages`, `funding_entity`, `disclaimer`
- `delivery_start_time`, `delivery_stop_time`
- `age_gender_distribution`, `region_distribution`

### Exceptions

All exceptions inherit from `MetaAdsError`:

| Exception | When |
|-----------|------|
| `AuthenticationError` | Session init or token extraction fails |
| `RateLimitError` | API rate limit hit |
| `SessionExpiredError` | Session expired and refresh failed |
| `ProxyError` | Invalid proxy format or unreachable proxy |
| `InvalidParameterError` | Invalid parameter value passed to API |

## Export Formats

- **JSON** - Full metadata + ads array, pretty-printed
- **CSV** - Flattened schema (24 columns), one row per ad
- **JSONL** - One JSON object per line, streaming-friendly

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Type check
mypy meta_ads_collector/
```

## License

[MIT](LICENSE)
