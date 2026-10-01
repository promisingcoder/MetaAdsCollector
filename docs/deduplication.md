# Deduplication Guide

`DeduplicationTracker` skips ad IDs already recorded by that tracker. It supports in-memory tracking for one process and persistent SQLite-backed tracking across runs. It does not deduplicate across separate database files or different tracker instances.

## In-memory mode

State lives in a Python `set`. Fast, but lost when the process exits.

```python
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker

tracker = DeduplicationTracker(mode="memory")

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", dedup_tracker=tracker):
        print(ad.id)  # IDs are deduplicated as the iterator is consumed.

print(f"Unique ads: {tracker.count()}")
```

## Persistent mode

State is stored in a SQLite database file. Survives across process restarts.

```python
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker

tracker = DeduplicationTracker(mode="persistent", db_path="collection_state.db")

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", dedup_tracker=tracker):
        print(ad.id)  # Skips ads seen in any previous run
tracker.close()

# The search generator saves tracker state and updates the last-collection time in its finalization logic when it finishes or is closed. The guarantee applies when the iterator is fully consumed; stopping immediately after a yield can stop before that ad is recorded.
```

The SQLite database contains two tables:
- `seen_ads` -- maps ad IDs to their first-seen timestamp
- `collection_runs` -- records the timestamp of each completed collection run

## Incremental collection

Combine persistent deduplication with date filtering to only collect new ads since the last run.

```python
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker, FilterConfig

tracker = DeduplicationTracker(mode="persistent", db_path="state.db")
last_run = tracker.get_last_collection_time()

# Only fetch ads newer than the last collection
filters = FilterConfig(start_date=last_run) if last_run else None

with MetaAdsCollector() as collector:
    for ad in collector.search(query="crypto", filter_config=filters, dedup_tracker=tracker):
        print(ad.id)  # Replace with your application's processing code.
tracker.close()
```

## CLI usage

```bash
# In-memory deduplication (within a single run)
meta-ads-collector -q "test" --dedup -o ads.json

# Persistent deduplication (across runs)
meta-ads-collector -q "test" --state-file state.db -o ads.json

# Incremental: only collect ads since the last run
meta-ads-collector -q "test" --state-file state.db --since-last-run -o new_ads.jsonl
```

## API reference

### DeduplicationTracker

```python
from meta_ads_collector import DeduplicationTracker

memory_tracker = DeduplicationTracker(mode="memory")
persistent_tracker = DeduplicationTracker(mode="persistent", db_path="state.db")
```

| Method | Description |
|---|---|
| `has_seen(ad_id)` | Returns `True` if the ad ID was previously recorded |
| `mark_seen(ad_id, timestamp=None)` | Record an ad ID as seen |
| `get_last_collection_time()` | Returns the datetime of the most recent completed run, or `None` |
| `update_collection_time()` | Record the current time as the latest collection run |
| `save()` | Persist changes to disk (persistent mode only; no-op for memory) |
| `load()` | Load state from disk (persistent mode only; no-op for memory) |
| `count()` | Number of unique ad IDs tracked |
| `clear()` | Remove all tracked state |
| `close()` | Close the database connection (persistent mode) |

### Context manager

`DeduplicationTracker` supports `with` for automatic save and close:

```python
from meta_ads_collector import DeduplicationTracker

with DeduplicationTracker(mode="persistent", db_path="state.db") as tracker:
    tracker.mark_seen("12345")
    # Automatically saves and closes on exit
```
