# Extrio Web

Extrio Web is the desktop operations console for collector definition, rule
review, runs, data lineage, model settings, and operational dashboards. It uses
the versioned API contract in `docs/contracts/openapi.yaml`; MSW is limited to
tests and local fixtures.

## Development

```bash
pnpm install --frozen-lockfile
pnpm dev
```

The default URL is `http://127.0.0.1:5173`. Vite proxies `/api` and `/healthz`
to the local backend.

## Verification

```bash
pnpm test
pnpm lint
pnpm build
```

Generate API types after changing the OpenAPI contract with
`pnpm api:generate`.
