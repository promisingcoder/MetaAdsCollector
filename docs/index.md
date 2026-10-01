# MetaAdsCollector

MetaAdsCollector is a Python package and command-line tool for searching the Meta Ad Library. It does not require a Meta API key because it uses internal Meta endpoints rather than Meta's official Ad Library API.

!!! warning "Unofficial endpoints can change"
    Meta may change, challenge, restrict, or block requests to its internal endpoints. Searches can fail or return incomplete results. This project is not affiliated with or endorsed by Meta.

## Start here

- **New to programming?** Follow the [beginner's quick start](quickstart.md) to install the package and save results as a CSV file.
- **Using a command line?** See the [CLI reference](cli.md) for search options and output formats.
- **Writing Python?** Start with the quick start, then use the [Python API reference](api-reference.md).

## Guides

- [Filtering](filtering.md) — refine results with client-side filters.
- [Deduplication](deduplication.md) — skip ad IDs already recorded by a tracker.
- [Media downloads](media.md) — download media URLs returned with ads.
- [Events and webhooks](events.md) — handle collection events and optionally POST data to a webhook.
- [Async usage](async.md) — use the asynchronous collector.
- [Proxy configuration](proxy.md) — configure a proxy or proxy pool.
- [Architecture](architecture.md) — an overview of the package components.
- [Contributing](contributing.md) — set up a development environment and run checks.

## Project links

- [Source code](https://github.com/promisingcoder/MetaAdsCollector)
- [PyPI package](https://pypi.org/project/meta-ads-collector/)
- [Issue tracker](https://github.com/promisingcoder/MetaAdsCollector/issues)
