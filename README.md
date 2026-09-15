<div align="center">

# Extrio

**Web data you can trace. Collection rules you control.**

AI-assisted rule creation. Human-reviewed publication. Deterministic execution.

[Website](https://extrio.ouvo.ai) · [Quick Start](#quick-start) · [Documentation](#documentation) · [中文](README.zh-CN.md)

[![CI](https://github.com/iiwish/extrio/actions/workflows/ci.yml/badge.svg)](https://github.com/iiwish/extrio/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: Public Alpha](https://img.shields.io/badge/Status-Public_Alpha-orange.svg)](docs/releases/public-alpha-readiness.md)

</div>

Extrio is a **self-hosted web data collection platform for data operations teams**. Turn public or authorized websites into structured data using reviewable extraction rules, then trace every collected item back to its source, run, and rule version.

Built around tender, regulatory, and public-notice workflows, Extrio helps teams answer more than “did the scraper run?”: **What did we collect, what was rejected, and how was this result produced?**

![Extrio desktop console showing collected data, totals, and pagination](docs/reviews/unified-list-pagination/items-1440.png)

*Local acceptance instance with demonstration data, not a hosted trial. [Explore the console walkthrough](docs/showcase.md).*

> **Public alpha.** The self-hosted workflow is implemented and backed by repository-local tests and review evidence. Arbitrary-site compatibility, production-scale capacity, hardened multi-tenancy, and a production SLA are not claimed. Read the [security policy](SECURITY.md) before deployment.

## Why Extrio

Data operations need more than extracted text. They need repeatable rules, explicit review, and enough evidence to investigate failures without guessing.

| What you need | What Extrio provides |
| --- | --- |
| A shared definition of the data | Reusable collection requirements, field definitions, and versioned output contracts. |
| Less hand-written extraction setup | AI-assisted exploration and candidate rules with sample evidence for review. |
| Control over production changes | Human publication of immutable, signed rules. Repair candidates return to review. |
| Repeatable collection | Manual and scheduled runs execute frozen rules without an LLM at collection time. |
| Results you can investigate | Item lineage, revisions, quality decisions, rejected records, and run evidence. |
| Data usable outside the console | CSV/JSONL export, Webhook delivery, signed evidence bundles, and governed MCP tools. |

**AI proposes; people publish; the worker executes.** Extrio is not a webpage chatbot, a general-purpose crawler toolkit, or an agent that silently rewrites its production rules.

## From Source to Structured Data

1. **Define the requirement.** Describe the collection goal and expected fields so multiple sources can share a data contract.
2. **Add sources.** Enter a source URL or import a URL list with per-URL validation. Configure a model for AI exploration.
3. **Review the rule.** Inspect candidate fields and sample evidence, resolve problems, and explicitly publish an approved version.
4. **Run and monitor.** Collect manually or on a schedule. Inspect outcomes, quality rejections, checkpoints, and collection-scope limits.
5. **Use the results.** Query or export records, deliver them to a Webhook, or retrieve them through MCP with their lineage.

A successful run does not automatically mean complete coverage. Page limits, missing pages, and quality rejections remain part of the result, not details hidden behind a success badge.

<details>
<summary><strong>See requirements and field contracts</strong></summary>

![Collection requirements](docs/reviews/unified-list-pagination/collections-1440.png)

![Requirement fields and output contract](docs/reviews/collection-detail-polish/fields-1440.png)

</details>

The desktop console supports **中文 and English**, with a per-device language setting. Supported viewport widths start at **1024px**; mobile is outside the current scope.

## Quick Start

### Docker Compose

Install Git and Docker with the Compose plugin, then run:

```bash
git clone https://github.com/iiwish/extrio.git
cd extrio
docker compose up --build --wait
```

Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** and create the first administrator account. Passwords require at least 8 characters. The stack includes the console, API, and worker, with persistent state in a named volume. The initial image build installs browser dependencies and may take several minutes.

A local tender source is seeded for evaluation. **Fresh AI rule generation requires a configured model and credentials**; the key-free deterministic smoke test below validates execution, not AI generation.

Stop the stack without deleting your data:

```bash
docker compose down
```

Do not add `-v` unless you intend to delete the database, keys, and artifacts in the volume. If a default port is occupied, choose unused ports with `EXTRIO_API_PORT` and `EXTRIO_WEB_PORT`.

### From Source

Prerequisites: Git, **Python 3.12**, [uv](https://docs.astral.sh/uv/), **Node.js 22**, and the pnpm version pinned in [web/package.json](web/package.json). Run from a clone of this repository:

```bash
uv sync --project backend --locked --python 3.12
uv run --project backend crawl4ai-setup
pnpm --dir web install --frozen-lockfile
./scripts/dev.sh
```

Open **[http://127.0.0.1:5173](http://127.0.0.1:5173)**. The API uses port `8000`, with interactive documentation at `/docs` after login. Stop the local processes with `./scripts/stop.sh`.

For isolated instances, set `EXTRIO_INSTANCE_DIR`, `EXTRIO_API_PORT`, and `EXTRIO_WEB_PORT`; use the same instance directory when stopping. The launcher checks port conflicts and waits for worker readiness.

### Try Collection Without a Model Key

After installing the backend dependencies:

```bash
uv run --project backend python scripts/benchmark.py --collectors 1 --pages 1
```

This executes a hand-written, signed rule through the real worker against a bundled local source in temporary storage. It makes no third-party scraping requests, incurs no model charges, and does not write to your existing instance. It is an execution smoke test, not a compatibility or capacity benchmark.

## Capabilities and Boundaries

| Area | Current scope |
| --- | --- |
| Sources | Constrained HTML/JSON extraction, single-page and list/detail workflows, declared pagination, and bounded browser rendering. Broad real-world compatibility remains experimental. |
| Incremental collection | Checkpoints and controlled time windows for supported date-ordered `next_link` sources, not arbitrary cursors or infinite scrolling. |
| AI assistance | Rule generation and repair, structured task history, attempts, model usage, and one-run guidance. No raw prompts, reasoning, or model response bodies in activity logs. |
| Governance | Local administrator, engineer, reviewer, and viewer roles; human publication, signed attestations, and audit records. No enforced independent two-person approval. |
| Operations | Durable work, schedules, readiness checks, diagnostics, backup/restore, key rotation, and Prometheus metrics. |
| Storage | SQLite WAL for local evaluation; PostgreSQL for self-hosted deployments; shared filesystem artifacts. |
| Evidence | Item/run/rule lineage and signed evidence bundles. Sampled page evidence is not a complete replay engine; evidence ZIPs are not disaster-recovery backups. |

Production login flows, CAPTCHA or access-control bypass, universal website support, SSO/MFA, multi-tenant isolation, and distributed high availability are outside the validated scope. Use only public or explicitly authorized sources and respect their access conditions.

See the [operations guide](docs/self-hosted-operations.md) for exact restrictions and the [roadmap](ROADMAP.md) for direction. The [1.0 scope contract](docs/planning/v1.0-scope-matrix.md) describes a delivery target, not a claim that a stable release has shipped.

## MCP Server

Extrio exposes seven tools for AI clients through `extrio-mcp`:

| Tool | Purpose |
| --- | --- |
| `list_collectors` | List sources, publication state, schedules, and recent outcomes. |
| `get_collector` | Inspect a source, frozen fields, recent runs, and delivery sinks. |
| `create_collection` | Create a governed source and queue AI exploration for human review. |
| `trigger_run` | Queue collection against an already-published, integrity-verified rule. |
| `get_run` | Inspect status, counts, stop reason, integrity checks, and checkpoint. |
| `query_items` | Read filtered, cursor-paginated records. |
| `get_item` | Inspect data, decision evidence, observations, and full lineage. |

**There is no rule-publication tool.** An agent can request exploration, but a human must publish the rule before a collection run can use it.

For trusted local clients, launch from the repository root:

```bash
uv run --project backend extrio-mcp
```

For Streamable HTTP, set a strong secret in `EXTRIO_MCP_TOKEN`, then launch:

```bash
uv run --project backend extrio-mcp --transport http --host 127.0.0.1 --port 8818
```

The endpoint is `http://127.0.0.1:8818/mcp` and requires `Authorization: Bearer <token>`. MCP must use the **same database, artifact directory, and signing/encryption keys** as the API and worker. The HTTP token grants access to all seven tools; it is not a browser user's role-scoped session. Use TLS for remote access. See [API and MCP client guidance](docs/self-hosted-operations.md#api-与-mcp-客户端).

## Self-Hosting Safely

- Keep the API and worker off the public internet; route console traffic through the bundled web proxy and a controlled TLS reverse proxy.
- Set `EXTRIO_AUTH_COOKIE_SECURE=true` behind HTTPS. The local HTTP evaluation profile intentionally defaults to `false`.
- Protect credentials, signing keys, persistent volumes, and outbound network access. Never reuse development keys in production.
- Back up the database, artifacts, and keys together, and test restoration before upgrading.
- Restrict `/metrics` to trusted monitoring access: it is unauthenticated by design. `/healthz` proves API liveness; `/readyz` also checks the worker and deployment/key consistency.

Read [SECURITY.md](SECURITY.md) and the [operations guide](docs/self-hosted-operations.md) before handling sensitive data or exposing an instance beyond localhost.

## Documentation

Several detailed design and operations documents are maintained in Chinese; API contracts and code identifiers are shared across both languages.

| Start here | What you will find |
| --- | --- |
| [Console walkthrough](docs/showcase.md) | A three-minute product tour and local screenshots. |
| [Product definition](docs/SSOT.md) · [Product contract](docs/product-contract.md) | Goals, scope, and behavioral boundaries. |
| [Operations guide](docs/self-hosted-operations.md) | Configuration, PostgreSQL, upgrades, diagnostics, backup/restore, and keys. |
| [Backend architecture](docs/backend-vertical-slice.md) · [Architecture decisions](docs/architecture/) | Runtime responsibilities and design decisions. |
| [API contract](docs/contracts/api-contract.md) · [OpenAPI](docs/contracts/openapi.yaml) | Integration contracts, schemas, and examples. |
| [Rules guide](docs/rules-guide.md) | Extraction rules and their semantics. |
| [Release readiness](docs/releases/public-alpha-readiness.md) · [Roadmap](ROADMAP.md) | Release gates, evidence limits, and future direction. |

## Development and Contribution

The repository maintains one frontend and one backend package:

```text
backend/             Python / FastAPI control plane, worker, MCP, storage, tests
web/                 React / TypeScript / Vite / Tailwind CSS / shadcn/ui console
docs/contracts/      OpenAPI, JSON Schema, examples, extraction semantics
docs/architecture/   Architecture decisions
docs/reviews/        Review records and desktop QA evidence
docker/              Container definitions
scripts/             Development, verification, and operations utilities
```

Run checks from the repository root:

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -c backend/pyproject.toml backend/tests
uv run --project backend python scripts/update-docset-manifest.py --check
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
```

PostgreSQL integration tests require an isolated `EXTRIO_TEST_DATABASE_URL`; otherwise they are skipped. Installation smoke checks are `bash scripts/verify-source.sh` and `./scripts/verify-compose.sh` (requires Docker). They use ports `18100`/`15173` and `18000`/`18080` respectively; override `EXTRIO_API_PORT` and `EXTRIO_WEB_PORT` when needed. Build the backend wheel with `uv build --project backend --wheel`.

Contributions to source fixtures, reproducible bug reports, documentation, translations, and focused fixes are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), and open an [issue](https://github.com/iiwish/extrio/issues) before starting a large behavioral or contract change. Include relevant tests and desktop evidence for UI changes.

For help and project decisions, see [SUPPORT.md](SUPPORT.md) and [GOVERNANCE.md](GOVERNANCE.md). Report vulnerabilities **privately** using [SECURITY.md](SECURITY.md), not in a public issue.

## License

Extrio is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution notices.
