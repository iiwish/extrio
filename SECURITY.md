# Security policy

## Supported versions

Extrio is a self-hosted public alpha. Security fixes are applied to the latest commit on the default
branch; no older release line is supported yet.

## Deployment boundary

Extrio requires first-run local administrator setup and uses Argon2 password hashes with
server-side revocable browser sessions. It provides local users and administrator-managed roles,
but does not yet provide password recovery, MFA, external OIDC, or tenant isolation. Do not expose
the API or worker directly to the public internet; route browser traffic through the bundled web
proxy.

Public deployments require HTTPS, `EXTRIO_AUTH_COOKIE_SECURE=true`, a restricted listening
interface, outbound network controls, protected persistent volumes, and backups. Authentication
can be disabled only for isolated development and automated test environments with
`EXTRIO_AUTH_ENABLED=false`.

Runtime state under `backend/data`, including generated signing and encryption
keys, is development-only and must never be committed or reused in production.

## Dependency advisory boundary

As of 2026-09-15, the transitive Crawl4AI dependency NLTK 3.10.3 has an unpatched
model-artifact path containment advisory, [GHSA-8mgp-746c-j5xp](https://github.com/nltk/nltk/security/advisories/GHSA-8mgp-746c-j5xp).
The affected APIs import or export parser/tagger models using caller-controlled
filesystem paths. Extrio does not expose these APIs or accept NLTK model paths;
its source code has no direct NLTK calls. The installed Crawl4AI integration uses
tokenization and fixed `punkt` resource lookup, not the affected model persistence
APIs. This is a scoped exposure assessment, not a dependency fix or a claim that
the package is vulnerability-free. Do not add arbitrary model-artifact loading or
untrusted Python execution without reassessing this boundary. The upstream alert
remains open until a patched dependency is available.

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's GitHub
Security Advisory page. Include affected versions, reproduction steps, impact,
and any suggested mitigation. Do not open a public issue for an unpatched
vulnerability.

We will acknowledge a complete report as soon as practical and coordinate a
fix and disclosure timeline with the reporter.
