"""Package metadata, dependency-floor and source-archive regressions."""

from __future__ import annotations

import os
import re
import subprocess
import tarfile
from importlib.metadata import requires
from pathlib import Path

import pytest
from packaging.requirements import Requirement


def test_documented_core_dependency_matches_the_installable_package():
    source = Path(__file__).resolve().parents[1] / "docs" / "contributing.md"
    if source.is_file():
        documentation = source.read_text(encoding="utf-8")
    else:
        with tarfile.open(os.environ["METAADS_AUDIT_SDIST"]) as archive:
            member = next(item for item in archive.getmembers() if item.name.endswith("/docs/contributing.md"))
            documentation = archive.extractfile(member).read().decode("utf-8")
    dependencies = [Requirement(value) for value in requires("meta-ads-collector") or []]
    curl_requirement = next(item for item in dependencies if item.name.replace("_", "-") == "curl-cffi")
    floor = next(spec.version for spec in curl_requirement.specifier if spec.operator == ">=")
    assert re.findall(r"curl_cffi>=([0-9.]+)", documentation) == [floor]


def test_published_package_imports_with_its_declared_minimum_dependency():
    """A resolver-valid installation must at least import before contacting Meta.

    Set METAADS_AUDIT_MIN_PYTHON to the interpreter of a clean environment
    containing the candidate build and its exact declared curl-cffi minimum.
    The distribution CI job prepares this without using the checkout package.
    """
    dependencies = [Requirement(value) for value in requires("meta-ads-collector") or []]
    curl_requirement = next(item for item in dependencies if item.name.replace("_", "-") == "curl-cffi")
    assert "0.7.0" not in curl_requirement.specifier, "curl-cffi 0.7.0 cannot import RequestException"
    floor = next(spec.version for spec in curl_requirement.specifier if spec.operator == ">=")
    interpreter = os.environ.get("METAADS_AUDIT_MIN_PYTHON")
    if not interpreter:
        pytest.skip("Exact-floor installation is checked by the distribution CI job")
    assert Path(interpreter).is_file()
    probe = subprocess.run(
        [interpreter, "-I", "-c", "import importlib.metadata as m; "
         f"assert m.version('curl-cffi') == {floor!r}; "
         "from meta_ads_collector import MetaAdsCollector; "
         "print('Package import succeeded')"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_published_sdist_includes_support_for_the_tests_it_ships(tmp_path):
    """Bundled tests must include their imported helpers and required fixtures."""
    artifact = os.environ.get("METAADS_AUDIT_SDIST")
    if not artifact:
        built = subprocess.run(
            [os.sys.executable, "-m", "build", "--sdist", "--no-isolation", "--outdir", str(tmp_path)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=120, check=False,
        )
        assert built.returncode == 0, built.stdout + built.stderr
        artifact = str(next(tmp_path.glob("*.tar.gz")))
    with tarfile.open(artifact) as archive:
        names = {"/".join(name.split("/")[1:]) for name in archive.getnames()}
    required = {
        "tests/__init__.py", "tests/utils.py", "tests/conftest.py", "tests/audit_meta_samples.py",
        "tests/meta_full_sample.py", "tests/meta_forward_proxy.py", "tests/ci_network.py",
        "tests/test_all_meta_fields.py",
        "tests/test_live_proxy_transport.py", "scripts/check_distribution.py",
    }
    required.update(f"tests/{path.name}" for path in Path(__file__).parent.glob("test_*.py"))
    assert required <= names, f"Bundled tests are missing support files: {sorted(required - names)}"
    assert not any(
        "_local_audit/" in name or "metaads_audit_report" in name or "docs_decision_checklist" in name
        for name in names
    )
