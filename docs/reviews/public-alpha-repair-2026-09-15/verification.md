# Public-alpha release repair verification

Date: 2026-09-15. Scope: release-entry repair and portfolio presentation, following
the user's request to fix the release gaps. Existing product changes are retained;
no application behavior is changed by this repair.

## Changes

- README, CONTRIBUTING, backend README and CI explicitly select the backend pytest
  configuration and test directory when invoked from the repository root.
- The documentation manifest is regenerated from the canonical files.
- README references inspected September 14 desktop acceptance screenshots.
- `docs/showcase.md` provides the demonstration sequence and honest evidence boundaries.
- `scripts/verify-source.sh` verifies a disposable source startup, worker readiness,
  first-admin setup state, anonymous access rejection and the frontend response.
  It isolates storage and keys and stops its processes on exit.

## Results

| Command / check | Result |
| --- | --- |
| `uv run --project backend pytest -c backend/pyproject.toml backend/tests -q` | 576 passed, 21 skipped; 79.15s |
| `pnpm --dir web test` | 42 files, 262 tests passed |
| `pnpm --dir web build` | Passed |
| `pnpm --dir web lint` | Passed |
| `uv run --project backend ruff check backend/src backend/tests` | Passed |
| `uv run --project backend python scripts/update-docset-manifest.py --check` | Passed |
| `git diff --check` | Passed |
| `bash -n scripts/verify-source.sh` | Passed |
| `EXTRIO_WEB_PORT=5173 bash scripts/verify-source.sh` | Expected occupied-port rejection; existing service preserved |

## Isolated source verification

The candidate source was copied using `git ls-files --cached --others
--exclude-standard` into `/tmp/extrio-release-check.eQj90p`, excluding ignored
dependencies, runtime state and secrets. This includes untracked source; it is a
working-tree snapshot, not a clean release commit. Package caches were reused.

In that directory:

- `uv sync --project backend --locked --python 3.12`: passed, new virtual environment.
- `pnpm --dir web install --frozen-lockfile`: passed, new node_modules; mirror downloads took 3m 28.7s.
- `pnpm --dir web build`: passed.
- `uv build --project backend --wheel`: passed; wheel contains `extrio/contracts_data/openapi.yaml`.
- `uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_source_samples.py -q`: 28 passed.
- `bash scripts/verify-source.sh`: passed; API, worker and web stopped by cleanup.
- `uv run --project backend python scripts/benchmark.py --collectors 1 --pages 1`:
  succeeded, 3 list pages, 4 detail pages, 4 accepted, 0 rejected, `next_link_exhausted`.
  Uses a fixed signed rule and temporary SQLite/artifacts, not an AI-generated rule.

## Open gates

- Container verification was interrupted during dependency/image downloads. The
  default web test port 18080 is occupied by another application. No container
  acceptance is claimed. The disposable Compose project
  `extrio-e2e-release-check-20260915` has no remaining containers or volumes.
- PostgreSQL integration, remote CI and release secret scanning are not verified
  by this local run. The skipped backend tests remain explicit.
- Existing changes and required untracked files need an intentional release commit
  and verification of that exact commit before tagging. No commit, push or tag is
  created by this repair.
- Real-model/source P28 and uninterrupted 72-hour P31 evidence remain open on the
  stable-release track. No paid model run or public deployment was performed.
- The walkthrough is not a recorded video. Screenshots are existing inspected QA
  captures, not freshly captured browser evidence from this turn.

Conclusion: local source-based portfolio/public-alpha preparation is verified;
container distribution and a stable release are not fully accepted.
