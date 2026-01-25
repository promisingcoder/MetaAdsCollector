#!/usr/bin/env python3
"""
Example usage of the Meta Ads Collector

This script demonstrates various ways to use the collector.
"""

import logging
from meta_ads_collector import MetaAdsCollector, Ad

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Your proxy configuration
PROXY = "REDACTED_PROXY_CREDENTIALS"


def example_basic_search():
    """Basic search example - collect ads and print them."""
    print("\n=== Basic Search Example ===\n")

    with MetaAdsCollector(proxy=PROXY) as collector:
        # Search for real estate ads in the US
        for ad in collector.search(
            query="real estate",
            country="US",
            ad_type=MetaAdsCollector.AD_TYPE_HOUSING,
            max_results=5,  # Limit for demo
        ):
            print(f"Ad ID: {ad.id}")
            print(f"  Page: {ad.page.name if ad.page else 'N/A'}")
            print(f"  Active: {ad.is_active}")
            if ad.creatives:
                print(f"  Body: {ad.creatives[0].body[:100] if ad.creatives[0].body else 'N/A'}...")
            print(f"  Impressions: {ad.impressions}")
            print(f"  Spend: {ad.spend}")
            print("-" * 50)


def example_political_ads():
    """Collect political ads example."""
    print("\n=== Political Ads Example ===\n")

    with MetaAdsCollector(proxy=PROXY) as collector:
        # Collect political ads from Egypt, sorted by impressions
        count = collector.collect_to_json(
            output_path="output/political_ads_eg.json",
            country="EG",
            ad_type=MetaAdsCollector.AD_TYPE_POLITICAL,
            sort_by=MetaAdsCollector.SORT_IMPRESSIONS,
            max_results=20,
        )
        print(f"Collected {count} political ads from Egypt")


def example_export_csv():
    """Export to CSV example."""
    print("\n=== CSV Export Example ===\n")

    with MetaAdsCollector(proxy=PROXY) as collector:
        count = collector.collect_to_csv(
            output_path="output/housing_ads.csv",
            query="apartment",
            country="US",
            ad_type=MetaAdsCollector.AD_TYPE_HOUSING,
            status=MetaAdsCollector.STATUS_ACTIVE,
            max_results=50,
        )
        print(f"Exported {count} ads to CSV")


def example_exact_phrase_search():
    """Exact phrase search example."""
    print("\n=== Exact Phrase Search Example ===\n")

    with MetaAdsCollector(proxy=PROXY) as collector:
        ads = collector.collect(
            query='"buy now"',  # Exact phrase
            country="US",
            search_type=MetaAdsCollector.SEARCH_EXACT,
            max_results=10,
        )

        print(f"Found {len(ads)} ads with exact phrase 'buy now'")
        for ad in ads:
            print(f"  - {ad.page.name if ad.page else 'Unknown'}: {ad.id}")


def example_page_specific():
    """Collect ads from specific pages."""
    print("\n=== Page-Specific Collection Example ===\n")

    with MetaAdsCollector(proxy=PROXY) as collector:
        # Replace with actual page IDs you want to monitor
        page_ids = ["123456789", "987654321"]

        count = collector.collect_to_jsonl(
            output_path="output/specific_pages.jsonl",
            page_ids=page_ids,
            max_results=100,
        )
        print(f"Collected {count} ads from specified pages")


def example_with_progress():
    """Collection with progress callback."""
    print("\n=== Progress Tracking Example ===\n")

    def progress_callback(collected: int, total: int):
        if total > 0:
            pct = (collected / total) * 100
            print(f"\rProgress: {collected}/{total} ({pct:.1f}%)", end="", flush=True)
        else:
            print(f"\rCollected: {collected}", end="", flush=True)

    with MetaAdsCollector(proxy=PROXY) as collector:
        ads = []
        for ad in collector.search(
            query="insurance",
            country="US",
            max_results=25,
            progress_callback=progress_callback,
        ):
            ads.append(ad)

        print(f"\n\nCollected {len(ads)} insurance ads")


def example_analyze_collected():
    """Analyze collected ads."""
    print("\n=== Analysis Example ===\n")

    with MetaAdsCollector(proxy=PROXY) as collector:
        ads = collector.collect(
            query="software",
            country="US",
            max_results=30,
        )

        # Analyze by publisher platform
        platforms = {}
        for ad in ads:
            for platform in ad.publisher_platforms:
                platforms[platform] = platforms.get(platform, 0) + 1

        print("Ads by platform:")
        for platform, count in sorted(platforms.items(), key=lambda x: -x[1]):
            print(f"  {platform}: {count}")

        # Find highest impression ads
        ads_with_impressions = [a for a in ads if a.impressions and a.impressions.lower_bound]
        if ads_with_impressions:
            top_ad = max(ads_with_impressions, key=lambda x: x.impressions.lower_bound)
            print(f"\nHighest impressions: {top_ad.impressions}")
            print(f"  From: {top_ad.page.name if top_ad.page else 'Unknown'}")


if __name__ == "__main__":
    # Run examples (uncomment the ones you want to try)

    example_basic_search()
    # example_political_ads()
    # example_export_csv()
    # example_exact_phrase_search()
    # example_page_specific()
    # example_with_progress()
    # example_analyze_collected()
