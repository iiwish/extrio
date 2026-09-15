from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

from extrio.config import Settings


def test_default_contracts_path_uses_repository_contracts() -> None:
    project_dir = Path(__file__).resolve().parents[1]

    settings = Settings(_env_file=None).resolve_paths(project_dir)

    assert settings.contracts_path == project_dir.parent / "docs" / "contracts"
    assert (settings.contracts_path / "openapi.yaml").is_file()


def test_explicit_contracts_path_is_resolved_from_project(tmp_path: Path) -> None:
    settings = Settings(contracts_path=Path("fixtures/contracts"), _env_file=None).resolve_paths(tmp_path)

    assert settings.contracts_path == tmp_path / "fixtures" / "contracts"


def test_postgres_environment_is_explicit_and_escaped(monkeypatch) -> None:
    values = {"PGHOST": "postgresql", "PGPORT": "5432", "PGDATABASE": "extrio_alpha", "PGUSER": "app", "PGPASSWORD": "a@:/?#%$b"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    assert Settings(_env_file=None).database_url is None
    settings = Settings(database_from_pg_env=True, _env_file=None)
    parsed = conninfo_to_dict(settings.database_url)
    assert parsed["password"] == values["PGPASSWORD"]
    assert parsed["dbname"] == "extrio_alpha"
    assert parsed["host"] == "postgresql"
    with pytest.raises(ValueError, match="either"):
        Settings(database_from_pg_env=True, database_url="postgresql://example/db", _env_file=None)


def test_postgres_environment_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("PGPASSWORD", raising=False)
    with pytest.raises(ValueError, match="all five"):
        Settings(database_from_pg_env=True, _env_file=None)
