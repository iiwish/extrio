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
uv run --project backend python -m playwright install --with-deps --only-shell chromium
uv run --project backend extrio-api
uv run --project backend extrio-worker
```

Run verification with:

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -c backend/pyproject.toml backend/tests
```

## Packaging

Build the Python wheel with `uv build --project backend --wheel`. The wheel
contains the versioned contract bundle required by both processes. The primary
deployment artifact is the OCI image in `docker/backend.Dockerfile`; Compose
starts the same image once as the API and once as the worker.

The default Linux image uses digest-pinned Ubuntu 24.04 LTS, the Ubuntu-maintained
Python 3.12 security packages, Playwright headless-shell and the official PGDG
PostgreSQL 16 client. It retains LLVM/GBM and excludes full Chromium, CUPS and
Python development tools. Container user-space libraries belong to this image;
Docker still depends on its host or VM kernel. Changing the base image does not
upgrade the host OS or migrate an existing database. Browser rendering uses the
direct Playwright SDK; Crawl4AI and NLTK are not runtime dependencies. Full scan
findings and exact-build evidence are tracked in the RC2 security review.

The current package is a self-hosted 1.0 release candidate with first-run administrator
setup, local users, and role-based access control. It is not a hardened
multi-tenant service: keep the API and worker behind the bundled web proxy and
review [SECURITY.md](../SECURITY.md) before deployment. Do not bind it to an
untrusted network without outbound network controls, production secrets, and a
production persistence profile.
