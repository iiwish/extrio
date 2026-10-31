# Roadmap

The roadmap communicates direction, not a delivery promise. Accepted work is tracked through
issues and release milestones.

## Current release: v1.0.0-rc.3

[v1.0.0-rc.3](docs/releases/v1.0-rc.3.md) is a published prerelease from
`4f3929202d65601ced4ace3656eb726c64287459`. Stable `v1.0.0` remains unpublished and
`Needs_Review`; see the [stable acceptance handoff](docs/releases/v1.0.0.md).
Its scope includes
bounded-recovery and source-creation reliability fixes, bounded catalog validation, and three
offline extraction-template packs. Exact-source CI, native dual-architecture verification,
published-artifact security and signature/provenance checks, and isolated SQLite/PostgreSQL 16
installation of the published digests passed. Digest installation was on `linux/arm64`, separate
from the native dual-architecture tests. Existing instances are not upgraded; production deployment
and source schedules are not authorized.

- Self-hosted data-operations workflow for public and authorized list/detail sources.
- Constrained AI rule generation and repair with one-run operator guidance.
- Live, refresh-safe structured AI activity instead of raw prompts or reasoning logs.
- Human rule review, immutable attestation, deterministic scheduled runs, checkpoints, quality
  evidence, item lineage, Webhook delivery, and governed MCP access.
- Local multi-user roles, Docker Compose evaluation, and signed release artifacts.

## Stable acceptance priorities

**Proposal, pending maintainer review.** The [stable gate proposal](docs/releases/v1.0.0.md#稳定版剩余门槛重定义提案)
limits `v1.0.0` to software commitments. Until the product and technical owners approve it, the
current gates in the handoff still apply.

Proposed stable gates:

- Compatibility commitment for `/api/v1`, the database schema, and GatherSpec `extrio.gather.v1`.
  1.x only adds backward-compatible changes; breaking changes need a new major version with a
  migration, compatibility window, and rollback path.
- Verified upgrade, full backup, empty-target restore, and matched-code rollback on SQLite and
  PostgreSQL 16 for the exact candidate.
- Supported deployment matrix: single-organization self-hosting, SQLite for evaluation only,
  PostgreSQL 16, `linux/amd64` and `linux/arm64` images, desktop browsers at 1024px and wider.
- Candidate artifacts with required CI passing on the exact SHA, no unresolved HIGH/CRITICAL
  findings, signed images with provenance, and isolated installation of the published digests.
  RC3 results are limited to its exact source and digests and are not reused for a stable candidate.
- Final product and technical sign-off remains the release authorization.

Moved out of the release gate under the proposal:

- Source coverage goes to the continuously updated [source support matrix](docs/source-support-matrix.md).
  The procurement site's first historical window and real incremental coverage remain incomplete,
  106 quality items stay excluded, and the 1480-source directory and 1364-entry catalog matrix are
  not compatibility claims.
- Target-user acceptance moves to the design-partner programme under Product validation.
- The 72-hour observation and SLA move to Production hardening. Existing observation waivers are
  not evidence of a long-running SLA.

Other priorities that do not gate the release: [user review of the RC3 reliability fixes](docs/reviews/p2-reliability-20261022/verification.md),
and, after design confirmation, requirement-scoped data, version-bound sample evidence, and
partial-failure workflows on the existing frontend and backend contracts.

## Product validation

These items turn repository evidence into evidence that prospective users can inspect. They are not
claims about the current release.

- Consider a separately authorized hosted evaluation environment after the self-hosted workflow is validated.
- Build a curated corpus of representative tender, regulatory, and public-notice sources with declared
  support boundaries and repeatable success criteria.
- Run a design-partner programme for independent target-user acceptance, from installation to first
  data delivery without assistance.
- Measure first-valid-sample time, no-code publication rate, rule durability, and recovery time with
  external design partners.
- Publish reproducible compatibility and performance results rather than capacity promises.

## Adoption and ecosystem

- Guided source diagnostics and clearer recovery actions for the most common onboarding failures.
- Reviewed rule templates and examples for the initial source categories.
- Stable API clients, MCP examples, and extension documentation for downstream automation.
- Contribution paths for source fixtures, templates, and compatibility reports.

## Production hardening

- Supported database migration, backup/restore, key rotation, and artifact retention controls.
- External OIDC, tenant isolation, step-up authentication, and managed secret integrations.
- Distributed queues, object storage, additional delivery sinks, and high-availability scheduling.
- Production SLO evidence, long-running observation (including the waived 72-hour run), and capacity
  limits backed by published benchmarks.
