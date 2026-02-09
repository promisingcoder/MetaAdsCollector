#!/usr/bin/env python3
"""
Meta Ads Library Collector - CLI Entry Point

Usage:
    meta-ads-collector --query "real estate" --country US --max-results 100 --output ads.json
    python -m meta_ads_collector --query "climate" --ad-type political --output political_ads.csv
"""

import argparse
import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from . import MetaAdsCollector
from .logging_config import setup_logging as _setup_logging
from .models import Ad


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Collect ads from the Meta Ad Library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for real estate ads in the US
  meta-ads-collector --query "real estate" --country US --output ads.json

  # Collect political ads from Egypt
  meta-ads-collector --country EG --ad-type political --output egypt_political.json

  # Export to CSV with a limit
  meta-ads-collector --query "loans" --max-results 500 --output loans.csv

  # Use exact phrase matching
  meta-ads-collector --query "buy now" --search-type exact --output buy_now.json
        """,
    )

    # Page-level collection modes
    parser.add_argument(
        "--search-pages",
        metavar="QUERY",
        default=None,
        help="Search for Facebook pages by name (typeahead). Prints matching pages and exits.",
    )
    parser.add_argument(
        "--page-url",
        metavar="URL",
        default=None,
        help="Collect ads from a Facebook page identified by URL (e.g. Ad Library URL).",
    )
    parser.add_argument(
        "--page-name",
        metavar="NAME",
        default=None,
        help="Search for a page by name, then collect its ads. Uses the first typeahead result.",
    )

    # Search parameters
    parser.add_argument(
        "-q", "--query",
        default="",
        help="Search query string (default: empty for all ads)",
    )
    parser.add_argument(
        "-c", "--country",
        default="US",
        help="Country code (e.g., US, EG, GB, DE) (default: US)",
    )
    parser.add_argument(
        "-t", "--ad-type",
        choices=["all", "political", "housing", "employment", "credit"],
        default="all",
        help="Type of ads to collect (default: all)",
    )
    parser.add_argument(
        "-s", "--status",
        choices=["active", "inactive", "all"],
        default="active",
        help="Ad status filter (default: active)",
    )
    parser.add_argument(
        "--search-type",
        choices=["keyword", "exact", "page"],
        default="keyword",
        help="Search type (default: keyword)",
    )
    parser.add_argument(
        "--sort-by",
        choices=["relevancy", "impressions"],
        default="impressions",
        help="Sort order: relevancy (server default) or impressions (default: impressions)",
    )
    parser.add_argument(
        "--page-ids",
        nargs="+",
        help="Filter by specific page IDs",
    )

    # Output options
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (.json, .csv, or .jsonl). Required for ad collection.",
    )
    parser.add_argument(
        "-n", "--max-results",
        type=int,
        default=None,
        help="Maximum number of ads to collect (default: no limit)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="Results per API request (default: 10, max: ~30)",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include raw API response data in JSON output",
    )

    # Filtering options
    parser.add_argument(
        "--min-impressions",
        type=int,
        default=None,
        help="Minimum impressions (client-side filter, uses upper_bound >= value)",
    )
    parser.add_argument(
        "--max-impressions",
        type=int,
        default=None,
        help="Maximum impressions (client-side filter, uses lower_bound <= value)",
    )
    parser.add_argument(
        "--min-spend",
        type=int,
        default=None,
        help="Minimum spend amount (client-side filter)",
    )
    parser.add_argument(
        "--max-spend",
        type=int,
        default=None,
        help="Maximum spend amount (client-side filter)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Only include ads starting on or after this date (ISO 8601, e.g. 2024-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Only include ads starting on or before this date (ISO 8601, e.g. 2024-12-31)",
    )
    parser.add_argument(
        "--media-type",
        choices=["all", "image", "video", "meme", "none"],
        default=None,
        help="Filter ads by media type (client-side filter)",
    )
    parser.add_argument(
        "--publisher-platform",
        action="append",
        default=None,
        dest="publisher_platforms",
        help="Filter by publisher platform (repeatable, e.g. --publisher-platform facebook)",
    )
    parser.add_argument(
        "--language",
        action="append",
        default=None,
        dest="filter_languages",
        help="Filter by language code (repeatable, e.g. --language en --language es)",
    )
    parser.add_argument(
        "--has-video",
        action="store_true",
        default=None,
        help="Only include ads with video content",
    )
    parser.add_argument(
        "--has-image",
        action="store_true",
        default=None,
        help="Only include ads with image content",
    )

    # Connection options
    parser.add_argument(
        "--proxy",
        default=os.environ.get("META_ADS_PROXY"),
        help="Proxy in format host:port:user:pass (or set META_ADS_PROXY env var)",
    )
    parser.add_argument(
        "--proxy-file",
        default=None,
        help="Path to a text file with one proxy per line (for proxy rotation)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay between requests in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable proxy usage",
    )

    # Webhook options
    parser.add_argument(
        "--webhook-url",
        default=None,
        metavar="URL",
        help="POST each collected ad as JSON to this webhook URL",
    )

    # Media download options
    parser.add_argument(
        "--download-media",
        action="store_true",
        default=False,
        help="Download images, videos, and thumbnails for collected ads",
    )
    parser.add_argument(
        "--no-download-media",
        action="store_true",
        default=False,
        help="Explicitly disable media downloading (default behavior)",
    )
    parser.add_argument(
        "--media-dir",
        default="./ad_media",
        help="Directory to save downloaded media files (default: ./ad_media)",
    )

    # Enrichment options
    parser.add_argument(
        "--enrich",
        action="store_true",
        default=False,
        help="Fetch additional detail data for each ad from the snapshot endpoint",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        default=False,
        help="Explicitly disable ad enrichment (default behavior)",
    )

    # Deduplication options
    parser.add_argument(
        "--deduplicate", "--dedup",
        action="store_true",
        default=False,
        help="Enable in-memory deduplication within this run",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        metavar="PATH",
        help="Path to a SQLite file for persistent deduplication across runs",
    )
    parser.add_argument(
        "--since-last-run",
        action="store_true",
        default=False,
        help="Only collect ads newer than the last collection timestamp (requires --state-file)",
    )

    # Logging options
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help="Log output format: text (human-readable) or json (machine-readable) (default: text)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Also write log output to this file",
    )

    # Reporting options
    parser.add_argument(
        "--report",
        action="store_true",
        default=False,
        help="Print a collection report summary to stdout after collection",
    )
    parser.add_argument(
        "--report-file",
        default=None,
        metavar="PATH",
        help="Save the collection report (JSON) to this file",
    )

    # Other options
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def map_ad_type(ad_type: str) -> str:
    """Map CLI ad type to API constant."""
    mapping = {
        "all": MetaAdsCollector.AD_TYPE_ALL,
        "political": MetaAdsCollector.AD_TYPE_POLITICAL,
        "housing": MetaAdsCollector.AD_TYPE_HOUSING,
        "employment": MetaAdsCollector.AD_TYPE_EMPLOYMENT,
        "credit": MetaAdsCollector.AD_TYPE_CREDIT,
    }
    return mapping.get(ad_type, MetaAdsCollector.AD_TYPE_ALL)


def map_status(status: str) -> str:
    """Map CLI status to API constant."""
    mapping = {
        "active": MetaAdsCollector.STATUS_ACTIVE,
        "inactive": MetaAdsCollector.STATUS_INACTIVE,
        "all": MetaAdsCollector.STATUS_ALL,
    }
    return mapping.get(status, MetaAdsCollector.STATUS_ACTIVE)


def map_search_type(search_type: str) -> str:
    """Map CLI search type to API constant."""
    mapping = {
        "keyword": MetaAdsCollector.SEARCH_KEYWORD,
        "exact": MetaAdsCollector.SEARCH_EXACT,
        "page": MetaAdsCollector.SEARCH_PAGE,
    }
    return mapping.get(search_type, MetaAdsCollector.SEARCH_KEYWORD)


def map_sort(sort_by: str):
    """Map CLI sort to API constant."""
    mapping = {
        "relevancy": MetaAdsCollector.SORT_RELEVANCY,
        "impressions": MetaAdsCollector.SORT_IMPRESSIONS,
    }
    return mapping.get(sort_by, MetaAdsCollector.SORT_IMPRESSIONS)


def build_filter_config(args: argparse.Namespace):
    """Build a :class:`FilterConfig` from parsed CLI arguments.

    Returns:
        A :class:`FilterConfig` instance, or ``None`` if no filter
        flags were provided.
    """
    from datetime import datetime as _dt

    from .filters import FilterConfig

    start_date = None
    if args.start_date:
        try:
            start_date = _dt.fromisoformat(args.start_date)
        except ValueError:
            logging.getLogger(__name__).error(
                "Invalid --start-date format: %s (expected ISO 8601)", args.start_date
            )

    end_date = None
    if args.end_date:
        try:
            end_date = _dt.fromisoformat(args.end_date)
        except ValueError:
            logging.getLogger(__name__).error(
                "Invalid --end-date format: %s (expected ISO 8601)", args.end_date
            )

    media_type = None
    if args.media_type is not None:
        media_type = args.media_type.upper()

    # has_video / has_image: argparse stores True when flag is present,
    # None when absent (since default=None)
    has_video = args.has_video if args.has_video is not None else None
    has_image = args.has_image if args.has_image is not None else None

    config = FilterConfig(
        min_impressions=args.min_impressions,
        max_impressions=args.max_impressions,
        min_spend=args.min_spend,
        max_spend=args.max_spend,
        start_date=start_date,
        end_date=end_date,
        media_type=media_type,
        publisher_platforms=args.publisher_platforms,
        languages=args.filter_languages,
        has_video=has_video,
        has_image=has_image,
    )

    if config.is_empty():
        return None
    return config


def _write_ads_to_file(
    ads_iter: Iterable[Ad],
    output_path: str,
    extension: str,
    include_raw: bool = False,
) -> int:
    """Write ads from an iterator to a file in the specified format.

    Args:
        ads_iter: Iterator of :class:`Ad` objects.
        output_path: Path to the output file.
        extension: File extension (`.json`, `.csv`, or `.jsonl`).
        include_raw: Whether to include raw API data in JSON output.

    Returns:
        Number of ads written.
    """
    import csv
    import json as _json

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    if extension == ".jsonl":
        with open(path, "w", encoding="utf-8") as f:
            for ad in ads_iter:
                f.write(_json.dumps(ad.to_dict(include_raw=include_raw), ensure_ascii=False))
                f.write("\n")
                count += 1
    elif extension == ".csv":
        columns = [
            "id", "page_id", "page_name", "page_url", "is_active", "ad_status",
            "delivery_start_time", "delivery_stop_time", "creative_body",
            "creative_title", "creative_description", "creative_link_url",
            "creative_image_url", "snapshot_url", "impressions_lower",
            "impressions_upper", "spend_lower", "spend_upper", "currency",
            "publisher_platforms", "languages", "funding_entity", "disclaimer",
            "ad_type", "collected_at",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for ad in ads_iter:
                primary = ad.creatives[0] if ad.creatives else None
                row = {
                    "id": ad.id,
                    "page_id": ad.page.id if ad.page else "",
                    "page_name": ad.page.name if ad.page else "",
                    "page_url": ad.page.page_url if ad.page else "",
                    "is_active": ad.is_active if ad.is_active is not None else "",
                    "ad_status": ad.ad_status or "",
                    "delivery_start_time": ad.delivery_start_time.isoformat() if ad.delivery_start_time else "",
                    "delivery_stop_time": ad.delivery_stop_time.isoformat() if ad.delivery_stop_time else "",
                    "creative_body": primary.body if primary else "",
                    "creative_title": primary.title if primary else "",
                    "creative_description": primary.description if primary else "",
                    "creative_link_url": primary.link_url if primary else "",
                    "creative_image_url": primary.image_url if primary else "",
                    "snapshot_url": ad.snapshot_url or ad.ad_snapshot_url or "",
                    "impressions_lower": ad.impressions.lower_bound if ad.impressions else "",
                    "impressions_upper": ad.impressions.upper_bound if ad.impressions else "",
                    "spend_lower": ad.spend.lower_bound if ad.spend else "",
                    "spend_upper": ad.spend.upper_bound if ad.spend else "",
                    "currency": ad.currency or "",
                    "publisher_platforms": ",".join(ad.publisher_platforms),
                    "languages": ",".join(ad.languages),
                    "funding_entity": ad.funding_entity or "",
                    "disclaimer": ad.disclaimer or "",
                    "ad_type": ad.ad_type or "",
                    "collected_at": ad.collected_at.isoformat(),
                }
                writer.writerow(row)
                count += 1
    else:
        # .json
        ads = []
        for ad in ads_iter:
            ads.append(ad.to_dict(include_raw=include_raw))
            count += 1
        with open(path, "w", encoding="utf-8") as f:
            _json.dump({"ads": ads, "total_count": count}, f, indent=2, ensure_ascii=False)

    return count


def _configure_proxy(args: argparse.Namespace):
    """Build a proxy configuration from CLI arguments.

    Returns:
        A proxy string, :class:`ProxyPool`, or ``None``.
    """
    if args.no_proxy:
        return None
    if args.proxy_file:
        from .proxy_pool import ProxyPool
        return ProxyPool.from_file(args.proxy_file)
    if args.proxy:
        return args.proxy
    return None


def _run_search_pages(args: argparse.Namespace) -> int:
    """Execute the --search-pages mode and print results."""
    import json as _json

    logger = logging.getLogger(__name__)
    proxy = _configure_proxy(args)

    try:
        with MetaAdsCollector(
            proxy=proxy,
            rate_limit_delay=args.delay,
            timeout=args.timeout,
        ) as collector:
            pages = collector.search_pages(
                query=args.search_pages,
                country=args.country.upper(),
            )

            if not pages:
                print(f"No pages found for query: {args.search_pages!r}")
                return 0

            print(f"Found {len(pages)} page(s):\n")
            for page in pages:
                print(f"  Page ID:  {page.page_id}")
                print(f"  Name:     {page.page_name}")
                if page.page_profile_uri:
                    print(f"  URL:      {page.page_profile_uri}")
                if page.category:
                    print(f"  Category: {page.category}")
                if page.page_like_count is not None:
                    print(f"  Likes:    {page.page_like_count:,}")
                print()

            # Also write JSON to output if specified
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    _json.dump(
                        [p.to_dict() for p in pages],
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                logger.info("Saved page results to %s", output_path)

            return 0

    except KeyboardInterrupt:
        logger.info("\nSearch interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Page search failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def main() -> int:
    """Main entry point."""
    args = parse_args()
    log_level = "DEBUG" if args.verbose else "INFO"
    _setup_logging(
        level=log_level,
        fmt=getattr(args, "log_format", "text"),
        log_file=getattr(args, "log_file", None),
    )

    logger = logging.getLogger(__name__)

    # --search-pages mode: search for pages and exit
    if args.search_pages:
        return _run_search_pages(args)

    # Output is required for ad collection mode
    if not args.output:
        logger.error("--output is required for ad collection. Use -o/--output <file>.")
        return 1

    # Determine output format from file extension
    output_path = Path(args.output)
    extension = output_path.suffix.lower()

    if extension not in [".json", ".csv", ".jsonl"]:
        logger.error(f"Unsupported output format: {extension}")
        logger.error("Supported formats: .json, .csv, .jsonl")
        return 1

    # Configure proxy
    proxy = _configure_proxy(args)

    # Create collector
    logger.info("Initializing Meta Ads Collector...")

    try:
        with MetaAdsCollector(
            proxy=proxy,
            rate_limit_delay=args.delay,
            timeout=args.timeout,
        ) as collector:

            # Register webhook if requested
            webhook_url = getattr(args, "webhook_url", None)
            if webhook_url:
                from .events import AD_COLLECTED
                from .webhooks import WebhookSender
                _sender = WebhookSender(url=webhook_url)
                collector.event_emitter.on(AD_COLLECTED, _sender.as_callback())
                logger.info("Webhook registered: %s", webhook_url)

            # Build filter config from CLI flags
            fc = build_filter_config(args)

            # Build deduplication tracker from CLI flags
            tracker = None
            if getattr(args, "state_file", None):
                from .dedup import DeduplicationTracker
                tracker = DeduplicationTracker(mode="persistent", db_path=args.state_file)
                logger.info("Persistent deduplication enabled: %s", args.state_file)
            elif getattr(args, "deduplicate", False):
                from .dedup import DeduplicationTracker
                tracker = DeduplicationTracker(mode="memory")
                logger.info("In-memory deduplication enabled")

            # --since-last-run: use start_date from last collection time
            if getattr(args, "since_last_run", False) and tracker is not None:
                last_run = tracker.get_last_collection_time()
                if last_run:
                    logger.info("Filtering ads since last run: %s", last_run.isoformat())
                    if fc is None:
                        from .filters import FilterConfig as _FC
                        fc = _FC(start_date=last_run)
                    elif fc.start_date is None:
                        fc.start_date = last_run
                else:
                    logger.info("No previous run found; collecting all ads")

            # Common parameters for standard search
            params: Optional[dict[str, Any]] = {
                "query": args.query,
                "country": args.country.upper(),
                "ad_type": map_ad_type(args.ad_type),
                "status": map_status(args.status),
                "search_type": map_search_type(args.search_type),
                "sort_by": map_sort(args.sort_by),
                "page_ids": args.page_ids,
                "max_results": args.max_results,
                "page_size": args.page_size,
                "filter_config": fc,
                "dedup_tracker": tracker,
            }

            # Determine collection mode based on flags
            page_url = getattr(args, "page_url", None)
            page_name = getattr(args, "page_name", None)

            if page_url:
                logger.info(f"Collecting ads from page URL: {page_url}")
                # Use collect_by_page_url with search params as kwargs
                page_kwargs = {
                    "country": args.country.upper(),
                    "ad_type": map_ad_type(args.ad_type),
                    "status": map_status(args.status),
                    "sort_by": map_sort(args.sort_by),
                    "max_results": args.max_results,
                    "page_size": args.page_size,
                    "filter_config": fc,
                    "dedup_tracker": tracker,
                }
                params = None  # signal to use page mode below
            elif page_name:
                logger.info(f"Resolving page name: {page_name!r}")
                page_kwargs = {
                    "country": args.country.upper(),
                    "ad_type": map_ad_type(args.ad_type),
                    "status": map_status(args.status),
                    "sort_by": map_sort(args.sort_by),
                    "max_results": args.max_results,
                    "page_size": args.page_size,
                    "filter_config": fc,
                    "dedup_tracker": tracker,
                }
                params = None  # signal to use page mode below
            else:
                logger.info(f"Starting collection: query='{args.query}', country={args.country}")

            # Resolve download-media / enrich flags
            download_media = getattr(args, "download_media", False) and not getattr(
                args, "no_download_media", False
            )
            enrich = getattr(args, "enrich", False) and not getattr(
                args, "no_enrich", False
            )
            media_dir = getattr(args, "media_dir", "./ad_media")

            # ── Media-download path ──────────────────────────────
            if download_media and params is not None:
                media_stats: dict[str, int] = {
                    "attempted": 0, "succeeded": 0, "failed": 0, "total_bytes": 0,
                }

                def _ads_with_media_iter():
                    """Wraps collect_with_media, yields ads for file writing and accumulates media stats."""
                    for ad, results in collector.collect_with_media(
                        media_output_dir=media_dir,
                        **params,
                    ):
                        if enrich:
                            ad = collector.enrich_ad(ad)
                        for r in results:
                            media_stats["attempted"] += 1
                            if r.success:
                                media_stats["succeeded"] += 1
                                media_stats["total_bytes"] += r.file_size or 0
                            else:
                                media_stats["failed"] += 1
                        yield ad

                count = _write_ads_to_file(
                    _ads_with_media_iter(), str(output_path), extension, args.include_raw,
                )

                logger.info("Media download summary:")
                logger.info(f"  Attempted:   {media_stats['attempted']}")
                logger.info(f"  Succeeded:   {media_stats['succeeded']}")
                logger.info(f"  Failed:      {media_stats['failed']}")
                logger.info(f"  Total bytes: {media_stats['total_bytes']:,}")

            # ── Standard (no media) path ─────────────────────────
            elif params is not None:
                if enrich:
                    # Wrap the search iterator to enrich each ad
                    def _enriched_iter():
                        for ad in collector.search(**params):
                            yield collector.enrich_ad(ad)

                    count = _write_ads_to_file(
                        _enriched_iter(), str(output_path), extension, args.include_raw,
                    )
                else:
                    # Standard search collection
                    if extension == ".json":
                        count = collector.collect_to_json(
                            output_path=str(output_path),
                            include_raw=args.include_raw,
                            **params,
                        )
                    elif extension == ".csv":
                        count = collector.collect_to_csv(
                            output_path=str(output_path),
                            **params,
                        )
                    else:  # .jsonl
                        count = collector.collect_to_jsonl(
                            output_path=str(output_path),
                            include_raw=args.include_raw,
                            **params,
                        )
            else:
                # Page-level collection (--page-url or --page-name)
                if page_url:
                    ads_iter = collector.collect_by_page_url(page_url, **page_kwargs)
                else:
                    ads_iter = collector.collect_by_page_name(page_name, **page_kwargs)

                if enrich:
                    ads_iter = (collector.enrich_ad(ad) for ad in ads_iter)

                count = _write_ads_to_file(ads_iter, str(output_path), extension, args.include_raw)

            # Print stats
            stats = collector.get_stats()
            logger.info("=" * 50)
            logger.info("Collection Complete!")
            logger.info(f"  Ads collected: {count}")
            logger.info(f"  Requests made: {stats['requests_made']}")
            logger.info(f"  Pages fetched: {stats['pages_fetched']}")
            logger.info(f"  Errors: {stats['errors']}")
            if stats.get("duration_seconds"):
                logger.info(f"  Duration: {stats['duration_seconds']:.2f}s")
            logger.info(f"  Output: {output_path}")
            logger.info("=" * 50)

            # Generate collection report if requested
            if getattr(args, "report", False) or getattr(args, "report_file", None):
                from .reporting import CollectionReport, format_report, format_report_json

                report = CollectionReport(
                    total_collected=count,
                    duplicates_skipped=0,
                    filtered_out=0,
                    errors=stats.get("errors", 0),
                    duration_seconds=stats.get("duration_seconds", 0.0),
                    start_time=stats.get("start_time"),
                    end_time=stats.get("end_time"),
                )

                if getattr(args, "report", False):
                    print(format_report(report))

                report_file = getattr(args, "report_file", None)
                if report_file:
                    report_path = Path(report_file)
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(
                        format_report_json(report), encoding="utf-8",
                    )
                    logger.info("Report saved to %s", report_file)

            return 0

    except KeyboardInterrupt:
        logger.info("\nCollection interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
