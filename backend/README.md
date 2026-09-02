# Extrio backend

The backend package exposes two processes with separate responsibilities:

- `extrio-api` is the FastAPI control plane and the browser-facing writer.
- `extrio-worker` explores sources, compiles constrained rules, verifies fixed
  attestations, and performs deterministic collection runs.

The local profile uses SQLite WAL, filesystem artifacts, and development-only
Ed25519 and credential-encryption keys. The API and worker must share the same
database and artifact paths.

## Development

From the repository root:

```bash
uv sync --project backend --locked --python 3.12
uv run --project backend crawl4ai-setup
uv run --project backend extrio-api
uv run --project backend extrio-worker
```

Run verification with:

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest
```

## Packaging

Build the Python wheel with `uv build --project backend --wheel`. The wheel
contains the versioned contract bundle required by both processes. The primary
deployment artifact is the OCI image in `docker/backend.Dockerfile`; Compose
starts the same image once as the API and once as the worker.

The current package is a local alpha with first-run local administrator
authentication only. It is not a hardened multi-tenant service: keep the API
and worker behind the bundled web proxy and review [SECURITY.md](../SECURITY.md)
before deployment. Do not bind it to an untrusted network without outbound
network controls, production secrets, and a production persistence profile.
