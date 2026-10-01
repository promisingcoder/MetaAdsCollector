"""Actual Meta requests over local HTTP CONNECT proxies, including rotation."""

from __future__ import annotations

import secrets
from urllib.parse import quote

import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.collector import MetaAdsCollector

from .meta_forward_proxy import MetaForwardProxy, MetaSocksProxy


def _proxy_string(proxy, form):
    if form == "legacy":
        return f"{proxy.host_port}:{proxy.username}:{proxy.password}"
    return f"http://{quote(proxy.username, safe='')}:{quote(proxy.password, safe='')}@{proxy.host_port}"


@pytest.mark.parametrize("form", ["legacy", "url"])
def test_sync_proxy_constructor_preserves_normalized_proxy_without_logging_failure(form):
    """Guard the sync setup path, including its status log after normalization."""
    proxy = "127.0.0.1:8080" if form == "legacy" else "http://127.0.0.1:8080"
    with MetaAdsClient(proxy=proxy) as client:
        assert client.session.proxies["https"] == "http://127.0.0.1:8080"


@pytest.mark.integration
@pytest.mark.parametrize("form", ["legacy", "url"])
def test_live_sync_authenticated_proxy_collects_actual_meta_ads(form):
    with MetaForwardProxy("audit@meta", "local/" + secrets.token_hex(12)) as proxy:
        with MetaAdsCollector(proxy=_proxy_string(proxy, form), timeout=30, max_retries=2,
                              rate_limit_delay=0.5, jitter=0) as collector:
            ads = list(collector.search(query="nike", country="US", max_results=3, page_size=2))
        assert len(ads) == 3
        assert all(ad.id and ad.page and ad.page.id for ad in ads)
        assert proxy.connections, "No actual Meta tunnel was used"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["legacy", "url"])
async def test_live_async_authenticated_proxy_collects_actual_meta_ads(form):
    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    with MetaForwardProxy("audit@meta", "local/" + secrets.token_hex(12)) as proxy:
        async with AsyncMetaAdsCollector(proxy=_proxy_string(proxy, form), timeout=30, max_retries=2,
                                         rate_limit_delay=0.5, jitter=0) as collector:
            ads = await collector.collect(query="nike", country="US", max_results=3, page_size=2)
        assert len(ads) == 3
        assert all(ad.id and ad.page and ad.page.id for ad in ads)
        assert proxy.connections

@pytest.mark.integration
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_live_proxy_pool_routes_actual_meta_requests_through_both_proxies(async_mode):
    import asyncio

    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    with MetaForwardProxy() as first, MetaForwardProxy() as second:
        proxies = [f"http://{first.host_port}", f"http://{second.host_port}"]
        if async_mode:
            async def collect():
                async with AsyncMetaAdsCollector(proxy=proxies, timeout=30, max_retries=2,
                                                 rate_limit_delay=0.5, jitter=0) as collector:
                    return await collector.collect(query="nike", country="US", max_results=3, page_size=2)
            ads = asyncio.run(collect())
        else:
            with MetaAdsCollector(proxy=proxies, timeout=30, max_retries=2,
                                  rate_limit_delay=0.5, jitter=0) as collector:
                ads = list(collector.search(query="nike", country="US", max_results=3, page_size=2))
        assert len(ads) == 3
        assert first.connections and second.connections, "Pool did not rotate both actual Meta tunnels"


@pytest.mark.integration
@pytest.mark.parametrize("scheme", ["socks5", "socks5h"])
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
def test_live_authenticated_socks_proxy_collects_actual_meta_ads(scheme, async_mode):
    import asyncio

    from meta_ads_collector.async_collector import AsyncMetaAdsCollector

    with MetaSocksProxy("audit@meta", "local/" + secrets.token_hex(12)) as proxy:
        address = _proxy_string(proxy, "url").replace("http://", scheme + "://", 1)
        if async_mode:
            async def collect():
                async with AsyncMetaAdsCollector(proxy=address, timeout=30, max_retries=2,
                                                 rate_limit_delay=0.5, jitter=0) as collector:
                    return await collector.collect(query="nike", country="US", max_results=3, page_size=2)
            ads = asyncio.run(collect())
        else:
            with MetaAdsCollector(proxy=address, timeout=30, max_retries=2,
                                  rate_limit_delay=0.5, jitter=0) as collector:
                ads = list(collector.search(query="nike", country="US", max_results=3, page_size=2))
        assert len(ads) == 3
        assert all(ad.id and ad.page and ad.page.id for ad in ads)
        assert proxy.connections

        # Verify both SOCKS DNS modes using addresses from the actual Meta DNS.
        if scheme == "socks5":
            assert all(host in proxy.meta_addresses for host in proxy.connections)
        else:
            assert "www.facebook.com" in proxy.connections


@pytest.mark.integration
def test_live_proxy_transfers_actual_meta_media(collected_ads, tmp_path):
    from meta_ads_collector.models import Ad, AdCreative

    source = next(ad for ad in collected_ads if any(c.thumbnail_url or c.image_url for c in ad.creatives))
    url = next(c.thumbnail_url or c.image_url for c in source.creatives if c.thumbnail_url or c.image_url)
    with MetaForwardProxy() as proxy:
        with MetaAdsCollector(proxy=f"http://{proxy.host_port}", timeout=30, max_retries=2) as collector:
            results = collector.download_ad_media(Ad(id=source.id, creatives=[AdCreative(image_url=url)]), tmp_path)
        assert len(results) == 1 and results[0].success, results
        assert results[0].file_size > 0
        assert any(host.endswith(".fbcdn.net") for host in proxy.connections)


@pytest.mark.integration
@pytest.mark.parametrize("scheme", ["http", "socks5h"])
def test_live_local_proxy_chains_through_authenticated_upstream_to_actual_meta(scheme, monkeypatch):
    """Exercise the same extra upstream leg used by privately configured CI."""
    upstream_type = MetaForwardProxy if scheme == "http" else MetaSocksProxy
    with upstream_type("audit@meta", "local/" + secrets.token_hex(12)) as upstream:
        address = _proxy_string(upstream, "url").replace("http://", scheme + "://", 1)
        monkeypatch.setenv("METAADS_CI_PROXY", address)
        with MetaForwardProxy() as inner:
            with MetaAdsCollector(proxy=f"http://{inner.host_port}", timeout=30, max_retries=2,
                                  rate_limit_delay=0.5, jitter=0) as collector:
                ads = list(collector.search(query="nike", country="US", max_results=3, page_size=2))
            assert len(ads) == 3
            assert inner.connections and upstream.connections
            assert all(ad.id and ad.page and ad.page.id for ad in ads)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["sync", "async", "cli"])
def test_live_default_clients_and_cli_use_configured_ci_proxy(mode, monkeypatch, tmp_path):
    import asyncio
    import json
    import subprocess
    import sys

    from meta_ads_collector.async_collector import AsyncMetaAdsCollector
    from tests.ci_network import configure_ci_network

    with MetaForwardProxy() as proxy:
        configure_ci_network(monkeypatch, f"http://{proxy.host_port}")
        if mode == "async":
            async def collect():
                async with AsyncMetaAdsCollector(timeout=30, max_retries=2) as collector:
                    return await collector.collect(query="nike", country="US", max_results=2)
            ads = asyncio.run(collect())
        elif mode == "cli":
            path = tmp_path / "ci-proxy-ads.json"
            completed = subprocess.run(
                [sys.executable, "-m", "meta_ads_collector", "-q", "nike", "-n", "2", "-o", str(path)],
                capture_output=True, text=True, timeout=120, check=False,
            )
            assert completed.returncode == 0, "Actual Meta CLI proxy request failed"
            ads = json.loads(path.read_text(encoding="utf-8"))["ads"]
        else:
            with MetaAdsCollector(timeout=30, max_retries=2) as collector:
                ads = list(collector.search(query="nike", country="US", max_results=2))
        assert len(ads) == 2
        assert proxy.connections, "Default transport bypassed the configured CI proxy"
