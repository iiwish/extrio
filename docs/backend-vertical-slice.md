# Extrio 真实纵向闭环

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v1.12.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Confirmed` |
| 权威来源 | [`SSOT.md`](./SSOT.md) |
| 最后更新 | `2026-09-02` |

## 2. 闭环范围

本地纵向闭环覆盖需求与 URL 批量导入、Collector 创建和定义编辑、Crawl4AI Source 探索、同域 iframe 列表入口解析、默认模型两阶段 RulePlan 编译、候选规则 Override 与最近探索样本验证、GatherSpec Schema 校验、字段风险审核、RuleVersion 发布、CollectorSchedule、稳定 occurrence 去重与禁止重叠调度、CollectionPolicyVersion、首次时间窗口、增量 Checkpoint、确定性运行、分页与详情发现、HTML CSS/JSON JSONPath 字段提取、new/updated/unchanged 分类、accepted/rejected 质量终结、Item 谱系查看和刷新后状态恢复。

公告类两阶段采集以列表记录作为 Item 边界：列表阶段提取 `listTitle + detailUrl`，详情阶段提取 `title + publishedAt + content`，运行时写入 `observedAt` 采集时间。详情正文中的内部表格属于公告内容，不自动展开成新的 HarvestItem。

本地 TenantAdmin 策略通过 `EXTRIO_ALLOW_HTTP_PUBLIC=true` 显式允许匿名公共 HTTP Source。该开关默认关闭，不适用于 AccessProfile 或凭据请求，也不改变 allowedHosts、私网/metadata、DNS、redirect 与资源预算边界。开发启动脚本显式启用该策略，以覆盖仍只提供 HTTP 的政府公开站点。

控制面、探索和运行分别由 FastAPI API 进程与独立 Worker 进程承担。API 请求只持久化命令并返回 `202 Accepted` Operation；Worker 通过 SQLite 租约队列领取任务，阶段、指标、错误和终态全部写回持久化 Operation。API 进程重启不会丢失 Collector、Run、Item、幂等记录或已排队任务。

## 3. 组件合同

| 组件 | 当前职责 | 不承担的职责 |
| --- | --- | --- |
| React Web | `/api/v1` 客户端、操作轮询、审核决策和桌面运营界面 | 不读取数据库，不伪造异步进度，不运行采集代码 |
| FastAPI | OpenAPI v1、URL 校验、幂等、状态机入口、查询与本地演示 Source | 不在请求生命周期执行 Crawl4AI 或 Crawlee |
| Crawl4AI + Rule Compiler | 获取入口样本并解析同域嵌入入口；默认模型先编译列表发现计划，再结合详情样本编译 RulePlan；服务端验证并转换为 GatherSpec | 不发布规则，不参与已发布规则的运行，不接受模型生成代码 |
| Deterministic Runtime | 解释已发布 GatherSpec，执行其中冻结的 HTTP/browser transport、CSS/JSONPath selector、query page/next_link 分页、详情请求、字段提取和质量终结 | 不调用 LLM，不隐式修改规则 |
| SQLite Store | 本地领域状态、不可变 RuleVersion/RuleAttestation/AuditEvent、Operation、leased job 与幂等持久化 | 不作为生产高可用数据层 |

## 4. Phase 状态

| Phase | 状态 | 退出证据 |
| --- | --- | --- |
| Phase 1 · 控制面与持久化 | `Completed` | FastAPI `/api/v1`、SQLite WAL、幂等响应、持久化 Operation、独立 leased job Worker 与稳定 PlatformError |
| Phase 2 · 真实探索 | `Completed` | Crawl4AI 真实获取列表与详情样本并解析同域 iframe 入口，默认模型编译受约束 `extrio.rule-plan.v1`，服务端验证并生成 `single`/`list_detail` CandidateRule，GatherSpec 通过冻结 Schema |
| Phase 3 · 确定性运行 | `Completed` | 运行时直接解释已发布 GatherSpec，执行 HTTP/browser、HTML CSS/JSON JSONPath、query page/next_link 分页、允许主机约束、详情发现与通用字段提取；重复 Run 不复用旧 RequestQueue |
| Phase 4 · 产品闭环 | `Completed` | React 通过同源 `/api/v1` 完成导入、探索、审核、发布、运行、Run/Item/lineage 查看与刷新恢复，桌面双视口验证通过 |
| Phase 5 · 可信发布与运行门 | `Completed` | RFC 8785 rule digest、Ed25519 RuleAttestation、SigningKey 信任状态、不可变 RuleVersion/AuditEvent 与摘要链均已持久化；API 接受 Run 和 Worker 发出 Source 请求前双重验证，Run 证据区展示固定证明 |
| Phase 6 · 受控增量采集 | `Completed` | 不可变 CollectionPolicyVersion、成功 Checkpoint、30 天默认首次窗口、3 天默认回看、连续旧页停止、预算截断保护、Revision 分类与 Run 固定证据均已实现 |
| Phase 7 · Collector 配置工作区 | `Completed` | 采集定义编辑、保存并重新生成、两阶段候选规则工作台、完整列表/详情 selector 与分页直接编辑、最近探索样本验证、新候选 digest 与活动 RuleVersion 不可变边界均已实现 |
| Phase 8 · Collector 定时运行 | `Completed` | Collector 级 Schedule 启停、五段 Cron、下次运行计算、持久化 occurrence 去重、禁止重叠与自动 Run 入队均已实现 |

## 5. 分发方式

源码仓库是开发与审查入口；后端 wheel 是可安装的次级开发制品，并内置运行所需的 `docs/contracts` 契约快照。OCI 镜像是部署主制品，同一后端镜像分别以 `extrio-api` 和 `extrio-worker` 两个角色启动，二者共享持久化目录。根目录 `compose.yaml` 提供仅绑定本机地址的单机评估拓扑；Web 镜像通过 Nginx 提供静态资源并同源代理 `/api`。

容器拓扑默认不创建依赖 API 本机地址的演示 Collector。用户从控制台添加 HTTPS Source 后执行真实闭环。当前容器仍属于本地 Alpha 分发，不构成生产部署模板，生产边界继续以第 8 节为准。

## 6. 本地运行

```bash
uv sync --project backend --python 3.12
uv run --project backend crawl4ai-setup
pnpm --dir web install
./scripts/dev.sh
```

Web 使用 `http://127.0.0.1:5173`，API 使用 `http://127.0.0.1:8000`。首次启动自动创建一个指向 `/demo/tenders` 的 draft Collector。该演示 Source 包含两页列表、四个详情，其中三个通过质量门，一个因 `buyer` 缺失被拒绝，可重复证明完整闭环而不依赖第三方站点稳定性。

## 7. 验证门

1. `uv run --project backend ruff check src tests` 与 `uv run --project backend pytest` 必须通过。
2. `pnpm --dir web test`、`pnpm --dir web lint` 与 `pnpm --dir web build` 必须通过。
3. 真实浏览器必须从 draft Collector 完成探索、两阶段 RulePlan 编译、预算风险处置、发布和运行；可重复本地 Source 得到 `3 accepted / 1 rejected`。北京政府采购信息公告 HTTP Source 必须从 iframe 外壳解析真实列表入口，完成首次窗口与增量 Run，并得到可追溯 accepted Item 和 Checkpoint。
4. 刷新 Collector、Run 和 Item 页面后必须读取同一 SQLite 事实，不回退到 MSW 状态。
5. `1440x900` 与 `1280x800` 桌面视口不得出现关键溢出、遮挡或不可达操作。
6. `uv build --project backend --wheel` 产出的 wheel 必须包含 `extrio/contracts_data/openapi.yaml`；`docker compose config` 必须通过。

## 8. 生产边界

该闭环是可运行的公开 Alpha 基线，不等于多租户生产发布。公开 Alpha 通过本地管理员和服务端会话保护控制面；生产验收仍要求 PostgreSQL、Redis Streams、对象存储、OIDC/RBAC、KMS/HSM 托管签名、集中审计与导出、分布式高可用调度、交付、完整 SSRF/DNS rebinding 防护、租户隔离、重试栅栏、容量与灾备证据。SQLite、API 进程内调度扫描、文件型开发私钥、显式风险接受的匿名 HTTP 和本地单 Worker 只允许用于 Alpha 与验收环境。

## 9. 外部 HTTP 验收快照

`2026-09-01` 使用北京政府采购公告入口 `http://www.ccgp-beijing.gov.cn/xxgg/sjxxgg/zbgg/A002004001001index_1.htm` 验收通用编译链。Crawl4AI 固定一页列表和三个详情样本；GLM `glm-5.3-flash` 先编译列表发现计划，再编译包含 `list/detail` 字段、语义绑定、identity 与 fingerprint 的 `extrio.rule-plan.v1`。平台将其转换为 GatherSpec、完成人工审核并发布 `rule_www_ccgp_beijing_gov_cn_7cd7dd12_v1`。确定性 Run `run_ff9e7e00acc1489a` 未调用模型，读取原始 HTTP 响应，获取 `1` 个列表页、发现并抓取 `14` 个详情，终结为 `14 accepted / 0 rejected`、`14 new`；再次执行的增量 Run `run_c2c83dcb10594c44` 得到 `14 unchanged / 0 updated / 0 new`。两个 Run 的 RuleAttestation 均验证为 `verified`。

同日还使用外层入口 `http://www.ccgp-beijing.gov.cn/xxgg/A002004index_1.htm` 完成真实增量闭环。Crawl4AI 把同域 `#shuju` iframe 的 `http://www.ccgp-beijing.gov.cn/xxgg/sjxxgg/A002004001index_1.htm` 固定为有效入口；规则覆盖 `.inner-ul` 公告列表、列表时间与详情 URL、同源 `next_link` 分页、`.xl-box-t` 标题/发布时间和 `#BodyLabel` 公告正文。

首次完整 Run `run_x_37bc37b89d994d` 使用 `windowStart=2026-08-31`，获取 `8` 个列表页、发现并获取 `93` 个窗口内详情、过滤 `19` 条窗口外记录，以 `time_window_reached` 正常停止并建立 watermark `2026-08-31`。增量 Run `run_bef23013880946d1` 固定前一次 Checkpoint 与 `windowStart=2026-08-30`，得到 `93 unchanged / 0 updated / 0 new`，以 `checkpoint_reached` 正常停止；Checkpoint 的 `lastSuccessfulRunId` 原子更新。两个完整 Run 均为 `succeeded`，accepted `93`、rejected `0`。
