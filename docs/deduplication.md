# Deduplication Guide

`DeduplicationTracker` prevents collecting the same ad twice. It supports two modes: in-memory tracking for single runs, and persistent SQLite-backed tracking for incremental collection across scheduled runs.

## In-memory mode

State lives in a Python `set`. Fast, but lost when the process exits.

```python
from meta_ads_collector import MetaAdsCollector, DeduplicationTracker

tracker = DeduplicationTracker(mode="memory")

with MetaAdsCollector() as collector:
    for ad in collector.search(query="test", dedup_tracker=tracker):
        print(ad.id)  # Each ad ID appears only once

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

# State is saved automatically via context manager
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
        process(ad)

# Record this run's timestamp for next time
tracker.update_collection_time()
tracker.save()
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
tracker = DeduplicationTracker(mode="memory")        # In-memory
tracker = DeduplicationTracker(mode="persistent", db_path="state.db")  # SQLite
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
with DeduplicationTracker(mode="persistent", db_path="state.db") as tracker:
    tracker.mark_seen("12345")
    # Automatically saves and closes on exit
```
