# Roadmap

The roadmap communicates direction, not a delivery promise. Accepted work is tracked through
issues and release milestones.

## Candidate: v1.0.0-rc.3

[v1.0.0-rc.2](docs/releases/v1.0-rc.2.md) is a published prerelease from
`cd60804a60aaa7bbbcbd4a07ec7a3738b0699c75`. Stable `v1.0.0` remains unpublished and
`Needs_Review`; see the [stable acceptance handoff](docs/releases/v1.0.0.md).
[v1.0.0-rc.3](docs/releases/v1.0-rc.3.md) is in preparation and is not published. Its scope includes
bounded-recovery and source-creation reliability fixes, bounded catalog validation, and three
offline extraction-template packs. Publication is authorized only after the candidate's existing
checks and artifact gates pass. Existing instances are not upgraded; production deployment and
source schedules are not authorized.

- Self-hosted data-operations workflow for public and authorized list/detail sources.
- Constrained AI rule generation and repair with one-run operator guidance.
- Live, refresh-safe structured AI activity instead of raw prompts or reasoning logs.
- Human rule review, immutable attestation, deterministic scheduled runs, checkpoints, quality
  evidence, item lineage, Webhook delivery, and governed MCP access.
- Local multi-user roles, Docker Compose evaluation, and signed release artifacts.

## Stable acceptance priorities

- Bounded-recovery dispatch rejection handling and uncertain-result source-creation retries have
  completed source fixes and engineering verification, including failing regression controls,
  SQLite/PostgreSQL coverage, and desktop journeys. [User review remains pending](docs/reviews/p2-reliability-20261022/verification.md);
  these fixes are included in the unpublished RC3 candidate, not the published RC2 artifacts.
- Keep release status, source commits, and frozen evidence consistent; independently verify each
  changed candidate rather than reusing the RC2 result. RC3 requires its own dual-architecture
  artifact assessment, signature/provenance checks, and published-digest installation results.
- Define the six-source support matrix and quality exclusions. The procurement site's first
  historical window and real incremental coverage remain incomplete; the 1480-source directory
  is not a compatibility claim. Any further source experiment needs a bounded, authorized plan.
- Keep the 1364-entry bounded catalog matrix separate from production support. Its 68 readable
  samples and three template packs do not establish production rules, historical completeness,
  true incremental coverage, or long-term site compatibility.
- Complete independent target-user acceptance before a stable-release decision. Existing
  observation waivers are not evidence of a long-running SLA.
- After design confirmation, prioritize requirement-scoped data, version-bound sample evidence,
  and partial-failure workflows using the existing frontend and backend contracts.

## Product validation

These items turn repository evidence into evidence that prospective users can inspect. They are not
claims about the current release.

- Consider a separately authorized hosted evaluation environment after the self-hosted workflow is validated.
- Build a curated corpus of representative tender, regulatory, and public-notice sources with declared
  support boundaries and repeatable success criteria.
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
- Production SLO evidence and capacity limits backed by published benchmarks.
