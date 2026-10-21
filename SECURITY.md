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

Safe production defaults disable automatic migration, anonymous HTTP sources, demo data, and
Prometheus metrics; enable each only through explicit deployment policy. Public deployments
require HTTPS, `EXTRIO_AUTH_COOKIE_SECURE=true`, a restricted listening interface, outbound
network controls, protected persistent volumes, and backups. Authentication can be disabled only
for isolated development and automated test environments with `EXTRIO_AUTH_ENABLED=false`.

Login throttling is stored in the application database so API workers share one limit. Reverse
proxy client identities are ignored unless `EXTRIO_TRUSTED_PROXY_COUNT` explicitly declares the
number of trusted forwarding hops. Browser mutations reject cross-site Fetch Metadata and
untrusted `Origin` values; session cookies remain `SameSite=Strict`.

Prometheus metrics are disabled by default. When explicitly enabled, `/metrics` remains
unauthenticated and must be restricted to a trusted monitoring network or authenticated proxy.

Runtime state under `backend/data`, including generated signing and encryption
keys, is development-only and must never be committed or reused in production.

## Dependency advisory boundary

Browser rendering uses Playwright directly. Crawl4AI and NLTK are not runtime
dependencies; package absence is checked in the frozen lock, installed environment
and isolated image inventory. Historical releases containing NLTK retain their
[GHSA-8mgp-746c-j5xp](https://github.com/nltk/nltk/security/advisories/GHSA-8mgp-746c-j5xp)
advisory and exact-release evidence. Dependency removal does not repair upstream
NLTK or update an existing installation. Do not add arbitrary model-artifact
loading or untrusted Python execution without reassessing this boundary.

Browser requests use the same host, DNS/IP, robots, redirect, rate and budget
guard as HTTP collection. Chromium has a deny-only proxy, request interception,
blocked service workers and WebSockets, and disabled downloads. These controls
require regression evidence; Playwright alone is not an outbound sandbox.
Complete scans include unfixed findings, and unhandled HIGH/CRITICAL findings
block the candidate. Green CI is not production or release authorization.

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's GitHub
Security Advisory page. Include affected versions, reproduction steps, impact,
and any suggested mitigation. Do not open a public issue for an unpatched
vulnerability.

We will acknowledge a complete report as soon as practical and coordinate a
fix and disclosure timeline with the reporter.
