<div align="center">

# Extrio

**让网页数据有据可查，让采集规则尽在掌握。**

AI 辅助生成规则 · 人工审核发布 · 确定性执行

[官网](https://extrio.ouvo.ai) · [快速开始](#快速开始) · [文档导航](#文档导航) · [English](README.md)

[![CI](https://github.com/iiwish/extrio/actions/workflows/ci.yml/badge.svg)](https://github.com/iiwish/extrio/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: Public Alpha](https://img.shields.io/badge/Status-Public_Alpha-orange.svg)](docs/releases/public-alpha-readiness.md)

</div>

Extrio 是面向数据运营团队的**自托管网页数据采集平台**。它将公开或已获授权的网站转化为结构化数据：通过可审核的提取规则持续采集，并将每条记录追溯到对应的来源、运行和规则版本。

围绕招投标、监管信息和公共公告等场景，Extrio 不只回答「爬虫有没有跑完」，更帮助团队说清楚：**采集到了什么、哪些数据被拒绝，以及这条结果是如何产生的。**

![Extrio 桌面控制台：采集数据、记录总数与分页](docs/reviews/unified-list-pagination/items-1440.png)

*截图来自使用演示数据的本地验收实例，不代表在线试用服务。[查看控制台导览](docs/showcase.md)。*

> **公开 Alpha 阶段。** 自托管工作流已实现，并有仓库内测试与评审证据支持；不承诺任意网站兼容、生产级处理规模、多租户安全隔离或生产 SLA。部署前请阅读[安全政策](SECURITY.md)。

## 为什么选择 Extrio

数据采集的价值不止于拿到文本。团队还需要可重复执行的规则、明确的审核流程，以及足以定位问题的证据。

| 你的需要 | Extrio 提供的能力 |
| --- | --- |
| 统一定义要采集的数据 | 可复用的采集需求、字段定义和版本化输出合同。 |
| 减少手写提取规则的工作 | AI 辅助探索来源，生成附带样本证据的候选规则，供人工审核。 |
| 掌握生产规则的变更 | 人工发布不可变的签名规则；修复候选也必须重新进入审核。 |
| 可重复的采集过程 | 手动或定时运行已冻结规则，采集运行时不调用 LLM。 |
| 能够调查和解释结果 | 数据谱系、修订记录、质量判定、拒绝记录与运行证据。 |
| 在控制台之外使用数据 | CSV/JSONL 导出、Webhook 投递、签名证据包与受治理的 MCP 工具。 |

**AI 提议，人来发布，Worker 执行。** Extrio 不是网页聊天机器人、通用爬虫工具箱，也不是会静默改写生产规则的自主 Agent。

## 从来源到结构化数据

1. **定义需求。** 描述采集目标与预期字段，让多个来源遵循同一份数据合同。
2. **添加来源。** 输入来源 URL，或导入 URL 列表并逐条校验。配置模型后可发起 AI 探索。
3. **审核规则。** 检查候选字段和样本证据，处理问题，再明确发布批准的版本。
4. **运行与监控。** 手动采集或设置计划，检查运行结果、质量拒绝、检查点及采集范围限制。
5. **使用数据。** 查询或导出记录，投递到 Webhook，或通过 MCP 读取数据及其谱系。

运行成功不自动代表覆盖完整。页数上限、未获取页面和质量拒绝都是结果的一部分，不会被一个成功状态掩盖。

<details>
<summary><strong>查看采集需求与字段合同</strong></summary>

![Extrio 采集需求列表](docs/reviews/unified-list-pagination/collections-1440.png)

![采集需求字段与输出合同](docs/reviews/collection-detail-polish/fields-1440.png)

</details>

桌面控制台支持 **中文和 English**，语言偏好按设备保存。支持 **1024px 及以上**的视口宽度；移动端不在当前范围内。

## 快速开始

### Docker Compose

安装 Git 和带 Compose 插件的 Docker，然后运行：

```bash
git clone https://github.com/iiwish/extrio.git
cd extrio
docker compose up --build --wait
```

打开 **[http://127.0.0.1:8080](http://127.0.0.1:8080)**，创建首个管理员账号，密码至少 8 位。服务包含控制台、API 和 Worker，状态保存在具名持久卷中。首次构建会安装浏览器依赖，可能需要几分钟。

实例会初始化一个本地招投标示例来源，便于评估。**新生成 AI 规则需要配置模型与凭据**；下方无需模型密钥的确定性冒烟测试验证的是执行链路，不是 AI 生成能力。

停止服务并保留数据：

```bash
docker compose down
```

除非明确要删除持久卷中的数据库、密钥和证据文件，否则不要添加 `-v`。默认端口被占用时，通过 `EXTRIO_API_PORT` 和 `EXTRIO_WEB_PORT` 指定空闲端口。

### 从源码运行

前置依赖：Git、**Python 3.12**、[uv](https://docs.astral.sh/uv/)、**Node.js 22**，以及 [web/package.json](web/package.json) 中锁定版本的 pnpm。在克隆后的仓库根目录执行：

```bash
uv sync --project backend --locked --python 3.12
uv run --project backend crawl4ai-setup
pnpm --dir web install --frozen-lockfile
./scripts/dev.sh
```

打开 **[http://127.0.0.1:5173](http://127.0.0.1:5173)**。API 使用 `8000` 端口，登录后可访问 `/docs` 查看交互式 API 文档。使用 `./scripts/stop.sh` 停止本地进程。

需要隔离实例时，设置 `EXTRIO_INSTANCE_DIR`、`EXTRIO_API_PORT` 和 `EXTRIO_WEB_PORT`；停止时使用相同的实例目录。启动器会检查端口冲突并等待 Worker 就绪。

### 无需模型密钥，验证采集

安装后端依赖后执行：

```bash
uv run --project backend python scripts/benchmark.py --collectors 1 --pages 1
```

该命令使用手写的签名规则，通过真实 Worker 采集内置本地来源，数据保存在临时目录中。不抓取第三方网站、不产生模型费用，也不写入已有实例。这是执行链路冒烟测试，不是兼容性或容量基准测试。

## 能力与边界

| 领域 | 当前范围 |
| --- | --- |
| 来源支持 | 受约束的 HTML/JSON 提取、单页与列表/详情流程、声明式分页和有边界的浏览器渲染。真实网站的广泛兼容性仍属实验范围。 |
| 增量采集 | 检查点，以及针对受支持、按日期降序排列的 `next_link` 来源的受控时间窗口采集；不支持任意游标或无限滚动。 |
| AI 辅助 | 规则生成与修复、结构化任务历史、尝试记录、模型用量和单次操作指导。活动日志不展示原始提示词、推理内容或模型响应正文。 |
| 治理 | 本地管理员、工程师、审核员和只读用户角色；人工规则发布、签名证明与审计记录。不强制独立双人审批。 |
| 运维 | 持久化任务、调度计划、就绪检查、诊断、备份恢复、密钥轮换和 Prometheus 指标。 |
| 存储 | SQLite WAL 用于本地评估，PostgreSQL 用于自托管部署，证据文件使用共享文件系统。 |
| 证据 | 数据/运行/规则谱系与签名证据包。页面采样证据不等于完整回放引擎，证据 ZIP 不等于灾备包。 |

生产登录流程、验证码或访问控制绕过、任意网站兼容、SSO/MFA、多租户隔离和分布式高可用不在已验证范围内。只采集公开或明确授权的来源，并遵守其访问条件。

详细限制见[运维指南](docs/self-hosted-operations.md)，发展方向见[路线图](ROADMAP.md)。[1.0 范围合同](docs/planning/v1.0-scope-matrix.md)描述交付目标，不代表稳定版已经发布。

## MCP 服务

Extrio 通过 `extrio-mcp` 向 AI 客户端提供七个工具：

| 工具 | 用途 |
| --- | --- |
| `list_collectors` | 查看来源、发布状态、调度计划和最近运行结果。 |
| `get_collector` | 查看来源详情、冻结字段、最近运行和投递目标。 |
| `create_collection` | 创建受治理的来源，提交 AI 探索，等待人工审核。 |
| `trigger_run` | 基于已发布且完整性校验通过的规则创建采集运行。 |
| `get_run` | 查看状态、数量、停止原因、完整性检查和检查点。 |
| `query_items` | 按条件筛选，以游标分页读取数据。 |
| `get_item` | 查看记录内容、判定证据、观测历史和完整谱系。 |

**MCP 不提供规则发布工具。** Agent 可以请求探索，但采集运行使用规则前必须由人发布。

面向可信本地客户端，在仓库根目录启动：

```bash
uv run --project backend extrio-mcp
```

使用 Streamable HTTP 时，先将高强度密钥设置为 `EXTRIO_MCP_TOKEN`，再启动：

```bash
uv run --project backend extrio-mcp --transport http --host 127.0.0.1 --port 8818
```

端点为 `http://127.0.0.1:8818/mcp`，请求必须携带 `Authorization: Bearer <token>`。MCP 必须与 API、Worker 使用**同一数据库、证据目录、签名密钥和凭据加密密钥**。HTTP token 授权访问全部七个工具，不是受浏览器用户角色约束的会话；远程访问必须使用 TLS。详见 [API 与 MCP 客户端指南](docs/self-hosted-operations.md#api-与-mcp-客户端)。

## 安全自托管

- 不将 API 和 Worker 直接暴露到公网；控制台流量经内置 Web 代理和受控 TLS 反向代理访问。
- HTTPS 部署设置 `EXTRIO_AUTH_COOKIE_SECURE=true`；本地 HTTP 评估默认使用 `false`。
- 保护凭据、签名密钥、持久卷和出站网络访问；生产环境不得复用开发密钥。
- 数据库、证据文件和密钥一起备份，升级前验证恢复流程。
- 将 `/metrics` 限制为可信监控访问：该端点按设计不要求认证。`/healthz` 只证明 API 存活，`/readyz` 还检查 Worker、部署及密钥一致性。

处理敏感数据或将实例开放到本机之外前，请阅读[安全政策](SECURITY.md)和[运维指南](docs/self-hosted-operations.md)。

## 文档导航

部分详细设计与运维文档使用中文维护；API 合同和代码标识在两种语言中共用。

| 入口 | 内容 |
| --- | --- |
| [控制台导览](docs/showcase.md) | 三分钟产品演示流程与本地截图。 |
| [产品定义](docs/SSOT.md) · [产品合同](docs/product-contract.md) | 产品目标、范围与行为边界。 |
| [运维指南](docs/self-hosted-operations.md) | 配置、PostgreSQL、升级、诊断、备份恢复与密钥管理。 |
| [后端架构](docs/backend-vertical-slice.md) · [架构决策](docs/architecture/) | 运行时职责与设计决策。 |
| [API 合同](docs/contracts/api-contract.md) · [OpenAPI](docs/contracts/openapi.yaml) | 集成合同、Schema 与示例。 |
| [规则指南](docs/rules-guide.md) | 提取规则及其语义。 |
| [发布就绪检查](docs/releases/public-alpha-readiness.md) · [路线图](ROADMAP.md) | 发布门槛、证据限制与后续方向。 |

## 开发与贡献

仓库维护一个正式前端和一个后端包：

```text
backend/             Python / FastAPI 控制面、Worker、MCP、存储与测试
web/                 React / TypeScript / Vite / Tailwind CSS / shadcn/ui 控制台
docs/contracts/      OpenAPI、JSON Schema、示例与提取语义
docs/architecture/   架构决策
docs/reviews/        评审记录与桌面 QA 证据
docker/              容器定义
scripts/             开发、验证与运维工具
```

在仓库根目录执行检查：

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -c backend/pyproject.toml backend/tests
uv run --project backend python scripts/update-docset-manifest.py --check
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
```

PostgreSQL 集成测试需要独立的 `EXTRIO_TEST_DATABASE_URL`，未设置时会跳过。安装冒烟检查使用 `bash scripts/verify-source.sh` 和 `./scripts/verify-compose.sh`（需要 Docker），默认分别使用 `18100`/`15173` 和 `18000`/`18080` 端口；必要时通过 `EXTRIO_API_PORT` 和 `EXTRIO_WEB_PORT` 指定空闲端口。使用 `uv build --project backend --wheel` 构建后端 wheel。

欢迎贡献来源样本、可复现的问题报告、文档、翻译和聚焦的修复。请先阅读[贡献指南](CONTRIBUTING.md)；较大的行为或合同变更，先通过 [Issue](https://github.com/iiwish/extrio/issues) 讨论。提交相关测试，界面变更附上桌面验收证据。

使用帮助与项目决策见 [SUPPORT.md](SUPPORT.md) 和 [GOVERNANCE.md](GOVERNANCE.md)。安全漏洞请按 [SECURITY.md](SECURITY.md) 的流程**私下报告**，不要提交公开 Issue。

## 许可证

Extrio 使用 [Apache License 2.0](LICENSE) 许可证。署名声明见 [NOTICE](NOTICE)。
