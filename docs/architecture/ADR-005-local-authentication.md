# ADR-005: Local administrator authentication

## Status

Accepted for the `v0.2` public alpha.

## Context

Extrio is a single-instance, self-hosted operations console. The public alpha needs a real
authentication boundary without coupling the existing SQLite control plane to an ORM or
shipping public registration, password reset, and multi-tenant membership workflows that the
product does not yet support.

## Decision

Extrio provides a first-run administrator setup and local username/password login.

- Passwords are hashed with Argon2 through `pwdlib`; application code never implements a
  password primitive.
- Browser sessions use 256-bit opaque random tokens. Only SHA-256 token digests are stored in
  SQLite, so logout and server-side revocation take effect immediately.
- The session cookie is `HttpOnly`, `SameSite=Strict`, path-scoped to `/`, and `Secure` when
  `EXTRIO_AUTH_COOKIE_SECURE=true`.
- Login attempts are rate-limited through `limits`. Failed authentication uses one generic
  response and performs password verification even when the username does not exist.
- Setup closes atomically after the first administrator is created. Extrio exposes no public
  registration route.
- `/healthz`, the first-run authentication endpoints, and optional demo source pages are public.
  Control-plane APIs, bundled contracts, and API documentation require an authenticated session.
- The authenticated user ID is propagated into rule publication audit events.

`FastAPI Users` was evaluated. Its adapters, user manager, schema, and route model are valuable
for applications that already use a supported database adapter and need registration or account
management. For Extrio's one-administrator SQLite boundary it would introduce a parallel data
layer and unused account flows.

`Authlib` remains the preferred integration point for a future external OAuth 2.0/OIDC provider.
It is not used for local password verification or session persistence.

## Consequences

- An operator must create the first administrator before using a new installation.
- The public alpha supports one local administrator role, not self-service users, password
  recovery, SSO, MFA, or tenant memberships.
- TLS deployments must enable secure cookies and terminate HTTPS before traffic reaches the web
  container.
- Database backup and restore includes user and active-session records. Operators can revoke all
  sessions by deleting rows from `auth_sessions` while the service is stopped.

## Verification

Automated tests cover setup exclusivity, Argon2 password storage, protected routes, login,
generic invalid-credential errors, rate limiting, logout revocation, and cookie attributes.
Docker end-to-end verification proves that the reverse-proxied browser flow is protected.
