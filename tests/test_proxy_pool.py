"""Tests for meta_ads_collector.proxy_pool."""


import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.exceptions import ProxyError
from meta_ads_collector.proxy_pool import ProxyPool, parse_proxy

# ---------------------------------------------------------------------------
# parse_proxy
# ---------------------------------------------------------------------------

class TestParseProxy:
    """Tests for the parse_proxy helper."""

    def test_host_port(self):
        assert parse_proxy("1.2.3.4:8080") == "http://1.2.3.4:8080"

    def test_host_port_user_pass(self):
        assert parse_proxy("1.2.3.4:8080:user:pass") == "http://user:pass@1.2.3.4:8080"

    def test_http_url_format(self):
        assert parse_proxy("http://user:pass@host:3128") == "http://user:pass@host:3128"

    def test_socks5_url_format(self):
        assert parse_proxy("socks5://host:1080") == "socks5://host:1080"

    def test_whitespace_stripped(self):
        assert parse_proxy("  1.2.3.4:8080  ") == "http://1.2.3.4:8080"

    def test_empty_string_raises(self):
        with pytest.raises(ProxyError, match="Empty proxy"):
            parse_proxy("")

    def test_invalid_format_raises(self):
        with pytest.raises(ProxyError, match="Invalid proxy format"):
            parse_proxy("just_a_host")

    def test_three_part_raises(self):
        with pytest.raises(ProxyError, match="Invalid proxy format"):
            parse_proxy("1.2.3.4:8080:user")


# ---------------------------------------------------------------------------
# ProxyPool core
# ---------------------------------------------------------------------------

class TestProxyPoolRoundRobin:
    """Tests for round-robin proxy selection."""

    def test_cycles_through_proxies(self):
        pool = ProxyPool(["1.2.3.4:8080", "5.6.7.8:8080", "9.10.11.12:8080"])
        first = pool.get_next()
        second = pool.get_next()
        third = pool.get_next()
        fourth = pool.get_next()  # wraps around

        results = [first, second, third]
        # All three should be distinct
        assert len(set(results)) == 3
        # Fourth should be same as first
        assert fourth == first

    def test_single_proxy_always_same(self):
        pool = ProxyPool(["1.2.3.4:8080"])
        assert pool.get_next() == pool.get_next()

    def test_empty_list_raises(self):
        with pytest.raises(ProxyError, match="empty"):
            ProxyPool([])


# ---------------------------------------------------------------------------
# Failure tracking
# ---------------------------------------------------------------------------

class TestProxyPoolFailureTracking:
    """Tests for per-proxy failure counting and dead marking."""

    def test_failure_increments(self):
        pool = ProxyPool(["1.2.3.4:8080"], max_failures=3)
        proxy = pool.get_next()
        pool.mark_failure(proxy)
        assert pool._failures[proxy] == 1
        pool.mark_failure(proxy)
        assert pool._failures[proxy] == 2

    def test_dead_after_max_failures(self):
        pool = ProxyPool(["1.2.3.4:8080", "5.6.7.8:8080"], max_failures=2)
        first = "http://1.2.3.4:8080"
        pool.mark_failure(first)
        pool.mark_failure(first)
        # First proxy should be dead, only second returned
        alive = pool.alive_proxies
        assert first not in alive
        assert len(alive) == 1

    def test_success_resets_failure_count(self):
        pool = ProxyPool(["1.2.3.4:8080"], max_failures=3)
        proxy = pool.get_next()
        pool.mark_failure(proxy)
        pool.mark_failure(proxy)
        pool.mark_success(proxy)
        assert pool._failures[proxy] == 0

    def test_all_dead_raises(self):
        pool = ProxyPool(["1.2.3.4:8080"], max_failures=1, cooldown=9999.0)
        proxy = pool.get_next()
        pool.mark_failure(proxy)
        with pytest.raises(ProxyError, match="All proxies are dead"):
            pool.get_next()


# ---------------------------------------------------------------------------
# Dead proxy recovery
# ---------------------------------------------------------------------------

class TestProxyPoolRecovery:
    """Tests for dead proxy cooldown and reset."""

    def test_dead_proxy_recovers_after_cooldown(self):
        pool = ProxyPool(["1.2.3.4:8080"], max_failures=1, cooldown=0.0)
        proxy = pool.get_next()
        pool.mark_failure(proxy)
        # Cooldown is 0, so it should be alive again immediately
        assert proxy in pool.alive_proxies

    def test_dead_proxy_stays_dead_before_cooldown(self):
        pool = ProxyPool(["1.2.3.4:8080"], max_failures=1, cooldown=9999.0)
        proxy = pool.get_next()
        pool.mark_failure(proxy)
        assert proxy not in pool.alive_proxies

    def test_reset_revives_all(self):
        pool = ProxyPool(
            ["1.2.3.4:8080", "5.6.7.8:8080"],
            max_failures=1,
            cooldown=9999.0,
        )
        for proxy in pool._proxies:
            pool.mark_failure(proxy)
        # All dead
        with pytest.raises(ProxyError):
            pool.get_next()
        # Reset
        pool.reset()
        assert len(pool.alive_proxies) == 2
        # Should work now
        pool.get_next()

    def test_mark_success_revives_dead_proxy(self):
        pool = ProxyPool(["1.2.3.4:8080"], max_failures=1, cooldown=9999.0)
        proxy = pool.get_next()
        pool.mark_failure(proxy)
        assert proxy not in pool.alive_proxies
        pool.mark_success(proxy)
        assert proxy in pool.alive_proxies


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

class TestProxyPoolFromFile:
    """Tests for ProxyPool.from_file."""

    def test_loads_proxies(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("1.2.3.4:8080\n5.6.7.8:9090\n")
        pool = ProxyPool.from_file(str(proxy_file))
        assert len(pool) == 2

    def test_skips_blank_lines(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("1.2.3.4:8080\n\n  \n5.6.7.8:9090\n")
        pool = ProxyPool.from_file(str(proxy_file))
        assert len(pool) == 2

    def test_skips_comments(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text(
            "# This is a comment\n"
            "1.2.3.4:8080\n"
            "# Another comment\n"
            "5.6.7.8:9090\n"
        )
        pool = ProxyPool.from_file(str(proxy_file))
        assert len(pool) == 2

    def test_empty_file_raises(self, tmp_path):
        proxy_file = tmp_path / "empty.txt"
        proxy_file.write_text("# only comments\n\n")
        with pytest.raises(ProxyError, match="No proxies found"):
            ProxyPool.from_file(str(proxy_file))

    def test_all_formats_in_file(self, tmp_path):
        proxy_file = tmp_path / "mixed.txt"
        proxy_file.write_text(
            "1.2.3.4:8080\n"
            "5.6.7.8:9090:user:pass\n"
            "http://host:3128\n"
            "socks5://host2:1080\n"
        )
        pool = ProxyPool.from_file(str(proxy_file))
        assert len(pool) == 4
        proxies = pool._proxies
        assert "http://1.2.3.4:8080" in proxies
        assert "http://user:pass@5.6.7.8:9090" in proxies
        assert "http://host:3128" in proxies
        assert "socks5://host2:1080" in proxies


# ---------------------------------------------------------------------------
# Client integration
# ---------------------------------------------------------------------------

class TestClientProxyIntegration:
    """Tests for proxy pool integration with MetaAdsClient."""

    def test_none_proxy_no_pool(self):
        client = MetaAdsClient(proxy=None)
        assert client._proxy_pool is None
        assert client._proxy_string is None
        client.close()

    def test_single_string_proxy_backward_compat(self):
        client = MetaAdsClient(proxy="1.2.3.4:8080")
        assert client._proxy_pool is None
        assert client._proxy_string == "1.2.3.4:8080"
        assert client.session.proxies["http"] == "http://1.2.3.4:8080"
        client.close()

    def test_list_creates_pool(self):
        client = MetaAdsClient(proxy=["1.2.3.4:8080", "5.6.7.8:9090"])
        assert client._proxy_pool is not None
        assert len(client._proxy_pool) == 2
        assert client._proxy_string is None
        client.close()

    def test_pool_instance_accepted(self):
        pool = ProxyPool(["1.2.3.4:8080", "5.6.7.8:9090"])
        client = MetaAdsClient(proxy=pool)
        assert client._proxy_pool is pool
        assert client._proxy_string is None
        client.close()


# ---------------------------------------------------------------------------
# Utility methods
# ---------------------------------------------------------------------------

class TestProxyPoolUtils:
    """Tests for utility methods."""

    def test_len(self):
        pool = ProxyPool(["a:1", "b:2", "c:3"])
        assert len(pool) == 3

    def test_repr(self):
        pool = ProxyPool(["a:1", "b:2"])
        r = repr(pool)
        assert "total=2" in r
        assert "alive=2" in r

    def test_get_requests_proxies(self):
        pool = ProxyPool(["1.2.3.4:8080"])
        d = pool.get_requests_proxies("http://1.2.3.4:8080")
        assert d == {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
