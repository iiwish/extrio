"""Read-only release gate: main ancestry and successful checks for the exact tag commit."""

import json
import os
import re
import subprocess

REQUIRED_WORKFLOWS = {
    ".github/workflows/ci.yml": {"repository-security", "backend", "web"},
    ".github/workflows/container.yml": {"compose-e2e"},
}


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def resolve_release(tag):
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", tag):
        raise ValueError("Release requires an existing version tag, for example v0.7.0-alpha.1")
    sha = command("git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Release tag did not resolve to a commit")
    command("git", "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main")
    return sha


def github_api(path):
    return json.loads(command("gh", "api", "--paginate", "--slurp", path))


def verify_checks(repository, sha, api=github_api):
    runs = [run for page in api(f"repos/{repository}/actions/runs?head_sha={sha}&per_page=100") for run in page["workflow_runs"]]
    for path, required_jobs in REQUIRED_WORKFLOWS.items():
        matching = [run for run in runs if run["path"] == path and run["head_sha"] == sha
                    and run["event"] in {"push", "workflow_dispatch"}
                    and run.get("head_repository", {}).get("full_name", "").casefold() == repository.casefold()]
        if not matching:
            raise RuntimeError(f"Missing exact-commit verification: {path}. Run that workflow on the release tag first.")
        latest = max(matching, key=lambda run: (run["id"], run["run_attempt"]))
        if latest["status"] != "completed" or latest["conclusion"] != "success":
            raise RuntimeError(f"Latest verification is not successful: {path} run {latest['id']}")
        job_pages = api(f"repos/{repository}/actions/runs/{latest['id']}/attempts/{latest['run_attempt']}/jobs?per_page=100")
        jobs = {job["name"]: job for page in job_pages for job in page["jobs"]}
        for name in required_jobs:
            job = jobs.get(name)
            if not job or job["status"] != "completed" or job["conclusion"] != "success":
                raise RuntimeError(f"Required job is missing or not successful: {path}: {name}")


def main():
    sha = resolve_release(os.environ["RELEASE_TAG"])
    if os.environ.get("VERIFIED_SHA") and os.environ["VERIFIED_SHA"] != sha:
        raise RuntimeError("Release tag moved after verification")
    verify_checks(os.environ["GITHUB_REPOSITORY"], sha)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"sha={sha}\n")
    print(f"Verified release commit {sha}")


if __name__ == "__main__":
    main()
