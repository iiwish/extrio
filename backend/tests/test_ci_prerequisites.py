from pathlib import Path

import yaml


def backend_steps():
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    return yaml.safe_load(workflow.read_text())["jobs"]["backend"]["steps"]


def test_upgrade_tests_have_the_historical_git_baseline():
    checkout = next(step for step in backend_steps() if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout.get("with", {}).get("fetch-depth") == 0


def test_browser_runtime_is_installed_before_backend_tests():
    commands = [step["run"] for step in backend_steps() if "run" in step]
    browser = "uv run --project backend python -m playwright install --with-deps chromium"
    suite = "uv run --project backend pytest -c backend/pyproject.toml backend/tests"
    assert commands.index(browser) < commands.index(suite)
