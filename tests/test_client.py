"""Tests for meta_ads_collector.client (unit tests, no network)."""

import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.exceptions import ProxyError


class TestProxyParsing:
    def test_host_port_user_pass(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        client.session = __import__("requests").Session()
        client._setup_proxy("1.2.3.4:8080:user:pass")
        assert client.session.proxies["http"] == "http://user:pass@1.2.3.4:8080"
        assert client.session.proxies["https"] == "http://user:pass@1.2.3.4:8080"
        client.session.close()

    def test_host_port_only(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        client.session = __import__("requests").Session()
        client._setup_proxy("1.2.3.4:8080")
        assert client.session.proxies["http"] == "http://1.2.3.4:8080"
        client.session.close()

    def test_invalid_format_raises(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        client.session = __import__("requests").Session()
        with pytest.raises(ProxyError, match="Invalid proxy format"):
            client._setup_proxy("invalid")
        client.session.close()

    def test_none_proxy_is_noop(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        client.session = __import__("requests").Session()
        client._setup_proxy(None)
        assert not client.session.proxies
        client.session.close()


class TestTokenExtraction:
    def _client(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        return client

    def test_extract_lsd(self):
        client = self._client()
        html = '"LSD",[],{"token":"abc123xyz"}'
        tokens = client._extract_tokens(html)
        assert tokens["lsd"] == "abc123xyz"

    def test_extract_lsd_alt_pattern(self):
        client = self._client()
        html = 'name="lsd" value="lsd_alt_value"'
        tokens = client._extract_tokens(html)
        assert tokens["lsd"] == "lsd_alt_value"

    def test_extract_rev(self):
        client = self._client()
        html = '"__spin_r":1234567'
        tokens = client._extract_tokens(html)
        assert tokens["__rev"] == "1234567"
        assert tokens["__spin_r"] == "1234567"

    def test_extract_spin_t(self):
        client = self._client()
        html = '"__spin_t":1700000000'
        tokens = client._extract_tokens(html)
        assert tokens["__spin_t"] == "1700000000"

    def test_extract_spin_b(self):
        client = self._client()
        html = '"__spin_b":"trunk"'
        tokens = client._extract_tokens(html)
        assert tokens["__spin_b"] == "trunk"

    def test_extract_hsi(self):
        client = self._client()
        html = '"hsi":"9999999"'
        tokens = client._extract_tokens(html)
        assert tokens["__hsi"] == "9999999"

    def test_extract_dyn_csr(self):
        client = self._client()
        html = '"__dyn":"dyn_value","__csr":"csr_value"'
        tokens = client._extract_tokens(html)
        assert tokens["__dyn"] == "dyn_value"
        assert tokens["__csr"] == "csr_value"

    def test_empty_html_returns_empty(self):
        client = self._client()
        tokens = client._extract_tokens("")
        assert tokens == {}


class TestJazoest:
    def test_calculate_jazoest(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        result = client._calculate_jazoest("abc")
        # 2 + ord('a') + ord('b') + ord('c') = 2 + 97 + 98 + 99 = 296
        assert result == "296"

    def test_calculate_jazoest_empty(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        result = client._calculate_jazoest("")
        assert result == "2893"


class TestRequestIdEncoding:
    def test_single_digit(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        assert client._encode_request_id(5) == "5"

    def test_base36(self):
        client = MetaAdsClient.__new__(MetaAdsClient)
        assert client._encode_request_id(36) == "10"
        assert client._encode_request_id(10) == "a"
