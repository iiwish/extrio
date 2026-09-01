# Contributing to Extrio

Thank you for helping improve Extrio. The project is currently a local alpha,
so open an issue before starting a large behavioral or contract change.

## Development setup

Prerequisites are Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22,
pnpm, and Chromium installed through Crawl4AI.

```bash
uv sync --project backend --locked --python 3.12
uv run --project backend crawl4ai-setup
pnpm --dir web install --frozen-lockfile
./scripts/dev.sh
```

Run the verification suite before opening a pull request:

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest
uv run --project backend python scripts/update-docset-manifest.py --check
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
```

## Pull requests

- Keep changes focused and preserve the repository's existing architecture.
- Update contracts and generated API types together when the API changes.
- Update the authoritative documents when product or UX scope changes.
- Add focused tests for behavior changes and include desktop QA evidence for UI changes.
- Do not commit credentials, signing keys, runtime databases, scraped content, or logs.

By submitting a contribution, you agree that it is licensed under Apache-2.0.
