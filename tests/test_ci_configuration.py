"""Regression contracts for the actual branch, release and private live CI configuration."""

import os
import tarfile
from pathlib import Path

import yaml


def workflow(name):
    relative = f".github/workflows/{name}.yml"
    sdist = os.environ.get("METAADS_AUDIT_SDIST")
    if sdist:
        with tarfile.open(sdist) as archive:
            member, = [member for member in archive.getmembers() if member.name.endswith("/" + relative)]
            content = archive.extractfile(member).read().decode("utf-8")
    else:
        content = (Path(__file__).resolve().parents[1] / relative).read_text(encoding="utf-8")
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
    for name in ("live-connectivity", "live-meta", "mcp-live"):
        job = jobs[name]
        assert job.get("continue-on-error", "false") == "false"
        assert job["env"]["METAADS_CI_PROXY"] == "${{ secrets.METAADS_CI_PROXY }}"
        for step in job["steps"]:
            assert step.get("continue-on-error", "false") == "false"
    assert "live-meta" in jobs["mcp-live"]["needs"]
    assert any("scripts/check_distribution.py --live" in step.get("run", "") for step in jobs["live-meta"]["steps"])


def test_public_package_verification_includes_core_and_mcp_live_tests():
    verification = workflow("publish")["jobs"]["verify-published"]
    commands = "\n".join(step.get("run", "") for step in verification["steps"])
    assert "scripts/check_distribution.py --published current --live" in commands
    assert "mcp/check_distribution.py --dist-dir published-dist --live" in commands
    assert verification.get("continue-on-error", "false") == "false"
