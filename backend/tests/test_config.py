from pathlib import Path

from extrio.config import Settings


def test_default_contracts_path_uses_repository_contracts() -> None:
    project_dir = Path(__file__).resolve().parents[1]

    settings = Settings(_env_file=None).resolve_paths(project_dir)

    assert settings.contracts_path == project_dir.parent / "docs" / "contracts"
    assert (settings.contracts_path / "openapi.yaml").is_file()


def test_explicit_contracts_path_is_resolved_from_project(tmp_path: Path) -> None:
    settings = Settings(contracts_path=Path("fixtures/contracts"), _env_file=None).resolve_paths(tmp_path)

    assert settings.contracts_path == tmp_path / "fixtures" / "contracts"
