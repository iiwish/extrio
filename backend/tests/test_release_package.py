import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

from extrio import __version__


def test_release_version_metadata_is_consistent():
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "backend/pyproject.toml").read_text())
    lock = tomllib.loads((root / "backend/uv.lock").read_text())
    locked_project = next(package for package in lock["package"] if package["name"] == "extrio-backend")
    web = json.loads((root / "web/package.json").read_text())
    assert project["project"]["version"] == locked_project["version"] == web["version"] == __version__ == "1.0.0"


def test_source_distribution_builds_a_self_contained_wheel(tmp_path):
    uv = shutil.which("uv")
    if not uv:
        pytest.skip("Release packaging requires uv")
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([uv, "build", "--project", str(backend), "--out-dir", str(tmp_path / "dist")], capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode()
    wheel = next((tmp_path / "dist").glob("*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        for name in (
            "extrio/LICENSE",
            "extrio/NOTICE",
            "extrio/contracts_data/gather-spec.schema.json",
            "extrio/migrations/008_item_entity_index.pg.sql",
            "extrio/migrations/008_item_entity_index.sqlite.sql",
            "extrio/migrations/013_runtime_backfills.pg.sql",
            "extrio/migrations/013_runtime_backfills.sqlite.sql",
        ):
            assert name in archive.namelist()
        metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        assert metadata["Version"] == __version__
        assert not any("/data/" in name or name.endswith("/.env") for name in archive.namelist())
        archive.extractall(installed)
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXTRIO_")}
    env.update(
        PYTHONPATH=str(installed), EXTRIO_DATABASE_URL="", EXTRIO_DATABASE_PATH=str(tmp_path / "package.db"), EXTRIO_SEED_DEMO="false"
    )
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.store import Store
settings = get_settings()
assert 'installed/extrio/contracts_data' in str(settings.contracts_path)
ContractBundle(settings.contracts_path)
store = Store(settings.database_path, database_url='')
store.initialize(migrate=True)
assert store.list_collectors() == []
""",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert check.returncode == 0, check.stderr.decode()
