import copy
import runpy
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


def workflow():
    return yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)


def test_release_labels_are_promoted_only_after_checks_scan_and_signatures():
    config = workflow()
    assert config["jobs"]["publish"]["needs"] == "verify"
    steps = config["jobs"]["publish"]["steps"]
    builds = [step for step in steps if "docker/build-push-action@" in step.get("uses", "")]
    assert len(builds) == 2
    for step in builds:
        assert "RELEASE_TAG" not in step["with"]["tags"]
        assert "CANDIDATE_TAG" in step["with"]["tags"]
    promotion = next(i for i, step in enumerate(steps) if step.get("name") == "Promote verified image manifests")
    scans = [i for i, step in enumerate(steps) if "trivy-action@" in step.get("uses", "")]
    assert len(scans) == 4 and max(scans) < promotion
    assert next(i for i, step in enumerate(steps) if step.get("name") == "Sign image manifests") < promotion
    assert next(i for i, step in enumerate(steps) if step.get("name") == "Attest web provenance") < promotion
    assert "github.sha" not in steps[promotion]["run"]
    for step in steps:
        assert step.get("continue-on-error", "false") == "false"


def test_release_web_image_refreshes_runtime_security_packages():
    steps = workflow()["jobs"]["publish"]["steps"]
    web = next(step for step in steps if step.get("id") == "web")
    assert web["with"]["no-cache-filters"] == "runtime"
    assert "FROM nginx:1.29-alpine AS runtime" in (ROOT / "docker/web.Dockerfile").read_text()


@pytest.fixture
def gate():
    return runpy.run_path(str(ROOT / "scripts/verify-release.py"))


def evidence():
    runs = [
        {"id": 10, "path": ".github/workflows/ci.yml", "head_sha": SHA, "event": "push", "run_attempt": 1,
         "head_repository": {"full_name": "iiwish/extrio"}, "status": "completed", "conclusion": "success"},
        {"id": 11, "path": ".github/workflows/container.yml", "head_sha": SHA, "event": "push", "run_attempt": 1,
         "head_repository": {"full_name": "iiwish/extrio"}, "status": "completed", "conclusion": "success"},
    ]
    jobs = {
        10: [{"name": name, "status": "completed", "conclusion": "success"} for name in ("backend", "web", "repository-security")],
        11: [{"name": "compose-e2e", "status": "completed", "conclusion": "success"}],
    }
    return runs, jobs


def api_for(runs, jobs):
    def api(path):
        if "/attempts/" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return [{"jobs": jobs[run_id]}]
        return [{"workflow_runs": runs[:1]}, {"workflow_runs": runs[1:]}]
    return api


def test_release_gate_accepts_exact_commit_and_all_required_jobs(gate):
    runs, jobs = evidence()
    gate["verify_checks"]("iiwish/extrio", SHA, api_for(runs, jobs))


@pytest.mark.parametrize("failure", [
    "wrong_sha", "fork", "missing_run", "queued", "newer_failed", "skipped_job", "missing_job", "pr_event",
])
def test_release_gate_fails_closed(gate, failure):
    runs, jobs = evidence()
    if failure == "wrong_sha":
        runs[0]["head_sha"] = "b" * 40
    elif failure == "fork":
        runs[0]["head_repository"]["full_name"] = "fork/extrio"
    elif failure == "missing_run":
        runs.pop()
    elif failure == "queued":
        runs[0].update(status="queued", conclusion=None)
    elif failure == "newer_failed":
        newer = copy.deepcopy(runs[0])
        newer.update(id=12, conclusion="failure")
        runs.append(newer)
    elif failure == "skipped_job":
        jobs[10][0]["conclusion"] = "skipped"
    elif failure == "missing_job":
        jobs[10].pop()
    elif failure == "pr_event":
        runs[0]["event"] = "pull_request"
    with pytest.raises(RuntimeError):
        gate["verify_checks"]("iiwish/extrio", SHA, api_for(runs, jobs))


@pytest.mark.parametrize("tag", ["main", "--help", "v1;echo bad", "v1.0.0\nextra", "v1.0.0/other"])
def test_release_gate_rejects_non_release_refs(gate, tag):
    with pytest.raises(ValueError):
        gate["resolve_release"](tag)


def test_release_resolution_uses_tag_commit_and_rejects_non_main_history(gate, tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Release Test", "-c", "user.email=test@example.com", *args],
            cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("commit", "--allow-empty", "-m", "Initial release")
    sha = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", sha)
    git("tag", "-a", "v1.0.0", "-m", "Release")
    git("commit", "--allow-empty", "-m", "Dispatcher is ahead")
    monkeypatch.chdir(tmp_path)
    assert gate["resolve_release"]("v1.0.0") == sha
    git("checkout", "--orphan", "unreviewed")
    git("commit", "--allow-empty", "-m", "Not on main")
    git("tag", "v2.0.0")
    with pytest.raises(subprocess.CalledProcessError):
        gate["resolve_release"]("v2.0.0")


def test_release_gate_required_jobs_match_repository_workflows(gate):
    for path, required in gate["REQUIRED_WORKFLOWS"].items():
        config = yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)
        assert set(config["jobs"]) == required
        assert "workflow_dispatch" in config["on"]
