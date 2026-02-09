# Media Downloads Guide

Download images, videos, and thumbnails from ad creatives to your local filesystem.

## Quick start

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad, media_results in collector.collect_with_media(
        query="fashion",
        country="US",
        max_results=20,
        media_output_dir="./fashion_media",
    ):
        for result in media_results:
            if result.success:
                print(f"  {result.media_type}: {result.local_path}")
```

## How it works

For each ad creative, the downloader attempts to download every available media URL:

| Media Type | Source Field | Description |
|---|---|---|
| `image` | `creative.image_url` | Main creative image |
| `video_hd` | `creative.video_hd_url` | HD video |
| `video_sd` | `creative.video_sd_url` | SD video |
| `thumbnail` | `creative.thumbnail_url` | Video preview/thumbnail image |

Files are saved as `{ad_id}_{creative_index}_{media_type}.{ext}`, for example:
- `123456_0_image.jpg`
- `123456_0_video_hd.mp4`
- `123456_1_thumbnail.webp`

## File extension detection

Extensions are resolved in priority order:

1. Recognizable extension in the URL path (e.g., `.jpg`, `.mp4`)
2. `Content-Type` header from the HTTP response
3. Fallback: `.bin`

## Collect with media

The `collect_with_media()` method on `MetaAdsCollector` yields `(Ad, list[MediaDownloadResult])` tuples:

```python
with MetaAdsCollector() as collector:
    for ad, results in collector.collect_with_media(
        query="tech",
        media_output_dir="./media",
        max_results=50,
    ):
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        print(f"Ad {ad.id}: {len(successful)} downloaded, {len(failed)} failed")
```

If media downloading fails for an ad, the ad is still yielded with an empty results list. Ad data is never lost due to media download failures.

## Download media for a single ad

```python
with MetaAdsCollector() as collector:
    ad = next(collector.search(query="test", max_results=1))
    results = collector.download_ad_media(ad, output_dir="./single_ad_media")

    for r in results:
        print(f"{r.media_type}: success={r.success}, path={r.local_path}")
```

## Using MediaDownloader directly

```python
from meta_ads_collector import MediaDownloader

downloader = MediaDownloader(
    output_dir="./media",
    timeout=30,
    max_retries=2,
)

results = downloader.download_ad_media(ad)
```

## MediaDownloadResult

Each download attempt produces a `MediaDownloadResult`:

| Field | Type | Description |
|---|---|---|
| `ad_id` | `str` | The ad archive ID |
| `creative_index` | `int` | Zero-based index of the creative |
| `media_type` | `str` | `image`, `video_hd`, `video_sd`, or `thumbnail` |
| `url` | `str` | The source URL |
| `local_path` | `str` or `None` | Absolute path to the downloaded file |
| `success` | `bool` | Whether the download succeeded |
| `error` | `str` or `None` | Error message on failure |
| `file_size` | `int` or `None` | File size in bytes on success |

## CLI usage

```bash
# Download media alongside ad collection
meta-ads-collector -q "fashion" --download-media --media-dir ./fashion_media -o ads.json

# Custom media directory
meta-ads-collector -q "tech" --download-media --media-dir /data/ad_media -o tech.json
```

## Retry behavior

Downloads retry up to `max_retries` times (default 2) with exponential backoff. HTTP 403 responses (expired URLs) are not retried since they indicate the CDN token has expired.

Existing files with non-zero size are skipped automatically.
