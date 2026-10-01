"""Configuration guards using ephemeral credentials, never personal secrets."""

import os

import pytest

from tests.ci_network import configure_ci_network, validate_ci_proxy


def test_ci_network_routes_http_and_https_but_keeps_local_receivers_local(monkeypatch):
    proxy = "http://audit-user:audit-password@127.0.0.1:8123"
    monkeypatch.setenv("NO_PROXY", "existing.example")
    configure_ci_network(monkeypatch, proxy)
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert os.environ[name] == proxy
    assert os.environ["NO_PROXY"] == os.environ["no_proxy"]
    assert {"existing.example", "localhost", "127.0.0.1", "::1"} <= set(os.environ["NO_PROXY"].split(","))


def test_ci_network_normalizes_legacy_proxy_credentials(monkeypatch):
    configure_ci_network(monkeypatch, "127.0.0.1:8123:audit@user:pass/with:colon")
    assert os.environ["https_proxy"] == "http://audit%40user:pass%2Fwith%3Acolon@127.0.0.1:8123"


def test_live_ci_cannot_silently_fall_back_to_direct_connections():
    with pytest.raises(ValueError, match="METAADS_CI_PROXY is required"):
        validate_ci_proxy(None, required=True)
    assert validate_ci_proxy(None, required=False) is None


def test_apify_ci_uses_one_session_for_bootstrap_and_queries(monkeypatch):
    from urllib.parse import unquote, urlsplit

    configure_ci_network(monkeypatch, "http://groups-RESIDENTIAL:ephemeral@proxy.apify.com:8000")
    pinned = os.environ["METAADS_CI_PROXY"]
    assert "session-metaads" in unquote(urlsplit(pinned).username)
    assert os.environ["https_proxy"] == pinned
    configure_ci_network(monkeypatch, pinned)
    assert os.environ["METAADS_CI_PROXY"] == pinned


def test_private_proxy_credentials_are_removed_from_uploaded_evidence(tmp_path):
    from scripts.check_distribution import private_proxy_values, redact_evidence

    proxy = "http://audit:ephemeral%2Fpassword@127.0.0.1:8123"
    evidence = tmp_path / "live.xml"
    evidence.write_text(f"<failure>{proxy} ephemeral/password ephemeral%2Fpassword</failure>", encoding="utf-8")
    redact_evidence(tmp_path, private_proxy_values(proxy))
    content = evidence.read_text(encoding="utf-8")
    assert "password" not in content
    assert "[REDACTED]" in content
