import copy
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
SECURITY_RANGES = {
    "filelock": SpecifierSet(">=4.2.1,<5"),
    "pypdf": SpecifierSet(">=6.21.2,<7"),
}


def project_metadata():
    return tomllib.loads((ROOT / "backend/pyproject.toml").read_text())


def locked_packages():
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    return {canonicalize_name(package["name"]): package for package in lock["package"]}


def assert_declared_security_floor(project, name):
    dependencies = project["project"]["dependencies"]
    if name == "filelock":
        assert all(canonicalize_name(Requirement(item).name) != name for item in dependencies)
        dependencies = project.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
    matches = [Requirement(item) for item in dependencies if canonicalize_name(Requirement(item).name) == name]
    assert len(matches) == 1, f"Missing or duplicate security requirement for {name}"
    assert matches[0].marker is None
    assert not matches[0].extras
    assert matches[0].specifier == SECURITY_RANGES[name]


def assert_secure_locked_version(name, raw_version):
    resolved = Version(raw_version)
    assert not resolved.is_prerelease and not resolved.is_devrelease
    assert resolved in SECURITY_RANGES[name], f"Unpatched or unsupported {name} version: {resolved}"


@pytest.mark.parametrize("name", SECURITY_RANGES)
def test_project_persists_security_floor(name):
    assert_declared_security_floor(project_metadata(), name)


@pytest.mark.parametrize("name", SECURITY_RANGES)
def test_locked_dependency_is_patched(name):
    assert_secure_locked_version(name, locked_packages()[name]["version"])


@pytest.mark.parametrize("name", SECURITY_RANGES)
def test_installed_dependency_matches_secure_lock(name):
    locked_version = locked_packages()[name]["version"]
    assert_secure_locked_version(name, locked_version)
    assert Version(version(name)) == Version(locked_version), f"Installed {name} differs from uv.lock"


@pytest.mark.parametrize("change", ["missing_filelock", "old_filelock", "missing_pypdf", "old_pypdf"])
def test_security_floor_rejects_missing_or_vulnerable_declarations(change):
    project = copy.deepcopy(project_metadata())
    if change.endswith("filelock"):
        project.setdefault("tool", {}).setdefault("uv", {})["constraint-dependencies"] = (
            [] if change.startswith("missing") else ["filelock>=3.32.4,<5"]
        )
        name = "filelock"
    else:
        dependencies = project["project"]["dependencies"]
        project["project"]["dependencies"] = [
            item for item in dependencies if canonicalize_name(Requirement(item).name) != "pypdf"
        ]
        if change.startswith("old"):
            project["project"]["dependencies"].append("pypdf>=6,<7")
        name = "pypdf"
    with pytest.raises(AssertionError):
        assert_declared_security_floor(project, name)


@pytest.mark.parametrize(("name", "old_version"), [("filelock", "3.32.4"), ("pypdf", "6.21.1")])
def test_security_version_gate_rejects_vulnerable_versions(name, old_version):
    with pytest.raises(AssertionError, match="Unpatched or unsupported"):
        assert_secure_locked_version(name, old_version)
