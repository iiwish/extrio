# Changelog

All notable changes to Extrio are documented in this file. The project follows
[Semantic Versioning](https://semver.org/) and keeps pending work under
`Unreleased`.

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
