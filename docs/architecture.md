# Architecture

This page describes the main components in MetaAdsCollector 1.4.2. It is a source-oriented overview; Meta's internal endpoints and response formats can change independently of this package.

## Components

| Component | Main responsibility |
|---|---|
| `MetaAdsCollector` (`collector.py`) | Synchronous search, pagination, client-side filters, deduplication, events, media, enrichment, and export |
| `AsyncMetaAdsCollector` (`async_collector.py`) | Asynchronous search and export using the async client |
| `MetaAdsClient` (`client.py`) | HTTP session, session initialization, GraphQL requests, page search, and ad detail requests |
| `AsyncMetaAdsClient` (`async_client.py`) | Async HTTP implementation with shared parsing and payload logic |
| `models.py` | Converts response dictionaries into `Ad`, `AdCreative`, and related data classes |
| `filters.py` | Client-side `FilterConfig` and `passes_filter()` |
| `dedup.py` | In-memory or SQLite-backed ad ID tracking |
| `events.py`, `webhooks.py` | Collection events and optional HTTP webhook delivery |
| `media.py`, `proxy_pool.py` | Media downloads and optional proxy selection |
| `cli.py`, `__main__.py` | Command-line interface and `python -m meta_ads_collector` entry point |

## Search flow

At a high level, a search:

1. Validates the requested ad type, status, search type, sort mode, and country-code shape.
2. Requests result pages through the client and follows returned pagination cursors.
3. Parses each response item into an `Ad` object.
4. Applies optional deduplication and client-side filters, then yields matching ads.
5. Emits lifecycle events and records collection statistics. Export helpers write results as JSON, CSV, or JSONL.

The exact internal request fields and response structure are implementation details of Meta's internal API, not a stable public contract. A change on Meta's side can make a search fail or cause fields to be absent. Ad fields are optional because Meta does not return every detail for every ad.

## Data parsing

`Ad.from_graphql_response()` accepts the response shapes currently handled by this version, including known snake-case and camel-case variants and multiple creative layouts. It normalizes common creative, page, delivery, and transparency data into the package's data classes. Use `include_raw=True` when exporting JSON if you need the raw response dictionary as well as the normalized fields.

The `Ad` schema is not a promise that Meta supplies every field. Some fields are category- or region-specific; others may be missing or change without notice. See the [API reference](api-reference.md) for the fields represented by the package.

## Sync and async use

The synchronous collector exposes iterator-based `search()` and list-based `collect()` interfaces. The asynchronous collector exposes an async iterator for `search()` and async methods for its supported collection/export operations. The two interfaces are similar, but consult the [async guide](async.md) for the methods documented for the asynchronous version.

## Operational notes

- No Meta API key is required because the package does not use Meta's official Ad Library Graph API.
- Meta may change internal endpoints, challenge requests, impose limits, or block access. Retries and session refresh cannot guarantee a successful collection.
- Proxies and browser-style TLS impersonation are connection options; neither guarantees access or bypasses Meta's controls.
- Review Meta's current policies and terms before using the package, especially for collection, storage, and reuse of ad data.

## Source links

- [Synchronous collector](https://github.com/promisingcoder/MetaAdsCollector/blob/main/meta_ads_collector/collector.py)
- [Asynchronous collector](https://github.com/promisingcoder/MetaAdsCollector/blob/main/meta_ads_collector/async_collector.py)
- [Data models](https://github.com/promisingcoder/MetaAdsCollector/blob/main/meta_ads_collector/models.py)
- [Command-line interface](https://github.com/promisingcoder/MetaAdsCollector/blob/main/meta_ads_collector/cli.py)
