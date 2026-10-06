"""Allowlisted metadata from real Meta responses; never cookies, tokens or bodies."""

from __future__ import annotations

import inspect
import json
from urllib.parse import urlsplit


def response_metadata(client, method, url, response):
    """Do not serialize server messages, URLs, request arguments or credentials."""
    parsed = urlsplit(url)
    if parsed.hostname not in {"www.facebook.com", "web.facebook.com"}:
        return None
    codes = []
    if parsed.path == "/api/graphql/":
        try:
            text = response.text
            payload = json.loads(text[9:] if text.startswith("for (;;);") else text)
            if isinstance(payload, dict):
                for error in payload.get("errors", []) or []:
                    if isinstance(error, dict) and type(error.get("code")) is int:
                        codes.append(error["code"])
        except (ValueError, TypeError):
            pass
    return {
        "method": "POST" if method.upper() == "POST" else "GET",
        "endpoint": "graphql" if parsed.path == "/api/graphql/" else "bootstrap",
        "host": parsed.hostname,
        "status": int(response.status_code),
        "error_codes": codes,
        "lsd_present": bool(getattr(client, "_tokens", {}).get("lsd")),
    }


class MetaTransportDiagnostics:
    """Observe the existing request method without changing any network behavior."""

    def __init__(self):
        self.responses = []

    def instrument(self, patch, client):
        request = client._make_request

        def record(method, url, response):
            entry = response_metadata(client, method, url, response)
            if entry is not None and len(self.responses) < 100:
                self.responses.append(entry)

        if inspect.iscoroutinefunction(request):
            async def async_request(method, url, **kwargs):
                response = await request(method, url, **kwargs)
                record(method, url, response)
                return response
            patch.setattr(client, "_make_request", async_request)
        else:
            def sync_request(method, url, **kwargs):
                response = request(method, url, **kwargs)
                record(method, url, response)
                return response
            patch.setattr(client, "_make_request", sync_request)

    def snapshot(self, destinations):
        return {"responses": list(self.responses), "meta_destinations": sorted(set(destinations))}
