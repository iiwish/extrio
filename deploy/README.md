# Maco Alpha Deployment

The Alpha runs as Compose project `extrio-test` on maco. It uses the registered
`pg-main` PostgreSQL 17 instance, database `extrio_test`, and separate runtime
and migration roles. No Redis dependency or bundled database is required.

## Release Inputs

- `maco.json` declares ownership, persistence, and the connection budget.
- `compose.maco.yaml` requires immutable `EXTRIO_BACKEND_IMAGE` and
  `EXTRIO_WEB_IMAGE` digests from a successful signed release workflow.
- Root-only `postgres.env` and `postgres-migration.env` are provisioned by the
  maco platform helper under `/opt/maco-ops/secrets/extrio/test/`.
- The registered release directory is `/opt/maco-ops/apps/extrio/test/`.
- Persistent files live in `/opt/maco-apps/extrio/test/data/`, owned by UID/GID
  10001. Preserve artifacts and keys together with database backups.

Docker Compose injects the five `PG*` variables from the appropriate credential
file. `EXTRIO_DATABASE_FROM_PG_ENV=true` constructs an escaped connection URL in
memory and rejects incomplete credentials rather than falling back to SQLite.
API and worker use `EXTRIO_DATABASE_AUTO_MIGRATE=false` and refuse missing or
incompatible schemas. The explicit migration job owns schema changes.

## Deployment Order

1. Require a fresh successful maco platform inspection, including verified COS
   backup, capacity, and allocation checks. Do not bypass a failed gate.
2. Prepare declared bind paths and release inputs. Render Compose with
   `config --format json` into a mode-600 temporary file.
   Run the registered preflight with `--check-host-paths`. Never print resolved
   Compose JSON because it contains credentials.
3. Pull the verified digests. Run `docker compose run
   --rm --no-deps migrate` using the exact gated inputs.
4. Start `api worker web` with `up -d --wait`, verify readiness and runtime
   database privileges, then initialize the administrator through the private
   connection. Passwords must have at least eight characters.
5. Record commit, digests, backup reference, schema, health/auth checks and
   rollback decision in the server release record. Remove the resolved secret
   artifact, not the persistent data.

Only the web proxy publishes `127.0.0.1:18085`; the API has no host port.
Access uses `ssh -N -L 18085:127.0.0.1:18085 iiwish@maco`, then
`http://127.0.0.1:18085`. HTTP cookies are limited to this loopback/tunnel profile.
Public ingress requires a separately authorized HTTPS/authentication setup.

For the first release, rollback stops only `extrio-test` services and preserves
the database and files. Later rollback requires a recorded schema-compatible
image pair. Never restore the shared PostgreSQL instance or delete its volumes.

## Alpha Boundaries

The release is a prerelease, not a stable-production certification. The user
waived the 72-hour observation period; this is not a passed soak test. The
unpatched, scoped NLTK advisory remains documented in `SECURITY.md`. No local
development data, model credentials, or accounts are copied automatically.
