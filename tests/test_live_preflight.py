"""A bounded real Meta bootstrap/search check before the full CI workload."""

import pytest

from meta_ads_collector.client import MetaAdsClient
from meta_ads_collector.models import Ad


@pytest.mark.integration
def test_live_meta_bootstrap_search_and_field_fidelity():
    with MetaAdsClient(timeout=20, max_retries=1) as client:
        client.initialize()
        response, _cursor = client.search_ads(query="nike", country="US", first=2)
    assert not response.get("error"), response.get("error")
    assert not response.get("rate_limited")
    assert not response.get("session_expired")
    assert response.get("ads"), "Meta preflight returned no ads for the broad query"
    for raw in response["ads"]:
        ad = Ad.from_graphql_response(raw)
        assert ad.id and ad.page and ad.page.id
        assert ad.to_dict()["api_fields"] == raw
