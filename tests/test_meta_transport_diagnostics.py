"""Privacy and transparency contracts for metadata, separate from live collection."""

import json
from types import SimpleNamespace

import pytest

from tests.meta_transport_diagnostics import MetaTransportDiagnostics, response_metadata


@pytest.mark.parametrize("prefix", ["", "for (;;);"])
def test_response_metadata_never_serializes_tokens_cookies_messages_or_url_query(prefix):
    sensitive = "ephemeral-private-canary"
    client = SimpleNamespace(_tokens={"lsd": sensitive})
    # Exercise the observed Meta GraphQL error shape with a deliberate canary
    # in fields that must never enter public evidence. This is a privacy unit
    # contract, not a substitute for the actual Meta SOCKS integration cases.
    body = {"errors": [{"code": 1675004, "message": sensitive}, {"code": sensitive}], "token": sensitive}
    response = SimpleNamespace(status_code=200, text=prefix + json.dumps(body), cookies={"datr": sensitive})
    evidence = response_metadata(client, "POST", "https://www.facebook.com/api/graphql/?token=" + sensitive, response)
    assert evidence == {
        "method": "POST", "endpoint": "graphql", "host": "www.facebook.com",
        "status": 200, "error_codes": [1675004], "lsd_present": True,
    }
    assert sensitive not in json.dumps(evidence)


@pytest.mark.parametrize("body", ["not JSON", "[]", "null", '{"errors": true}'])
def test_unstructured_response_does_not_leak_body_or_break_the_observer(body):
    evidence = response_metadata(SimpleNamespace(_tokens={}), "POST", "https://www.facebook.com/api/graphql/",
                                 SimpleNamespace(status_code=403, text=body))
    assert evidence["status"] == 403 and evidence["error_codes"] == [] and not evidence["lsd_present"]


@pytest.mark.parametrize("async_mode", [False, True])
def test_instrumentation_preserves_response_identity_and_request_arguments(monkeypatch, async_mode):
    import asyncio

    response = SimpleNamespace(status_code=200, text="")
    arguments = []

    def request(method, url, **kwargs):
        arguments.append((method, url, kwargs))
        return response

    async def async_request(method, url, **kwargs):
        return request(method, url, **kwargs)

    client = SimpleNamespace(_make_request=async_request if async_mode else request, _tokens={})
    diagnostics = MetaTransportDiagnostics()
    diagnostics.instrument(monkeypatch, client)
    call = client._make_request("GET", "https://www.facebook.com/", headers={"accept": "text/html"})
    result = asyncio.run(call) if async_mode else call
    assert result is response
    assert arguments == [("GET", "https://www.facebook.com/", {"headers": {"accept": "text/html"}})]
    assert diagnostics.snapshot(["www.facebook.com"])["responses"][0]["status"] == 200
