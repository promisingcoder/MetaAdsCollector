"""The extra is optional, but explicitly requesting it must install its dependency."""
from importlib.metadata import metadata, requires

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


def test_plain_install_excludes_sdk_and_extra_selects_it_on_every_python():
    sdk = next(Requirement(item) for item in requires("meta-ads-collector") if Requirement(item).name == "mcp")
    assert not sdk.marker.evaluate({"extra": "", "python_version": "3.9"})
    assert sdk.marker.evaluate({"extra": "mcp", "python_version": "3.9"}), (
        "An incompatible Python must fail dependency resolution, not silently omit the requested MCP SDK"
    )
    assert sdk.marker.evaluate({"extra": "mcp", "python_version": "3.12"})
    assert SpecifierSet(metadata("meta-ads-collector")["Requires-Python"]).contains("3.9")


def test_sdk_requires_python_310_and_core_remains_separate():
    requirement = SpecifierSet(metadata("mcp")["Requires-Python"])
    assert not requirement.contains("3.9")
    assert requirement.contains("3.10")
