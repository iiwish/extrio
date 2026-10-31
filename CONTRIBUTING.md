# Contributing to Extrio

Thank you for helping improve Extrio. The project is in its 1.0 release-candidate phase, so please
open an issue before starting a large behavioral or contract change. Questions and early ideas are
welcome in [GitHub Discussions](https://github.com/iiwish/extrio/discussions).

## Good first contributions

- **Source fixtures and compatibility reports** for public or authorized sites, with the expected
  fields and the behavior you observed. Do not submit scraped content you are not allowed to share.
- **Extraction templates** for common notice and announcement layouts.
- **Documentation and translations.** Several design and operations documents exist only in
  Chinese; English versions are especially welcome.
- **Focused fixes** with a regression test.

## Development setup

Prerequisites are Git, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22, the pnpm version
pinned in [web/package.json](web/package.json), and the Chromium headless shell installed through
Playwright.

```bash
uv sync --project backend --locked --python 3.12
uv run --project backend python -m playwright install --with-deps --only-shell chromium
pnpm --dir web install --frozen-lockfile
./scripts/dev.sh
```

The console runs at `http://127.0.0.1:5173` and the API at port `8000`. Stop both with
`./scripts/stop.sh`.

If you are updating an older checkout, run the `uv sync` command again. `uv run` installs missing
packages but does not remove ones the lockfile no longer contains, such as Crawl4AI and NLTK, and
the dependency-boundary tests fail when those are still present.

## Repository layout

```text
backend/             Python / FastAPI control plane, worker, MCP, storage, tests
web/                 React / TypeScript / Vite / Tailwind CSS / shadcn/ui console
docs/contracts/      OpenAPI, JSON Schema, examples, extraction semantics
docs/architecture/   Architecture decisions
docs/assets/         Images used by the README and public guides
docs/reviews/        Review records and desktop QA evidence
docker/              Container definitions
scripts/             Development, verification, and operations utilities
```

The repository keeps one frontend entry and one backend package. Product prototypes are iterations
of the real frontend, not separate sample applications.

## Checks

Run the verification suite before opening a pull request:

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -c backend/pyproject.toml backend/tests
uv run --project backend python scripts/update-docset-manifest.py --check
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
```

- PostgreSQL integration tests need an isolated database in `EXTRIO_TEST_DATABASE_URL`; without
  it they are skipped.
- Installation smoke checks are `bash scripts/verify-source.sh` and `./scripts/verify-compose.sh`
  (requires Docker). They use ports `18100`/`15173` and `18000`/`18080`; override
  `EXTRIO_API_PORT` and `EXTRIO_WEB_PORT` if those are taken.
- After changing [docs/contracts/openapi.yaml](docs/contracts/openapi.yaml), regenerate the
  frontend types with `pnpm --dir web api:generate`.
- Build the backend wheel with `uv build --project backend --wheel`.

## Pull requests

- Keep changes focused and small enough to review, and preserve the existing architecture.
- Use [Conventional Commits](https://www.conventionalcommits.org/) prefixes such as `feat:`,
  `fix:`, `docs:`, and `chore:` in pull request titles.
- Update contracts and generated API types together when the API changes.
- When product or UX scope changes, keep [docs/SSOT.md](docs/SSOT.md),
  [docs/product-contract.md](docs/product-contract.md),
  [docs/frontend-prototype.md](docs/frontend-prototype.md), and
  [docs/releases/v0.2-acceptance.md](docs/releases/v0.2-acceptance.md) aligned.
- Add focused tests for behavior changes. For UI changes, include screenshots at the supported
  desktop viewports (1440×900 primary; 1280×800, 1132×1028, and 1024×800 minimum).
- Do not commit credentials, signing keys, runtime databases, scraped content, or logs.

By submitting a contribution, you agree that it is licensed under Apache-2.0.
