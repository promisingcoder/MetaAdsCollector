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


def test_preflight_and_live_ci_share_an_exit_but_published_check_uses_a_fresh_one(monkeypatch):
    proxy = "http://groups-RESIDENTIAL:ephemeral@proxy.apify.com:8000"
    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_JOB", "live-connectivity")
    configure_ci_network(monkeypatch, proxy)
    preflight = os.environ["METAADS_CI_PROXY"]
    monkeypatch.setenv("GITHUB_JOB", "live-meta")
    configure_ci_network(monkeypatch, proxy)
    assert os.environ["METAADS_CI_PROXY"] == preflight
    monkeypatch.setenv("GITHUB_JOB", "verify-published")
    configure_ci_network(monkeypatch, proxy)
    assert os.environ["METAADS_CI_PROXY"] != preflight
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_JOB", "live-meta")
    configure_ci_network(monkeypatch, proxy)
    assert os.environ["METAADS_CI_PROXY"] != preflight


def test_private_proxy_credentials_are_removed_from_uploaded_evidence(tmp_path):
    from scripts.check_distribution import private_proxy_values, redact_evidence

    proxy = "http://audit:ephemeral%2Fpassword@127.0.0.1:8123"
    evidence = tmp_path / "live.xml"
    evidence.write_text(f"<failure>{proxy} ephemeral/password ephemeral%2Fpassword</failure>", encoding="utf-8")
    redact_evidence(tmp_path, private_proxy_values(proxy))
    content = evidence.read_text(encoding="utf-8")
    assert "password" not in content
    assert "[REDACTED]" in content


def test_distribution_checks_do_not_filter_out_integration_regressions():
    import inspect

    from scripts.check_distribution import main

    # Captured-data fault injection is labeled separately in the report, but
    # must still be exercised alongside every other permanent regression.
    assert '"not controlled"' not in inspect.getsource(main)


def test_scoped_proxy_matches_dns_cases_but_separates_families(monkeypatch):
    from urllib.parse import unquote, urlsplit

    from tests.ci_network import scoped_ci_proxy

    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    configure_ci_network(monkeypatch, "http://groups-RESIDENTIAL,country-US:ephemeral@proxy.apify.com:8000")
    shared = os.environ["METAADS_CI_PROXY"]
    first = scoped_ci_proxy(shared, "authenticated_socks")
    assert first == scoped_ci_proxy(shared, "authenticated_socks")
    assert first != scoped_ci_proxy(shared, "independent_dns")
    assert first != shared
    parsed = urlsplit(first)
    parameters = unquote(parsed.username).split(",")
    assert "groups-RESIDENTIAL" in parameters and "country-US" in parameters
    sessions = [item.removeprefix("session-") for item in parameters if item.startswith("session-")]
    assert len(sessions) == 1 and len(sessions[0]) <= 50
    assert parsed.password == "ephemeral" and parsed.hostname == "proxy.apify.com" and parsed.port == 8000


@pytest.mark.parametrize("proxy", [
    None,
    "http://audit:ephemeral@127.0.0.1:8123",
    "http://groups-RESIDENTIAL,session-userchosen:ephemeral@proxy.apify.com:8000",
])
def test_scoped_proxy_preserves_user_selected_session_and_other_providers(proxy):
    from tests.ci_network import scoped_ci_proxy

    assert scoped_ci_proxy(proxy, "authenticated_socks") == proxy
