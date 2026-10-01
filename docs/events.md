# Events & Webhooks Guide

`meta-ads-collector` emits lifecycle events during collection that you can hook into with callbacks or forward to external services via webhooks.

## Event types

| Event Constant | String Value | Data Keys | When |
|---|---|---|---|
| `COLLECTION_STARTED` | `"collection_started"` | `query`, `country`, `ad_type`, `status`, `search_type`, `page_ids`, `max_results` | Search begins |
| `AD_COLLECTED` | `"ad_collected"` | `ad` (Ad object) | Each ad is collected |
| `PAGE_FETCHED` | `"page_fetched"` | `page_number`, `ads_on_page`, `has_next_page` | API page is fetched |
| `ERROR_OCCURRED` | `"error_occurred"` | `exception`, `context` | An error occurs |
| `RATE_LIMITED` | `"rate_limited"` | `wait_seconds`, `retry_count` | Rate limiting detected |
| `SESSION_REFRESHED` | `"session_refreshed"` | `reason` | Session is refreshed |
| `COLLECTION_FINISHED` | `"collection_finished"` | `total_ads`, `total_pages`, `duration_seconds` | Search completes |

## Registering callbacks

### Using event_emitter.on()

```python
from meta_ads_collector import MetaAdsCollector, AD_COLLECTED, COLLECTION_FINISHED

def on_ad(event):
    ad = event.data["ad"]
    print(f"Collected: {ad.id} from {ad.page.name if ad.page is not None else 'Unknown page'}")

def on_finished(event):
    data = event.data
    print(f"Done: {data['total_ads']} ads in {data['duration_seconds']:.1f}s")

with MetaAdsCollector() as collector:
    collector.event_emitter.on(AD_COLLECTED, on_ad)
    collector.event_emitter.on(COLLECTION_FINISHED, on_finished)

    for ad in collector.search(query="test", max_results=10):
        pass
```

### Using the callbacks parameter

Register callbacks at collector initialization:

```python
from meta_ads_collector import MetaAdsCollector

def on_ad(event):
    print(f"Collected: {event.data['ad'].id}")

def on_finished(event):
    print(f"Finished: {event.data['total_ads']} ads")

with MetaAdsCollector(callbacks={
    "ad_collected": on_ad,
    "error_occurred": lambda event: print(f"Error: {event.data['context']}"),
    "collection_finished": on_finished,
}) as collector:
    for ad in collector.search(query="test", max_results=10):
        pass
```

### Removing callbacks

Use `off()` on the emitter where the callback was registered:

```python
from meta_ads_collector import MetaAdsCollector, AD_COLLECTED

def on_ad(event):
    print(event.data["ad"].id)

with MetaAdsCollector() as collector:
    collector.event_emitter.on(AD_COLLECTED, on_ad)
    collector.event_emitter.off(AD_COLLECTED, on_ad)
```

## Event object

Each callback receives an `Event` object:

```python
from meta_ads_collector import Event

# Construct an example event to inspect the event model.
event = Event(event_type="ad_collected", data={"ad": None})
print(event.event_type)  # e.g., "ad_collected"
print(event.data)        # event-specific payload
print(event.timestamp)   # UTC timestamp
```

## Exception isolation

Callbacks are exception-isolated. If a callback raises an exception, it is logged as a warning but does not crash the collection pipeline. Other callbacks and the collection continue normally.

## Stream mode

The `stream()` method yields `(event_type, data)` tuples for all lifecycle events through a single iterator:

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for event_type, data in collector.stream(query="test", max_results=10):
        if event_type == "collection_started":
            print(f"Starting search for: {data['query']}")
        elif event_type == "ad_collected":
            print(f"Ad: {data['ad'].id}")
        elif event_type == "page_fetched":
            print(f"Page {data['page_number']}: {data['ads_on_page']} ads")
        elif event_type == "rate_limited":
            print(f"Rate limited, waiting {data['wait_seconds']:.0f}s")
        elif event_type == "collection_finished":
            print(f"Finished: {data['total_ads']} ads in {data['duration_seconds']:.1f}s")
```

## Webhooks

### WebhookSender

POST ad data to an external HTTP endpoint as JSON:

```python
from meta_ads_collector import MetaAdsCollector, WebhookSender, AD_COLLECTED

sender = WebhookSender(
    url="https://hooks.example.com/ads",
    retries=3,       # Retry up to 3 times on failure
    batch_size=1,    # Send immediately (no batching)
    timeout=10,      # 10 second timeout per request
)

with MetaAdsCollector() as collector:
    collector.event_emitter.on(AD_COLLECTED, sender.as_callback())
    for ad in collector.search(query="test", max_results=10):
        pass  # Each ad is POSTed to the webhook URL
```

### Batch mode

Buffer ads and send them in batches:

```python
from meta_ads_collector import MetaAdsCollector, WebhookSender, AD_COLLECTED

sender = WebhookSender(
    url="https://hooks.example.com/ads",
    batch_size=10,  # Send every 10 ads
)

with MetaAdsCollector() as collector:
    collector.event_emitter.on(AD_COLLECTED, sender.as_callback())
    for ad in collector.search(query="test", max_results=100):
        pass

    # Flush remaining buffered ads
    sender.flush()
```

### Manual webhook sends

```python
from meta_ads_collector import WebhookSender

sender = WebhookSender(url="https://hooks.example.com/ads")

# Send a single payload
success = sender.send({"ad_id": "12345", "page": "Test Page"})

# Send a batch of JSON-serializable payloads
success = sender.send_batch([
    {"ad_id": "12345", "page": "Test Page"},
    {"ad_id": "67890", "page": "Another Page"},
])
```

### CLI webhook

```bash
meta-ads-collector -q "test" --webhook-url "https://hooks.example.com/ads" -o ads.json
```

## Retry behavior

`WebhookSender` retries failed POST requests with exponential backoff (0.1s * 2^attempt). All methods are safe -- they catch exceptions internally and return `True`/`False` instead of raising.
