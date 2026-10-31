# Changelog

All notable changes to Extrio are documented in this file. The project follows
[Semantic Versioning](https://semver.org/) and keeps pending work under
`Unreleased`.

## Unreleased

Stable `v1.0.0` remains unpublished and `Needs_Review`; see the
[stable handoff](docs/releases/v1.0.0.md).

### Security

- Update `filelock` to 4.2.1 and `pypdf` to 6.21.2 to address HIGH findings
  (CVE-2026-112940; CVE-2026-115572, CVE-2026-115580, CVE-2026-115585) reported for
  rebuilt images after RC3 was published. The published RC3 images still contain the
  affected versions.

### Documentation

- Record the published RC3 artifact verification and its public receipts.
- Rewrite the English and Chinese READMEs around the review-then-run workflow, a
  comparison with other approaches, and a concise project status. Move development
  details into CONTRIBUTING and README screenshots into `docs/assets/screenshots/`.
- Replace outdated alpha and Crawl4AI references in CONTRIBUTING, SUPPORT, SECURITY,
  the console walkthrough, the backend README, and the rules guide.

## 1.0.0-rc.3 - 2026-10-23

Published prerelease: [v1.0.0-rc.3](https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.3),
commit `4f3929202d65601ced4ace3656eb726c64287459`. Python `1.0.0rc3`, Web `1.0.0-rc.3`;
the database stays at schema 014 and the API contract is unchanged. See the
[release record](docs/releases/v1.0-rc.3.md) for verification and known limitations.

- When a bounded-recovery batch is rejected at start because its signature check fails,
  finish that batch and continue with the remaining batches
  ([#50](https://github.com/iiwish/extrio/pull/50)).
- Retry source creation idempotently when the response is lost
  ([#50](https://github.com/iiwish/extrio/pull/50)).
- Link from a run to the complete list of its rejected records
  ([#50](https://github.com/iiwish/extrio/pull/50)).
- Add bounded, isolated validation for CSV source catalogs with a traceable result matrix,
  plus three offline extraction-template packs. Readable catalog samples are not production
  rules or compatibility claims ([#51](https://github.com/iiwish/extrio/pull/51)).

## 1.0.0-rc.2 - 2026-10-21

Published prerelease: [v1.0.0-rc.2](https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.2),
commit `cd60804a60aaa7bbbcbd4a07ec7a3738b0699c75`. Python `1.0.0rc2`, Web `1.0.0-rc.2`,
database schema 014. See the [release record](docs/releases/v1.0-rc.2.md).

- Render pages with a restricted browser built directly on Playwright 1.62 instead of
  Crawl4AI. Crawl4AI, NLTK, and 51 other packages leave the lockfile; no other locked
  versions change ([#49](https://github.com/iiwish/extrio/pull/49)).
- Keep the browser behind the existing network guard (anonymous GET, robots, DNS/IP
  pinning, redirects, rate and request budgets), and block WebSockets, service workers,
  and downloads.
- Build the default backend image on digest-pinned Ubuntu 24.04 LTS with the Playwright
  headless shell and the PGDG PostgreSQL 16 client.
- Ship six-source tender collection with field evidence, original text, PDF and EPS
  handling, separate coverage and quality checkpoints, and bounded cooldown recovery
  (migration 014).
- Stop filtering unfixed HIGH and CRITICAL findings out of the container and release
  scans.
- Add the published RC1 commit to the SQLite/PostgreSQL upgrade and full-backup
  restore/rollback matrix, and verify published images by immutable digest without
  rebuilding them ([#34](https://github.com/iiwish/extrio/pull/34)).

## 1.0.0-rc.1 - 2026-09-27

Published prerelease: [v1.0.0-rc.1](https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.1),
commit `c2fc06f420c31aaf5bbbea53332ef4af2b48804e`. Exact-commit main CI and
dual-architecture scans, signatures and provenance passed; see the
[release record](docs/releases/v1.0-rc.1.md). This is not a stable release.

- Prepare matching Python `1.0.0rc1` and Web `1.0.0-rc.1` candidate versions.
- Verify the published `v0.7.0-alpha.1` upgrade and full-backup rollback on SQLite
  and PostgreSQL 16, including frozen field bindings, signatures and historical Deliveries.
- Serialize PostgreSQL login-limit checks across API connections and disable implicit
  server proxy rewriting so trusted-hop configuration is the sole client-identity policy.
- Refresh the Web runtime security packages for release builds rather than reusing a
  stale upgrade layer.
- Add isolated stdin-only real-model verification and current desktop acceptance flows,
  with bounded DeepSeek evidence and no automatic publication of real-source candidates.
- Localize the system's missing publication-time placeholder in source, run and data
  views without changing original content or exported data.

- Unify operational lists with a shared scroll region, totals, page size and numbered pagination.
- Refine requirement, source, run, AI task and item details, plus creation and settings workflows.
- Pin the repository-root pytest configuration and refresh public-alpha demonstration materials.
- Report the resolved database target in the worker startup log instead of the SQLite
  fallback path, which misreported PostgreSQL deployments.
- Split the global stylesheet into ordered partials so `web/src/index.css` is a
  documented manifest; emitted CSS is byte-for-byte unchanged.
- Give every ItemEvent and SinkVersion one deterministic logical Delivery, including
  a versioned uniqueness migration and schema-compatible `sha256:` delivery IDs.
- Align the FastAPI service metadata with the frozen OpenAPI contract version and add
  contract-drift checks.
- Consolidate SSOT and product-contract ownership so scope, product policy, and UX rules
  have one canonical home.
- Add explicit v0.7 backup, migration, verification, and restore-based rollback guidance.
- Make production defaults fail closed for automatic migration, anonymous HTTP, demo data,
  secure cookies, and Prometheus metrics while keeping local development profiles explicit.
- Persist login throttling in the shared database, add trusted-proxy controls, and reject
  cross-site Fetch Metadata and untrusted mutation origins.

- Add live, refresh-safe structured activity for AI rule generation and repair, with stages,
  timings, non-sensitive metrics, and a direct link from the active Collector workflow.
- Add optional one-run operator guidance for rule generation and repair. Guidance is treated as
  untrusted input to the constrained compiler and does not weaken validation or human review.
- Clarify Extrio's initial data-operations positioning, current evidence level, experimental
  boundaries, and validation roadmap without claiming hosted or large-scale proof.

## 0.7.0-alpha.1 - 2026-09-15

Published prerelease: [v0.7.0-alpha.1](https://github.com/iiwish/extrio/releases/tag/v0.7.0-alpha.1),
commit `1e02dbbddd273bda7a7023b8824d0bb58f3db5d6`. See the
[v0.7 upgrade guide](docs/releases/v0.7-upgrade.md).

- Add a digest-only Compose deployment profile with resource limits, loopback ingress, and
  separate migration and runtime database credentials
  ([#21](https://github.com/iiwish/extrio/pull/21)).
- Support explicit PostgreSQL environment configuration and schema validation without
  runtime DDL.
- Mark prerelease tags as GitHub prereleases and align package versions.
- Install Chromium before backend tests, patch `js-yaml` and `qs`, and run the required
  Compose check on every pull request ([#19](https://github.com/iiwish/extrio/pull/19),
  [#20](https://github.com/iiwish/extrio/pull/20)).

## 0.6.0 - 2026-09-03

- Allow anonymous `http://` collection sources by default and make the policy
  a first-class setting: administrators can toggle 「允许匿名 HTTP 来源」 in
  Settings → 采集策略 (stored per instance, audited with updater and time).
  The deprecated `EXTRIO_ALLOW_HTTP_PUBLIC` environment variable no longer
  controls runtime behavior. Credential-bearing sources still require HTTPS.

## 0.5.0 - 2026-09-03

- Add AI rule auto-repair: re-explore a changed site, compile a corrected rule
  from the old GatherSpec plus fresh DOM, force-preserve the frozen data
  contract server-side, and route the repaired candidate through the existing
  human review flow (`REPAIR_VALIDATION_FAILED` / `REPAIR_NOT_APPLICABLE`
  stable error codes).
- Add signed evidence-bundle export: a deterministic, Ed25519-signed ZIP with
  the collector, immutable rules, attestations, runs, item lineage, deliveries,
  and SHA256SUMS — with hard guards against secret leakage and a verification
  helper (`verify_evidence_bundle`).
- Add a governed MCP server (`extrio-mcp`): AI agents can list collectors,
  query attested items, trigger runs against frozen rules, and create
  collections that require human review; stdio and token-protected HTTP
  transports.
- Add an Ollama provider preset for local model setups.

## 0.4.0 - 2026-09-03

- Add multi-user local accounts with role-based access control: administrator
  (full permissions plus user management), engineer (collector, exploration,
  run, schedule, and sink operations), reviewer (rule review and publication),
  and viewer (read-only access with export). First-run setup still creates the
  administrator; accounts use Argon2 password hashing.
- Enforce the role matrix on the control plane: rule publication requires
  reviewer or above; collector, run, sink, and schedule writes require engineer
  or above; user management and model settings require administrator; all reads
  are available to every authenticated role.
- Add user management API and console UI for creating, updating, and disabling
  local accounts and their roles.
- Add a Prometheus `/metrics` endpoint (no extra dependencies, scrape-time
  counts) covering collectors, runs (24h and total), items, deliveries, and
  sinks by status, plus build info. Controlled by `EXTRIO_METRICS_ENABLED`
  (default `true`), unauthenticated by design and intended for an
  internally-bound scrape target.
- Protect scheduled collection: a schedule that records three consecutive
  failed runs is paused automatically and stays paused until it is resumed
  manually.
- Add an offline benchmark harness (`scripts/benchmark.py`) and benchmark
  methodology and baseline results documentation (`docs/benchmarks.md`) for the
  deterministic local demo source.

## 0.3.0 - 2026-09-03

- Add the data output loop: per-collector Webhook sinks with HMAC-SHA256
  signing, exponential-backoff retries, dead-letter handling, manual redelivery,
  and n8n-friendly flat payloads.
- Add CSV/JSONL export with URL-synced filters and cursor-paginated items API.
- Add PostgreSQL as a first-class production storage backend with dialect-aware
  SQL, versioned schema migrations, backup/restore CLI, and a compose PG profile
  (SQLite remains the zero-config development profile).
- Ship demo seed data by default on fresh installations and document the
  GatherSpec rule format with an authoring guide, RE2 `regex_extract`
  transforms, and rule field labels.

## 0.2.0 - 2026-09-02

- Add bilingual console support (Chinese/English): i18next-based localization
  across all pages, a settings interface-language switcher persisted per device,
  and localized API fallback messages.
- Add file import for collector entry URLs to batch-create collectors from a
  newline/comma/semicolon-separated URL list with dedup and merge feedback.
- Add durable AI rule-task history with attempts, model usage metadata, review
  status, migration backfill, and unified collection/AI run workspaces.
- Set the first-run administrator password minimum to eight characters.
- Add first-run administrator setup, Argon2 password storage, revocable cookie
  sessions, login throttling, and authenticated control-plane access.
- Add reproducible source, wheel, and authenticated Docker Compose verification
  paths, with backend dependency and browser layers cached independently from
  application source changes.
- Add multi-architecture GHCR publishing with SBOM and provenance attestations,
  Trivy release gates, and keyless image signing.
- Add Apache-2.0 licensing, contribution, support, governance, security, roadmap,
  maintainer, and public-readiness guidance.
