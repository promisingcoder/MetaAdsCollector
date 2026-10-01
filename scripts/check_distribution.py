"""Test actual wheels outside the checkout, including hash-verified PyPI downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import venv
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement


def run(command: list[str], **kwargs) -> None:
    subprocess.run(command, check=True, **kwargs)


def fetch_published(version: str, destination: Path) -> tuple[Path, Path]:
    url = f"https://pypi.org/pypi/meta-ads-collector/{version}/json"
    for attempt in range(12):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                metadata = json.load(response)
            break
        except OSError:
            if attempt == 11:
                raise
            time.sleep(5)
    files = []
    for artifact in metadata["urls"]:
        path = destination / artifact["filename"]
        urllib.request.urlretrieve(artifact["url"], path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["digests"]["sha256"]:
            raise RuntimeError(f"PyPI SHA256 mismatch: {path.name}")
        files.append(path)
    return next(path for path in files if path.suffix == ".whl"), next(
        path for path in files if path.name.endswith(".tar.gz")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--published", help="Exact PyPI version, or current for pyproject.toml's version")
    parser.add_argument("--minimum", action="store_true", help="Pin curl-cffi to the declared minimum")
    parser.add_argument("--live", action="store_true", help="Run actual Meta integration checks")
    parser.add_argument("--preflight", action="store_true", help="Run only the bounded live connectivity check")
    parser.add_argument("--evidence-dir", type=Path, default=Path("ci-results"))
    args = parser.parse_args()
    if args.preflight and not args.live:
        parser.error("--preflight requires --live")
    root = Path(__file__).resolve().parents[1]
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    if args.published == "current":
        match = re.search(r'^version = "([^\"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        if not match:
            raise RuntimeError("Missing project version")
        args.published = match.group(1)
    with tempfile.TemporaryDirectory(prefix="mac-dist-") as directory:
        temporary = Path(directory)
        if args.published:
            wheel, sdist = fetch_published(args.published, temporary)
        else:
            wheel = next(args.dist_dir.resolve().glob("*.whl"))
            sdist = next(args.dist_dir.resolve().glob("*.tar.gz"))
        with zipfile.ZipFile(wheel) as archive:
            metadata = Parser().parsestr(archive.read(next(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )).decode("utf-8"))
            for source in (root / "meta_ads_collector").glob("*.py"):
                packaged = archive.read(f"meta_ads_collector/{source.name}")
                if packaged.replace(b"\r\n", b"\n") != source.read_bytes().replace(b"\r\n", b"\n"):
                    raise RuntimeError(f"Wheel does not match repository: {source.name}")
        version = metadata["Version"]
        requirement = next(Requirement(value) for value in metadata.get_all("Requires-Dist", [])
                           if Requirement(value).name.replace("_", "-") == "curl-cffi")
        floor = next(spec.version for spec in requirement.specifier if spec.operator == ">=")
        environment = temporary / "env"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = [str(python), "-m", "pip", "install", f"{wheel}[dev]"]
        if args.minimum:
            install.append(f"curl-cffi=={floor}")
        run(install)
        suite = temporary / "suite"
        suite.mkdir()
        # Execute the tests actually shipped in the source archive, outside the checkout.
        with tarfile.open(sdist) as archive:
            for member in archive.getmembers():
                relative = Path(*Path(member.name).parts[1:])
                if not member.isfile() or not relative.parts:
                    continue
                if relative.parts[0] != "tests" and str(relative) != "pyproject.toml":
                    continue
                destination = (suite / relative).resolve()
                if suite.resolve() not in destination.parents:
                    raise RuntimeError("Unsafe path in source archive")
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"Missing archived file: {relative}")
                content = stream.read()
                local = root / relative
                if local.is_file() and content.replace(b"\r\n", b"\n") != local.read_bytes().replace(b"\r\n", b"\n"):
                    raise RuntimeError(f"Source archive does not match repository: {relative}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
        for source in (root / "tests").glob("*.py"):
            if not (suite / "tests" / source.name).is_file():
                raise RuntimeError(f"Source archive omits test: {source.name}")
        run([str(python), "-I", "-c", "import pathlib, importlib.metadata as m; "
             "import meta_ads_collector as p; "
             f"assert p.__version__ == {version!r}; "
             "assert 'site-packages' in str(pathlib.Path(p.__file__)); "
             "print('Testing installed wheel:', p.__version__, p.__file__, "
             "'curl-cffi', m.version('curl-cffi'))"], cwd=suite)
        env = os.environ.copy()
        env["METAADS_AUDIT_SDIST"] = str(sdist)
        env.pop("METAADS_AUDIT_MIN_PYTHON", None)
        if args.minimum:
            env["METAADS_AUDIT_MIN_PYTHON"] = str(python)
        label = "preflight" if args.preflight else "live" if args.live else "minimum" if args.minimum else "wheel"
        target = "tests/test_live_preflight.py" if args.preflight else "tests"
        command = [str(python), "-I", "-m", "pytest", target, "-q",
                   f"--junitxml={evidence / (label + '.xml')}"]
        if args.live:
            command += ["--run-integration", "-m", "integration", "-k", "not controlled"]
        else:
            command += ["-m", "not integration"]
        run(command, cwd=suite, env=env)


if __name__ == "__main__":
    main()
