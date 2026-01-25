#!/usr/bin/env python3
"""
Meta Ads Library Collector - Main Entry Point

Usage:
    python main.py --query "real estate" --country US --max-results 100 --output ads.json
    python main.py --query "climate" --ad-type political --output political_ads.csv
"""

import argparse
import logging
import sys
from pathlib import Path

from meta_ads_collector import MetaAdsCollector


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Collect ads from the Meta Ad Library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for real estate ads in the US
  python main.py --query "real estate" --country US --output ads.json

  # Collect political ads from Egypt
  python main.py --country EG --ad-type political --output egypt_political.json

  # Export to CSV with a limit
  python main.py --query "loans" --max-results 500 --output loans.csv

  # Use exact phrase matching
  python main.py --query "buy now" --search-type exact --output buy_now.json
        """,
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
        required=True,
        help="Output file path (.json, .csv, or .jsonl)",
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

    # Connection options
    parser.add_argument(
        "--proxy",
        default="REDACTED_PROXY_CREDENTIALS",
        help="Proxy in format host:port:user:pass (default: configured proxy)",
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
        "relevancy": MetaAdsCollector.SORT_RELEVANCY,  # None = server default
        "impressions": MetaAdsCollector.SORT_IMPRESSIONS,
    }
    return mapping.get(sort_by, MetaAdsCollector.SORT_IMPRESSIONS)


def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    # Determine output format from file extension
    output_path = Path(args.output)
    extension = output_path.suffix.lower()

    if extension not in [".json", ".csv", ".jsonl"]:
        logger.error(f"Unsupported output format: {extension}")
        logger.error("Supported formats: .json, .csv, .jsonl")
        return 1

    # Configure proxy
    proxy = None if args.no_proxy else args.proxy

    # Create collector
    logger.info("Initializing Meta Ads Collector...")

    try:
        with MetaAdsCollector(
            proxy=proxy,
            rate_limit_delay=args.delay,
            timeout=args.timeout,
        ) as collector:

            # Common parameters
            params = {
                "query": args.query,
                "country": args.country.upper(),
                "ad_type": map_ad_type(args.ad_type),
                "status": map_status(args.status),
                "search_type": map_search_type(args.search_type),
                "sort_by": map_sort(args.sort_by),
                "page_ids": args.page_ids,
                "max_results": args.max_results,
                "page_size": args.page_size,
            }

            logger.info(f"Starting collection: query='{args.query}', country={args.country}")

            # Collect based on output format
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
