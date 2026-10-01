"""Private optional upstream proxy configuration for actual Meta CI traffic."""

import os
import uuid
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from meta_ads_collector.proxy_pool import parse_proxy


def validate_ci_proxy(proxy, required=False):
    if required and not proxy:
        raise ValueError("METAADS_CI_PROXY is required for live GitHub CI checks")
    return parse_proxy(proxy) if proxy else None


def configure_ci_network(patch, proxy):
    normalized = parse_proxy(proxy)
    parsed = urlsplit(normalized)
    # Apify rotates each connection unless a session is requested. Keep the
    # bootstrap cookies and GraphQL calls on one residential exit for this run.
    if parsed.hostname == "proxy.apify.com" and parsed.username:
        username = unquote(parsed.username)
        if not any(part.startswith("session-") for part in username.split(",")):
            run_id = os.environ.get("GITHUB_RUN_ID")
            attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
            # Validate the same exit in preflight and the full live job. Start
            # a separate fresh exit for the post-publication verification.
            stage = "published" if os.environ.get("GITHUB_JOB") == "verify-published" else "validate"
            session = (
                f"metaads{run_id}a{attempt}{stage}" if run_id and run_id.isdigit()
                else "metaads" + uuid.uuid4().hex
            )
            username += ",session-" + session
            authority = quote(username, safe="") + ":" + (parsed.password or "")
            authority += "@" + parsed.hostname + (f":{parsed.port}" if parsed.port else "")
            normalized = urlunsplit(parsed._replace(netloc=authority))
    patch.setenv("METAADS_CI_PROXY", normalized)
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        patch.setenv(name, normalized)
    bypass = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    bypass = ",".join(value for value in (bypass, "localhost", "127.0.0.1", "::1") if value)
    patch.setenv("NO_PROXY", bypass)
    patch.setenv("no_proxy", bypass)
