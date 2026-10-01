"""Check the README shipped to PyPI, including its exact real-Meta examples."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from importlib.metadata import entry_points, metadata
from pathlib import Path

import pytest


def readme():
    return metadata("meta-ads-collector")["Description"]


def code(language):
    return re.findall(r"```" + language + r"\n(.*?)```", readme(), re.DOTALL)


def test_pypi_readme_has_only_the_requested_sections():
    assert re.findall(r"^## (.+)$", readme(), re.MULTILINE) == [
        "Installation", "MCP quick start", "Collector basics"
    ]
    assert not re.search(r"^###", readme(), re.MULTILINE)
    assert 'meta-ads-collector[mcp]' in readme()
    assert 'Python 3.10+' in readme()
    assert 'Python 3.9+' in readme()


def test_pypi_description_is_identical_to_repository_readme():
    assert readme().replace("\r\n", "\n").strip() == Path("README.md").read_text(
        encoding="utf-8"
    ).replace("\r\n", "\n").strip()


def test_readme_client_config_selects_the_installed_stdio_entry_point():
    config, = code("json")
    server = json.loads(config)["mcpServers"]["meta-ads"]
    assert server == {"command": "meta-ads-mcp", "args": []}
    entry, = entry_points(group="console_scripts", name=server["command"])
    assert entry.value == "meta_ads_collector_mcp.cli:main"
    assert callable(entry.load())


def test_readme_collector_command_is_accepted_by_the_real_cli(monkeypatch):
    from meta_ads_collector.cli import parse_args

    command, = [block.strip() for block in code("bash") if "-q" in block]
    arguments = shlex.split(command)
    assert arguments[:3] == ["python", "-m", "meta_ads_collector"]
    monkeypatch.setattr(sys, "argv", ["meta-ads-collector", *arguments[3:]])
    parsed = parse_args()
    assert (parsed.query, parsed.country, parsed.max_results, parsed.output) == ("nike", "US", 10, "ads.csv")


def test_readme_discovery_command_runs_without_meta_access(tmp_path):
    command, = [block.strip() for block in code("bash") if block.strip().endswith(" discover")]
    arguments = shlex.split(command)
    completed = subprocess.run(
        [sys.executable, *arguments[1:], "--data-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    capabilities = json.loads(completed.stdout)
    assert capabilities["transport"] == "stdio"
    assert len(capabilities["operations"]) == 10


@pytest.mark.mcp_live
def test_exact_readme_python_example_returns_actual_meta_ads(capsys):
    example, = code("python")
    exec(compile(example, "README.md:python-example", "exec"), {})
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 5
    assert all(line.split()[0].isdigit() for line in lines)
    assert len({line.split()[0] for line in lines}) == 5


@pytest.mark.mcp_live
def test_exact_readme_cli_example_exports_actual_meta_csv(tmp_path):
    import csv

    from meta_ads_collector import Ad

    example, = [block.strip() for block in code("bash") if "-q" in block]
    arguments = shlex.split(example)
    completed = subprocess.run(
        [sys.executable, *arguments[1:]], cwd=tmp_path,
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, "README CLI failed; investigate private captured subprocess output"
    with (tmp_path / "ads.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 10
    assert len({row["id"] for row in rows}) == 10
    for row in rows:
        assert Ad.from_graphql_response(json.loads(row["api_fields"])).id == row["id"]
