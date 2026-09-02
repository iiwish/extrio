# Governance

Extrio is maintained in the open under the Apache License 2.0. Technical decisions favor a
reviewable collection pipeline, stable contracts, operational clarity, and secure self-hosting.

## Roles

- **Contributors** propose issues, documentation, tests, and code through pull requests.
- **Maintainers** review changes, manage releases, triage security reports, and protect the
  project's product and compatibility contracts.

The current maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md). Maintainers are added or
removed through a reviewed pull request with existing-maintainer consensus.

## Decisions

Routine changes require one approving maintainer and passing required checks. Architecture,
security boundaries, contract-breaking changes, and governance changes require an ADR or an
equivalent written proposal and explicit maintainer consensus. Unresolved decisions remain open
for at least five business days when practical so contributors can respond.

Maintainers may merge urgent security fixes through an abbreviated private review. The rationale
and non-sensitive follow-up are published after users have a reasonable upgrade window.

## Releases

Version tags are created from `main` after source, contract, container, vulnerability, and release
readiness checks pass. GitHub Actions publishes signed multi-architecture images with provenance
and SBOM attestations. Release notes identify breaking changes, migrations, and known limitations.

## Conduct and security

Participation follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Vulnerabilities follow the private
process in [SECURITY.md](SECURITY.md), not public issue triage.
