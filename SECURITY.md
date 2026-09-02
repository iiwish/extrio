# Security policy

## Supported versions

Extrio is a public-alpha release candidate. Security fixes are applied to the latest commit on the
default branch; no older release line is supported yet.

## Deployment boundary

Extrio requires first-run local administrator setup and uses Argon2 password hashes with
server-side revocable browser sessions. It does not yet provide password recovery, MFA, external
OIDC, multiple users, role administration, or tenant isolation. Do not expose the API or worker
directly to the public internet; route browser traffic through the bundled web proxy.

Public deployments require HTTPS, `EXTRIO_AUTH_COOKIE_SECURE=true`, a restricted listening
interface, outbound network controls, protected persistent volumes, and backups. Authentication
can be disabled only for isolated development and automated test environments with
`EXTRIO_AUTH_ENABLED=false`.

Runtime state under `backend/data`, including generated signing and encryption
keys, is development-only and must never be committed or reused in production.

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's GitHub
Security Advisory page. Include affected versions, reproduction steps, impact,
and any suggested mitigation. Do not open a public issue for an unpatched
vulnerability.

We will acknowledge a complete report as soon as practical and coordinate a
fix and disclosure timeline with the reporter.
