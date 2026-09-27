# Reliability Verification

## Scope

This record covers R1-R4 in `packet.md` and their required startup and migration guards.
Existing unrelated working-tree changes are preserved. No commit, deployment, image publication,
production migration, or remote release was performed.

## Verified Behavior

- Schedule claims survive restart. Run/Operation/Job creation and the dispatch receipt commit
  together. Failure after receipt writing and process termination before commit leave no partial
  dispatch. Concurrent dispatchers create one job. Paused, revised, or blocked schedules are skipped.
- SQLite migration SQL, foreign-key validation, and migration markers share a transaction. SQL
  errors and invalid references roll back data and DDL, and foreign-key enforcement is restored.
- Release verification resolves the tag's commit, requires main ancestry and successful exact-commit
  CI jobs, and rejects missing, skipped, failed, stale, or unrelated evidence. Workflow tests require
  all scans and signatures before candidate digests receive final tags.
- Historical compatibility and attribution backfills use bounded batches and a completion marker.
  Interrupted backfills can be retried; runtime startup refuses incomplete migration state. Completed
  runtime startup does not scan historical records. Source creation includes defaults atomically.
- The migration CLI requires an offline instance lock; doctor identifies incomplete backfills.
- The source launcher waits for both API and Web readiness. A deterministic delayed-Web regression
  test covers the startup race observed during the first smoke attempt.

Failure regressions were run before their corresponding fixes. SQLite and PostgreSQL tests cover
schedule recovery, backfill interruption, and upgrade behavior. Release checks use offline API
fixtures and temporary Git repositories, including annotated tags and unrelated history.

## Final Checks

| Check | Result |
| --- | --- |
| Full backend pytest with isolated PostgreSQL enabled | 750 passed, no skips, 90.69 seconds |
| Ruff: backend source, tests, and release verification script | Passed |
| Source startup smoke (`EXTRIO_DATABASE_FROM_PG_ENV=false bash scripts/verify-source.sh`) | Passed; temporary API, Worker, and Web stopped |
| Shell syntax: `scripts/dev.sh`, `scripts/verify-source.sh` | Passed |
| Documentation manifest check | Passed |
| `git diff --check` | Passed |

The PostgreSQL run used a dedicated local PostgreSQL 16.15 temporary cluster on port 55493,
not a shared or production database. The cluster was stopped after verification.

## Remaining Boundaries

- Migration 013 and its backfill must run offline after a verified backup; follow
  `docs/releases/v0.7-upgrade.md` before starting upgraded services.
- Legacy claimed occurrences do not have reliable atomic dispatch receipts. Audit them against
  existing Runs before resuming schedules; historical exactly-once recovery is not asserted.
- Registry promotion cannot atomically update both image tags. Deploy the digest pair from a
  successfully completed release rather than observing individual mutable tags.
- GitHub-hosted execution, multi-architecture image scans, signing, registry promotion, live model
  calls, and production-scale performance were not exercised. No frontend code changed, so visual
  browser acceptance was outside this repair scope.
