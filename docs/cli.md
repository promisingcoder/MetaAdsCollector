# CLI Reference

The `meta-ads-collector` command-line tool provides full access to all library features.

## Usage

```
meta-ads-collector [OPTIONS]
python -m meta_ads_collector [OPTIONS]
```

## All flags

### Search Parameters

| Flag | Description | Default |
|---|---|---|
| `-q, --query TEXT` | Search query string | `""` (all ads) |
| `-c, --country CODE` | ISO 3166-1 alpha-2 country code (e.g., US, EG, GB, DE) | `US` |
| `-t, --ad-type TYPE` | Ad type: `all`, `political`, `housing`, `employment`, `credit` | `all` |
| `-s, --status STATUS` | Ad status: `active`, `inactive`, `all` | `active` |
| `--search-type TYPE` | Search type: `keyword`, `exact`, `page` | `keyword` |
| `--sort-by MODE` | Sort order: `relevancy`, `impressions` | `impressions` |
| `--page-ids ID [ID ...]` | Filter by specific page IDs (space-separated) | |

### Page-Level Collection

| Flag | Description |
|---|---|
| `--search-pages QUERY` | Search for pages by name, print results and exit |
| `--page-url URL` | Collect ads from a Facebook page identified by URL |
| `--page-name NAME` | Search for a page by name, then collect its ads |

### Output

| Flag | Description | Default |
|---|---|---|
| `-o, --output PATH` | Output file path (`.json`, `.csv`, `.jsonl`) | **required** |
| `-n, --max-results N` | Maximum number of ads to collect | unlimited |
| `--page-size N` | Results per API request (max ~30) | `10` |
| `--include-raw` | Include raw API response data in JSON output | `false` |

### Filtering

| Flag | Description |
|---|---|
| `--min-impressions N` | Minimum impressions (client-side filter) |
| `--max-impressions N` | Maximum impressions (client-side filter) |
| `--min-spend N` | Minimum spend amount |
| `--max-spend N` | Maximum spend amount |
| `--start-date DATE` | Only ads starting on or after this date (ISO 8601, e.g., 2024-01-01) |
| `--end-date DATE` | Only ads starting on or before this date (ISO 8601) |
| `--media-type TYPE` | Filter by media type: `all`, `image`, `video`, `meme`, `none` |
| `--publisher-platform PLAT` | Filter by platform (repeatable, e.g., `--publisher-platform facebook`) |
| `--language LANG` | Filter by language code (repeatable, e.g., `--language en --language es`) |
| `--has-video` | Only include ads with video content |
| `--has-image` | Only include ads with image content |

### Connection

| Flag | Description | Default |
|---|---|---|
| `--proxy PROXY` | Proxy in format `host:port:user:pass` | `META_ADS_PROXY` env |
| `--proxy-file PATH` | Path to file with one proxy per line (for rotation) | |
| `--timeout N` | Request timeout in seconds | `30` |
| `--delay N` | Delay between requests in seconds | `2.0` |
| `--no-proxy` | Disable proxy usage entirely | `false` |

### Media Downloads

| Flag | Description | Default |
|---|---|---|
| `--download-media` | Download images, videos, and thumbnails | `false` |
| `--no-download-media` | Explicitly disable media downloading | |
| `--media-dir PATH` | Directory for downloaded media files | `./ad_media` |

### Enrichment

| Flag | Description | Default |
|---|---|---|
| `--enrich` | Fetch additional detail data for each ad | `false` |
| `--no-enrich` | Explicitly disable enrichment | |

### Deduplication

| Flag | Description | Default |
|---|---|---|
| `--deduplicate, --dedup` | Enable in-memory deduplication within this run | `false` |
| `--state-file PATH` | Path to SQLite file for persistent deduplication | |
| `--since-last-run` | Only collect ads newer than the last collection (requires `--state-file`) | `false` |

### Webhooks

| Flag | Description |
|---|---|
| `--webhook-url URL` | POST each collected ad as JSON to this URL |

### Logging

| Flag | Description | Default |
|---|---|---|
| `--log-format FORMAT` | Log format: `text` (human-readable) or `json` (machine-readable) | `text` |
| `--log-file PATH` | Also write log output to this file | |
| `-v, --verbose` | Enable debug-level logging | `false` |

### Reporting

| Flag | Description | Default |
|---|---|---|
| `--report` | Print collection summary report to stdout | `false` |
| `--report-file PATH` | Save the collection report as JSON to this file | |

## Examples

### Basic searches

```bash
# All active ads mentioning "solar panels" in the US
meta-ads-collector -q "solar panels" -c US -o solar.json

# Political ads from Egypt
meta-ads-collector -c EG -t political -o egypt_political.csv

# All housing ads, sorted by relevancy
meta-ads-collector -t housing --sort-by relevancy -o housing.json

# Exact phrase matching with result limit
meta-ads-collector -q "buy now" --search-type exact -n 500 -o buy_now.jsonl
```

### Page-level collection

```bash
# Search for pages by name
meta-ads-collector --search-pages "Coca-Cola" -c US

# Collect ads from a specific page URL
meta-ads-collector --page-url "https://www.facebook.com/ads/library/?view_all_page_id=123456" -o page_ads.json

# Resolve a page name and collect its ads
meta-ads-collector --page-name "Nike" -c US -o nike_ads.json
```

### Filtering

```bash
# High-impression video ads
meta-ads-collector -q "SaaS" --min-impressions 10000 --has-video -o saas_videos.json

# Date-range filtering
meta-ads-collector -q "election" --start-date 2024-01-01 --end-date 2024-11-05 -o election.json

# Multi-platform, multi-language
meta-ads-collector -q "finance" \
    --publisher-platform facebook \
    --publisher-platform instagram \
    --language en \
    --language es \
    -o finance.json
```

### Advanced workflows

```bash
# Incremental collection with deduplication
meta-ads-collector -q "crypto" --state-file crypto_state.db --since-last-run -o new_crypto.jsonl

# Download media alongside collection
meta-ads-collector -q "fashion" --download-media --media-dir ./fashion_media -o fashion.json

# Enrich ads with snapshot data
meta-ads-collector -q "test" --enrich -o enriched.json

# Webhook integration
meta-ads-collector -q "competitors" --webhook-url "https://hooks.example.com/ads" -o competitors.json

# Full logging with report
meta-ads-collector -q "test" \
    --log-format json \
    --log-file collection.log \
    --report \
    --report-file report.json \
    -v \
    -o test.json

# Proxy rotation
meta-ads-collector -q "test" --proxy-file proxies.txt --delay 3.0 -o ads.json
```
