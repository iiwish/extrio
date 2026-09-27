"""Exercise verification modes without creating Docker resources or making requests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_IMAGE = "ghcr.io/iiwish/extrio-backend@sha256:" + "a" * 64
WEB_IMAGE = "ghcr.io/iiwish/extrio-web@sha256:" + "b" * 64


@pytest.fixture
def verifier(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands.jsonl"
    fake = """
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with Path(os.environ['FAKE_LOG']).open('a') as output:
    output.write(json.dumps([name, *args]) + '\\n')
if name == 'docker':
    if args[:2] == ['ps', '-aq'] and os.environ.get('FAKE_EXISTING_PROJECT'):
        print('existing-container')
    if 'up' in args and os.environ.get('FAKE_UP_FAILURE'):
        sys.exit(1)
elif name == 'curl':
    url = args[-1]
    if '--write-out' in args:
        print('401', end='')
    elif url.endswith('/readyz'):
        print('{"ready":true}')
    elif url.endswith('/auth/state'):
        print('{"setupRequired":true}')
    elif url.endswith('/auth/setup'):
        print('{"authenticated":true}')
    elif url.endswith('/auth/logout'):
        print('{"authenticated":false}')
    elif url.endswith('/collectors'):
        print('{"items":[]}')
    elif url.endswith('/'):
        print('<title>Extrio</title>')
    else:
        sys.exit(2)
"""
    for name in ("docker", "curl"):
        executable = binaries / name
        executable.write_text(f"#!{sys.executable}\n{fake}")
        executable.chmod(0o755)

    def run(*arguments, **overrides):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("EXTRIO_")}
        environment.update(
            PATH=f"{binaries}{os.pathsep}{environment['PATH']}",
            FAKE_LOG=str(log),
            EXTRIO_E2E_PROJECT="extrio-e2e-script-test",
            **overrides,
        )
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/verify-compose.sh"), *arguments],
            env=environment, capture_output=True, text=True, timeout=20,
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, commands

    return run


def test_default_compose_verification_keeps_local_build(verifier):
    result, commands = verifier()
    assert result.returncode == 0, result.stderr
    up = next(command for command in commands if command[0] == "docker" and "up" in command)
    assert "--build" in up
    assert "--no-build" not in up
    assert any("down" in command and "-v" in command for command in commands)


@pytest.mark.parametrize("compose_file", ["compose.yaml", "compose.postgres.yaml"])
def test_image_only_uses_pinned_images_and_never_rebuilds(verifier, compose_file):
    result, commands = verifier(
        "--image-only", EXTRIO_BACKEND_IMAGE=BACKEND_IMAGE, EXTRIO_WEB_IMAGE=WEB_IMAGE,
        EXTRIO_E2E_COMPOSE_FILE=str(ROOT / compose_file),
    )
    assert result.returncode == 0, result.stderr
    up = next(command for command in commands if command[0] == "docker" and "up" in command)
    assert "--no-build" in up
    assert up[up.index("--pull") + 1] == "always"
    assert not any("--build" in command or "build" in command for command in commands)
    assert BACKEND_IMAGE in result.stdout
    assert WEB_IMAGE in result.stdout
    assert any("down" in command and "-v" in command for command in commands)


@pytest.mark.parametrize("overrides", [
    {},
    {"EXTRIO_BACKEND_IMAGE": BACKEND_IMAGE},
    {"EXTRIO_WEB_IMAGE": WEB_IMAGE},
    {"EXTRIO_BACKEND_IMAGE": "ghcr.io/iiwish/extrio-backend:v1.0.0-rc.1", "EXTRIO_WEB_IMAGE": WEB_IMAGE},
    {"EXTRIO_BACKEND_IMAGE": BACKEND_IMAGE, "EXTRIO_WEB_IMAGE": "ghcr.io/iiwish/extrio-web:latest"},
    {"EXTRIO_BACKEND_IMAGE": BACKEND_IMAGE[:-1], "EXTRIO_WEB_IMAGE": WEB_IMAGE},
    {"EXTRIO_BACKEND_IMAGE": BACKEND_IMAGE + "\n", "EXTRIO_WEB_IMAGE": WEB_IMAGE},
])
def test_image_only_rejects_missing_or_non_digest_references_before_docker(verifier, overrides):
    result, commands = verifier("--image-only", **overrides)
    assert result.returncode != 0
    assert "digest-pinned" in result.stderr
    assert commands == []


@pytest.mark.parametrize("arguments", [("--build",), ("--image-only", "--build"), ("--unknown",)])
def test_unrecognized_arguments_fail_before_docker(verifier, arguments):
    result, commands = verifier(*arguments)
    assert result.returncode != 0
    assert "Usage:" in result.stderr
    assert commands == []


def test_image_only_rejects_unreviewed_compose_files_before_docker(verifier, tmp_path):
    compose = tmp_path / "override.yaml"
    compose.write_text("services: {}\n")
    result, commands = verifier(
        "--image-only", EXTRIO_BACKEND_IMAGE=BACKEND_IMAGE, EXTRIO_WEB_IMAGE=WEB_IMAGE,
        EXTRIO_E2E_COMPOSE_FILE=str(compose),
    )
    assert result.returncode != 0
    assert "repository compose.yaml or compose.postgres.yaml" in result.stderr
    assert commands == []


def test_image_only_failure_cleans_up_without_retrying_a_build(verifier):
    result, commands = verifier(
        "--image-only", EXTRIO_BACKEND_IMAGE=BACKEND_IMAGE, EXTRIO_WEB_IMAGE=WEB_IMAGE, FAKE_UP_FAILURE="1",
    )
    assert result.returncode != 0
    assert len([command for command in commands if "up" in command]) == 1
    assert not any("--build" in command or "build" in command for command in commands)
    assert any("down" in command and "-v" in command for command in commands)


def test_image_only_refuses_to_adopt_an_existing_project(verifier):
    result, commands = verifier(
        "--image-only", EXTRIO_BACKEND_IMAGE=BACKEND_IMAGE, EXTRIO_WEB_IMAGE=WEB_IMAGE, FAKE_EXISTING_PROJECT="1",
    )
    assert result.returncode != 0
    assert "Refusing to adopt" in result.stderr
    assert not any("up" in command or "down" in command for command in commands)
