# Security policy

## Supported versions

Extrio is a local alpha. Security fixes are applied to the latest commit on the
default branch; no older release line is supported yet.

## Deployment boundary

The current backend does not enforce user authentication and is intended for a
trusted local machine or an isolated development network. Do not expose the API
or worker directly to the public internet. Review source allowlists, outbound
network policy, credential storage, and persistence before production use.

Runtime state under `backend/data`, including generated signing and encryption
keys, is development-only and must never be committed or reused in production.

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's GitHub
Security Advisory page. Include affected versions, reproduction steps, impact,
and any suggested mitigation. Do not open a public issue for an unpatched
vulnerability.

We will acknowledge a complete report as soon as practical and coordinate a
fix and disclosure timeline with the reporter.
