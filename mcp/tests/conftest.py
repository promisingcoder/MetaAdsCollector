"""Offline infrastructure checks and explicitly enabled actual-Meta checks."""

from __future__ import annotations

import os

import pytest
from meta_ads_collector_mcp.schemas import Search
from meta_ads_collector_mcp.service import Service

from meta_ads_collector import Ad


def pytest_addoption(parser):
    parser.addoption(
        "--run-mcp-live",
        action="store_true",
        default=False,
        help="Verify MCP operations against the actual Meta Ad Library",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-mcp-live", default=False):
        return
    for item in items:
        if "mcp_live" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="Enable actual Meta checks with --run-mcp-live"))


@pytest.fixture(scope="session", autouse=True)
def mcp_network(request):
    if request.config.getoption("--run-mcp-live", default=False):
        from tests.ci_network import configure_ci_network, validate_ci_proxy

        proxy = validate_ci_proxy(
            os.environ.get("METAADS_CI_PROXY"), required=os.environ.get("GITHUB_ACTIONS") == "true"
        )
        with pytest.MonkeyPatch.context() as patch:
            if proxy:
                configure_ci_network(patch, proxy)
            yield
    else:
        yield


@pytest.fixture
def service(tmp_path):
    instance = Service(tmp_path)
    yield instance
    instance.close()


@pytest.fixture
def real_records():
    # Public records previously captured from Meta; no fabricated advertisers or dummy media URLs.
    from tests.audit_meta_samples import CAPTURED_ADS
    from tests.meta_full_sample import FULL_META_AD

    return [Ad.from_graphql_response(raw).to_dict() for raw in [FULL_META_AD, *CAPTURED_ADS[1:4]]]


@pytest.fixture
def stored(service, real_records):
    job_id = service.store.create_job(service.freeze(Search(query="nike")))
    assert service.store.claim(job_id, service.owner)
    for record in real_records:
        service.store.save_ad(job_id, service.owner, record)
    service.store.release(job_id, service.owner, "COMPLETED")
    return job_id
