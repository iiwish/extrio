import io
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def verifier():
    return runpy.run_path(str(ROOT / "scripts/verify-real-model.py"))


def arguments(tmp_path):
    return ["--source-url", "https://example.com/notices", "--output", str(tmp_path / "result.json"),
            "--authorize-model-call", "--api-key-stdin", "--base-url", "https://api.deepseek.com", "--model", "deepseek-flash"]


def test_explicit_model_credentials_are_read_from_stdin_not_arguments(verifier, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("fixture-secret-do-not-print\n"))
    args = verifier["parse_args"](arguments(tmp_path))
    provider, model, secret = verifier["read_model_configuration"](args)
    assert provider == {"provider": "openai", "baseUrl": "https://api.deepseek.com"}
    assert model["modelId"] == "deepseek-flash"
    assert secret == "fixture-secret-do-not-print"
    assert "fixture-secret" not in str(args)
    assert "fixture-secret" not in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("replacement", ["http://api.deepseek.com", "https://user:password@api.deepseek.com",
                                         "https://api.deepseek.com?token=secret", "https://api.deepseek.com/#fragment"])
def test_model_endpoint_rejects_insecure_or_embedded_credentials(verifier, tmp_path, replacement):
    argv = arguments(tmp_path)
    argv[argv.index("--base-url") + 1] = replacement
    with pytest.raises(SystemExit):
        verifier["parse_args"](argv)


def test_existing_configuration_and_direct_credentials_cannot_be_mixed(verifier, tmp_path):
    with pytest.raises(SystemExit):
        verifier["parse_args"]([*arguments(tmp_path), "--configuration-db", str(tmp_path / "state.db")])


def test_output_cannot_overwrite_prior_paid_attempt(verifier, tmp_path):
    (tmp_path / "result.json").write_text("prior evidence")
    with pytest.raises(SystemExit):
        verifier["parse_args"](arguments(tmp_path))
    assert (tmp_path / "result.json").read_text() == "prior evidence"


def test_empty_secret_is_rejected_without_initializing_an_instance(verifier, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(" \n"))
    args = verifier["parse_args"](arguments(tmp_path))
    with pytest.raises(ValueError, match="empty"):
        verifier["read_model_configuration"](args)
    assert list(tmp_path.iterdir()) == []


def test_isolated_verification_environment_is_explicit(verifier, tmp_path):
    env = verifier["isolated_environment"](tmp_path)
    assert env["EXTRIO_DATABASE_FROM_PG_ENV"] == "false"
    assert env["EXTRIO_AUTH_ENABLED"] == "true"
    assert env["EXTRIO_AUTH_COOKIE_SECURE"] == "false"
    assert env["EXTRIO_ALLOW_HTTP_PUBLIC"] == "true"
    assert env["EXTRIO_ALLOW_HTTP_LOCALHOST"] == "false"
    assert env["EXTRIO_SEED_DEMO"] == "false"
    assert env["EXTRIO_MODEL_API_KEY"] == ""
    assert str(tmp_path) in env["EXTRIO_DATABASE_PATH"]
