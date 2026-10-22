"""Regression contracts for the actual branch, release and private live CI configuration."""

import os
import re
import tarfile
from pathlib import Path

import yaml


def repository_text(relative):
    sdist = os.environ.get("METAADS_AUDIT_SDIST")
    if sdist:
        with tarfile.open(sdist) as archive:
            member, = [member for member in archive.getmembers() if member.name.endswith("/" + relative)]
            return archive.extractfile(member).read().decode("utf-8")
    return (Path(__file__).resolve().parents[1] / relative).read_text(encoding="utf-8")


def script_namespace(relative):
    namespace = {"__name__": "check_distribution_under_test"}
    exec(compile(repository_text(relative), relative, "exec"), namespace)
    return namespace


def workflow(name):
    relative = f".github/workflows/{name}.yml"
    content = repository_text(relative)
    # BaseLoader preserves the GitHub event key 'on', which YAML 1.1 otherwise
    # interprets as a boolean. These contracts intentionally compare scalar strings.
    return yaml.load(content, Loader=yaml.BaseLoader)


def test_every_branch_push_runs_ci_but_tag_push_does_not_duplicate_release_ci():
    events = workflow("ci")["on"]
    assert events["push"] == {"branches": ["**"]}
    assert "pull_request" in events
    assert "workflow_dispatch" in events
    assert "workflow_call" in events


def test_published_releases_keep_full_validation_and_private_proxy_forwarding():
    publishing = workflow("publish")
    assert publishing["on"]["release"]["types"] == ["published"]
    validate = publishing["jobs"]["validate"]
    assert validate["uses"] == "./.github/workflows/ci.yml"
    assert validate["secrets"]["METAADS_CI_PROXY"] == "${{ secrets.METAADS_CI_PROXY }}"
    assert publishing["jobs"]["publish"]["needs"] == "validate"


def test_live_failures_remain_blocking_and_mcp_live_runs_after_core_live():
    jobs = workflow("ci")["jobs"]
    for name in ("live-connectivity", "live-proxy", "live-meta", "mcp-live"):
        job = jobs[name]
        assert job.get("continue-on-error", "false") == "false"
        assert job["env"]["METAADS_CI_PROXY"] == "${{ secrets.METAADS_CI_PROXY }}"
        for step in job["steps"]:
            assert step.get("continue-on-error", "false") == "false"
    assert "live-meta" in jobs["mcp-live"]["needs"]
    assert any("scripts/check_distribution.py --live" in step.get("run", "") for step in jobs["live-meta"]["steps"])


def test_sock_dns_diagnostics_run_on_actual_distribution_and_remain_blocking():
    job = workflow("ci")["jobs"]["live-proxy"]
    assert job["needs"] == ["distribution"]
    assert job["runs-on"] == "macos-latest"
    assert any("--live --proxy-diagnostics" in step.get("run", "") for step in job["steps"])
    upload = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload) == 1 and upload[0]["if"] == "always()"


def test_public_package_verification_includes_core_and_mcp_live_tests():
    verification = workflow("publish")["jobs"]["verify-published"]
    commands = "\n".join(step.get("run", "") for step in verification["steps"])
    assert "scripts/check_distribution.py --published current --live" in commands
    assert "mcp/check_distribution.py --dist-dir published-dist --live" in commands
    assert verification.get("continue-on-error", "false") == "false"


def test_live_invocations_retry_only_transport_failures():
    core = script_namespace("scripts/check_distribution.py")
    extension = script_namespace("mcp/check_distribution.py")
    assert extension["LIVE_TRANSPORT_ERRORS"] == core["LIVE_TRANSPORT_ERRORS"]
    assert extension["live_rerun_arguments"]() == core["live_rerun_arguments"]()
    arguments = core["live_rerun_arguments"]()
    assert arguments[:4] == ["--reruns", "2", "--reruns-delay", "15"]
    patterns = [arguments[index + 1] for index, flag in enumerate(arguments) if flag == "--only-rerun"]
    assert patterns == list(core["LIVE_TRANSPORT_ERRORS"])

    def retried(message):
        return any(re.search(pattern, message) for pattern in patterns)

    # Failures observed on the residential CI proxy leg are retried.
    assert retried("Timeout: Failed to perform, curl: (28) Connection timed out after 30004 milliseconds")
    assert retried("AssertionError: Connection error: Failed to perform, curl: (7) CONNECT tunnel failed, response 590")
    assert retried("AuthenticationError: Failed to initialize async client: Failed to perform, curl: (28)")
    assert retried("RateLimitError: Max retries exceeded due to rate limiting")
    # Failures about Meta's data or the library's behaviour are not.
    assert not retried("AssertionError: assert 2 == 3")
    assert not retried("AssertionError: Actual Meta detail field eu_total_reach was not enriched")
    assert not retried("KeyError: 'ad_archive_id'")
    assert not retried("AssertionError: Meta preflight returned no ads for the broad query")
