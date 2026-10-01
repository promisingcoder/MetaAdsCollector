"""Verify the optional extra in a clean wheel install outside the source tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifacts = args.dist_dir.resolve()
    wheel = next(artifacts.glob("*.whl"))
    sdist = next(artifacts.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        assert "meta_ads_collector_mcp/server.py" in archive.namelist()
        forbidden = ("runtime/", ".private/", "ci_proxy.secret", "metaads_audit_report")
        assert not any(part in name for name in archive.namelist() for part in forbidden)
        metadata = archive.read(next(name for name in archive.namelist() if name.endswith("/METADATA"))).decode()
        assert "Provides-Extra: mcp" in metadata
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        assert any(name.endswith("mcp/tests/test_live.py") for name in names)
        assert not any(part in name for name in names for part in forbidden)
    results = root / "mcp/test-results"
    results.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metaads-mcp-wheel-") as directory:
        work = Path(directory)
        venv.EnvBuilder(with_pip=True).create(work / "venv")
        python = work / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], cwd=work, env=environment, check=True)
        plain = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import meta_ads_collector; from importlib.metadata import distributions; "
                "assert 'mcp' not in {d.metadata['Name'].lower() for d in distributions()}; "
                "print('Core installation has no MCP SDK dependency')",
            ],
            cwd=work,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        print(plain.stdout.strip())
        missing_extra = subprocess.run(
            [str(python), "-m", "meta_ads_collector_mcp", "discover", "--data-dir", str(work / "probe")],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing_extra.returncode == 2 and "[mcp]" in missing_extra.stderr
        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheel) + "[mcp]", "pytest", "pytest-asyncio", "pytest-cov"],
            cwd=work,
            env=environment,
            check=True,
        )
        # Only tests/fixtures are copied. There is no collector source in this directory.
        shutil.copytree(root / "mcp/tests", work / "mcp/tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(root / "README.md", work / "README.md")
        (work / "tests").mkdir()
        for name in ("__init__.py", "audit_meta_samples.py", "meta_full_sample.py", "ci_network.py"):
            shutil.copy2(root / "tests" / name, work / "tests" / name)
        (work / "pytest.ini").write_text(
            "[pytest]\nasyncio_mode=auto\nmarkers=\n    mcp_live: Actual Meta MCP checks\n", encoding="utf-8"
        )
        probe = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import json,meta_ads_collector as c,meta_ads_collector_mcp as m; "
                "print(json.dumps({'core':c.__file__,'mcp':m.__file__}))",
            ],
            cwd=work,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        locations = json.loads(probe.stdout)
        assert all(str(work / "venv").lower() in value.lower() for value in locations.values())
        marker = "mcp_live" if args.live else "not mcp_live"
        report = results / ("wheel-live.xml" if args.live else "wheel-unit.xml")
        command = [
            str(python),
            "-m",
            "pytest",
            "mcp/tests",
            "-m",
            marker,
            "-q",
            "--tb=short",
            "--junitxml=" + str(report),
        ]
        if args.live:
            command.append("--run-mcp-live")
        subprocess.run(command, cwd=work, env=environment, check=True)


if __name__ == "__main__":
    main()
