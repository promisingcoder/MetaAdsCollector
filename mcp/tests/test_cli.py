"""Real CLI subprocesses for non-network operations and explicit setup errors."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mode", ["discover", "worker"])
def test_cli_modes_and_single_pass_worker(tmp_path, mode):
    command = [sys.executable, "-m", "meta_ads_collector_mcp", mode, "--data-dir", str(tmp_path)]
    if mode == "worker":
        command.append("--once")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    if mode == "discover":
        assert json.loads(result.stdout)["transport"] == "stdio"
    else:
        assert result.stdout == "", "Worker logging must not pollute protocol stdout"


def test_cli_missing_secret_is_explicit_and_private(tmp_path):
    environment = os.environ.copy()
    environment.pop("MCP_NONEXISTENT_PROXY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "meta_ads_collector_mcp",
            "discover",
            "--data-dir",
            str(tmp_path),
            "--proxy-env",
            "MCP_NONEXISTENT_PROXY",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stderr)["code"] == "missing_secret"
    assert not result.stdout


def test_cli_invalid_concurrency():
    result = subprocess.run(
        [sys.executable, "-m", "meta_ads_collector_mcp", "--concurrency", "0"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2


def test_cli_python_requirement_does_not_change_core(monkeypatch):
    from meta_ads_collector_mcp.cli import main

    monkeypatch.setattr(sys, "argv", ["meta-ads-mcp", "discover"])
    monkeypatch.setattr(sys, "version_info", (3, 9))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_cli_missing_extra_reports_install_command(monkeypatch):
    from meta_ads_collector_mcp.cli import main

    monkeypatch.setattr(sys, "argv", ["meta-ads-mcp", "discover"])
    monkeypatch.setitem(sys.modules, "mcp.server", None)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
