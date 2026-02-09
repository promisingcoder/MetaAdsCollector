# Architecture

This document describes the internal architecture of `meta-ads-collector`. It is intended for contributors and anyone interested in understanding how the library works under the hood.

## Overview

`meta-ads-collector` is a layered Python library that reverse-engineers Meta's internal GraphQL API to collect ads from the Facebook Ad Library. The library is organized into a **client layer** (low-level HTTP and GraphQL) and a **collector layer** (high-level search, pagination, and export).

```
+--------------------------------------------------------------+
|                       Public API                             |
|   MetaAdsCollector  /  AsyncMetaAdsCollector  /  CLI         |
+--------------------------------------------------------------+
|                    Collector Layer                            |
|   Pagination  |  Filtering  |  Dedup  |  Events  |  Export   |
+--------------------------------------------------------------+
|                     Client Layer                             |
|   MetaAdsClient  /  AsyncMetaAdsClient                       |
|   Session Mgmt  |  Token Extraction  |  GraphQL Requests     |
+--------------------------------------------------------------+
|                    Support Modules                            |
|   Fingerprint  |  ProxyPool  |  Media  |  Webhooks  |  URL   |
+--------------------------------------------------------------+
```

## Module Inventory

| Module | Layer | Responsibility |
|---|---|---|
| `collector.py` | Collector | High-level search, pagination, export, media, enrichment |
| `async_collector.py` | Collector | Async mirror of `collector.py` using `httpx` |
| `client.py` | Client | Session management, token extraction, GraphQL requests |
| `async_client.py` | Client | Async mirror of `client.py`, delegates logic to sync client |
| `models.py` | Data | `Ad`, `AdCreative`, `PageInfo`, `PageSearchResult`, etc. |
| `filters.py` | Collector | Client-side `FilterConfig` and `passes_filter()` |
| `dedup.py` | Collector | `DeduplicationTracker` (memory and SQLite modes) |
| `events.py` | Collector | `EventEmitter` with 7 lifecycle event types |
| `webhooks.py` | Collector | `WebhookSender` for POSTing ad data to external endpoints |
| `media.py` | Support | `MediaDownloader` for images, videos, thumbnails |
| `proxy_pool.py` | Support | Round-robin `ProxyPool` with failure tracking |
| `fingerprint.py` | Support | `BrowserFingerprint` generation for detection avoidance |
| `url_parser.py` | Support | `extract_page_id_from_url()` for Facebook URL parsing |
| `constants.py` | Support | All constants: doc IDs, fallback tokens, valid parameter sets |
| `exceptions.py` | Support | Exception hierarchy rooted at `MetaAdsError` |
| `logging_config.py` | Support | `JSONFormatter` and `setup_logging()` helper |
| `reporting.py` | Support | `CollectionReport` dataclass and formatting functions |
| `cli.py` | CLI | `argparse`-based command-line interface |
| `__init__.py` | Package | Public API exports and `__version__` |
| `__main__.py` | Package | `python -m meta_ads_collector` entry point |

## Request Lifecycle

A typical ad collection follows this path:

### 1. Initialization

```
MetaAdsCollector.__init__()
  -> MetaAdsClient.__init__()
       -> generate_fingerprint()          # Random but consistent browser identity
       -> ProxyPool() or _setup_proxy()   # If proxy configured
       -> session.headers.update(...)     # Apply fingerprint headers
```

### 2. Session Bootstrap (Lazy)

On the first `search()` call, if `_initialized` is `False`:

```
MetaAdsClient.initialize()
  -> Generate datr cookie (device fingerprint)
  -> Set wd and dpr cookies (viewport dimensions)
  -> GET /ads/library/?active_status=active&ad_type=all&country=US
  -> If 403 or challenge detected:
       -> _handle_challenge()             # POST to /__rd_verify_* endpoint
       -> Retry the GET
  -> _extract_tokens(html)                # LSD, __rev, __spin_*, __hsi, fb_dtsg, __dyn, __csr, jazoest
  -> _extract_doc_ids(html)               # Dynamic GraphQL doc_ids from page JS
  -> _verify_tokens()                     # Ensure LSD token is present
  -> Set fallback values for missing tokens
  -> _initialized = True
```

### 3. Token Extraction

`_extract_tokens()` uses regex patterns to find tokens embedded in the server-rendered HTML:

| Token | Purpose | Patterns |
|---|---|---|
| `lsd` | CSRF protection (mandatory) | `"LSD",[],{"token":"..."}`, `name="lsd" value="..."` |
| `__rev` / `__spin_r` | Build revision | `"__spin_r":12345`, `"server_revision":12345` |
| `__spin_t` | Timestamp | `"__spin_t":12345` |
| `__hsi` | Session ID | `"hsi":"12345"` |
| `fb_dtsg` | DTSG token | `"DTSGInitialData",[],{"token":"..."}` |
| `__dyn` | Dynamic modules hash | `"__dyn":"..."` |
| `__csr` | CSR hash | `"__csr":"..."` |
| `jazoest` | Anti-abuse token | `"jazoest":12345` or computed from LSD |

Fallback values from `constants.py` are used when extraction fails.

### 4. Doc ID Extraction

`_extract_doc_ids()` attempts to find GraphQL document IDs from the page's bundled JavaScript. Three regex patterns are tried:

1. `__d("AdLibrary...Query...")` with nearby numeric ID
2. `"name":"AdLibrary...Query"` near `"queryID":"..."`
3. Reverse order: `"queryID":"..."` near `"name":"AdLibrary...Query"`

If extraction fails, hardcoded fallback IDs from `constants.py` are used (`DOC_ID_SEARCH`, `DOC_ID_TYPEAHEAD`).

### 5. GraphQL Search Request

```
MetaAdsCollector.search()
  -> _validate_params()                   # Check ad_type, status, search_type, sort_by, country
  -> event_emitter.emit(COLLECTION_STARTED, ...)
  -> Loop:
       -> MetaAdsClient.search_ads()
            -> _build_graphql_payload()    # Build form data with all tokens
            -> _make_graphql_request()     # POST to /api/graphql/ with auto-refresh
                 -> _make_request()        # Retry logic, proxy rotation
            -> _parse_search_response()    # Navigate nested JSON structure
       -> For each ad in response:
            -> Ad.from_graphql_response()  # Parse into Ad dataclass
            -> dedup_tracker.has_seen()    # Skip duplicates
            -> passes_filter()            # Client-side filtering
            -> yield ad                   # Return to caller
       -> Check next_cursor for pagination
       -> _delay()                        # Rate limiting with jitter
  -> event_emitter.emit(COLLECTION_FINISHED, ...)
```

### 6. Response Parsing

The GraphQL response has a nested structure:

```
{
  "data": {
    "ad_library_main": {
      "search_results_connection": {
        "edges": [
          {
            "node": {
              "collated_results": [
                { "ad_archive_id": "...", "snapshot": { ... } }
              ]
            }
          }
        ],
        "page_info": {
          "has_next_page": true,
          "end_cursor": "..."
        }
      }
    }
  }
}
```

Both snake_case and camelCase field names are handled, as Meta's API is inconsistent.

## Session Management

### Staleness Detection

Sessions become stale after `MAX_SESSION_AGE` (30 minutes by default). Before each request, `_is_session_stale()` checks the elapsed time and triggers a refresh if needed.

### Automatic Refresh

`_refresh_session()` performs a full re-initialization:

1. Close the old `requests.Session`
2. Generate a new `BrowserFingerprint`
3. Create a fresh session with new headers
4. Re-run `initialize()` to get new tokens
5. Track consecutive refresh failures to prevent infinite loops

If `max_refresh_attempts` consecutive refreshes fail, `SessionExpiredError` is raised.

### GraphQL Auto-Refresh

`_make_graphql_request()` handles 403 responses by:

1. Calling `_refresh_session()`
2. Rebuilding the payload with new tokens
3. Retrying the request once

## Detection Avoidance

### Browser Fingerprinting

`fingerprint.py` generates randomized but internally-consistent browser identities. Each session gets a unique combination of:

- **Chrome version**: Randomly selected from 8 recent versions (125--132)
- **Platform**: Windows or macOS with matching User-Agent OS string and `sec-ch-ua-platform`
- **Viewport**: 8 common screen resolutions
- **DPR**: 5 device pixel ratio values
- **"Not A Brand" hint**: 4 variations matching real Chrome behavior

All headers derived from the fingerprint are self-consistent -- the Chrome version in the User-Agent matches `sec-ch-ua`, the platform in the UA matches `sec-ch-ua-platform`, etc.

### Request Mimicry

The client replicates the exact request patterns of a real browser:

- Initial page load uses `sec-fetch-site: none` (direct navigation)
- GraphQL requests use `sec-fetch-site: same-origin` with correct `referer`
- `x-fb-friendly-name` and `x-fb-lsd` headers match Facebook's internal patterns
- The `datr` cookie (device fingerprint) is generated with the correct format
- Request counter is encoded in base-36 (`__req` field)

### Rate Limiting

Multiple layers of rate limiting:

1. **Base delay**: `rate_limit_delay` seconds between requests (default 2.0)
2. **Jitter**: Random additional delay up to `jitter` seconds (default 1.0)
3. **Backoff on 429**: Exponential backoff with random jitter
4. **Human-like delay**: Random 1.5--3.0 second delay after initialization

## Proxy Support

`ProxyPool` provides round-robin proxy rotation with health tracking:

- **Failure tracking**: Per-proxy consecutive failure counter
- **Dead proxy exclusion**: After `max_failures` (default 3), proxy is marked dead
- **Cooldown recovery**: Dead proxies are retried after `cooldown` seconds (default 300)
- **Automatic rotation**: `get_next()` cycles through alive proxies
- **Success reset**: Successful requests reset the failure counter and revive dead proxies

Supported proxy formats:
- `host:port`
- `host:port:user:pass`
- `http://user:pass@host:port`
- `socks5://host:port`

## Event System

`EventEmitter` provides a synchronous pub-sub system with **exception isolation**. Callbacks that raise exceptions are logged but never propagate to the collection pipeline.

Seven lifecycle events:

| Event | Emitted When |
|---|---|
| `collection_started` | Before the first API request |
| `ad_collected` | After each ad passes filters |
| `page_fetched` | After each API page is retrieved |
| `error_occurred` | On any error during collection |
| `rate_limited` | When the API returns a rate limit response |
| `session_refreshed` | When the session is refreshed |
| `collection_finished` | After the last page or on early termination |

## Async Architecture

`AsyncMetaAdsClient` uses composition (not inheritance) with the sync `MetaAdsClient`:

```python
self._logic = MetaAdsClient.__new__(MetaAdsClient)  # No __init__ call
```

All pure-logic methods (token extraction, payload building, response parsing) are delegated to `_logic`. Only HTTP methods are reimplemented using `httpx.AsyncClient`.

`AsyncMetaAdsCollector` mirrors `MetaAdsCollector` method-for-method, using `async def` and `async for` throughout.

## Data Model

`Ad.from_graphql_response()` handles the messy reality of Meta's API:

- Both snake_case (`ad_archive_id`) and camelCase (`adArchiveID`) field names
- Nested structures (snapshot inside node inside edge)
- Multiple creative formats (cards array vs. separate body/title arrays)
- Optional fields that may be present in some responses but not others
- Timestamps as both ISO strings and Unix integers
- Platform names as both strings and arrays

The method normalizes all of this into a clean `Ad` dataclass with typed fields.
