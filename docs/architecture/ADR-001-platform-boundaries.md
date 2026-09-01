# ADR-001：平台服务边界

## 元数据

| 字段 | 内容 |
| --- | --- |
| 决策状态 | `Ready_For_User_Review` |
| 决策版本 | `v2.0.0` |
| 对应产品版本 | `v0.2` |
| 最后更新 | `2026-08-30` |
| 审批责任 | 技术负责人 |
| 关联不变量 | `INV-001`、`INV-003`、`INV-004`、`INV-005`、`INV-007` |

## 背景

Extrio 需要稳定的多租户控制面、可审核的 AI 编译能力、成熟的 HTTP/浏览器采集生态和高效的运营前端。系统可以使用统一 Python 技术栈降低首版交付成本，但领域写入、LLM、浏览器、凭据和生产执行仍属于不同信任边界，不能因语言相同而合并权限或生命周期。

## 决策

采用 React Web 控制台、Python FastAPI 控制面、Python 编译 Worker 和 Python 执行 Worker 四类运行单元。控制面、编译与执行可以位于同一代码库，但以独立进程、工作负载身份、网络权限和部署入口运行。

### React Web 控制台

负责：

- Collector 创建、Source 探索、样本审核、规则发布、Run 与 Item/谱系操作界面。
- 使用 OpenAPI 和版本化 JSON Schema 访问控制面。
- 呈现 loading、partial、failed、permission denied、empty 和 success 状态。

Web 控制台不得直接访问 PostgreSQL、Redis、对象存储内部地址、Worker API 或服务凭据。客户端 tenantId、角色、隐藏按钮和路由状态均不构成授权依据。

### Python FastAPI 控制面

负责：

- 外部 API、Tenant、Membership 和 RBAC。
- Template、Collection、Source、Collector、RuleVersion、Schedule、Run、Item、Delivery 和 AuditEvent 的领域命令。
- Schema/语义验证编排、发布、回滚、调度、配额、告警和交付状态。
- PostgreSQL 事务、transactional outbox、job dispatch、签名 envelope 和短期 Worker 权限。

控制面是 PostgreSQL 领域表的唯一在线写入入口。生产采集、浏览器生命周期和 LLM 调用不得运行在 API request handler 或 FastAPI `BackgroundTasks` 中。数据库迁移、受控运维和恢复工具使用独立身份并生成审计记录。

### Python 编译 Worker

负责：

- 使用 Crawl4AI 和受控 sample-fetch 能力探索 Source。
- 基于固定输入生成 GatherSpecDraft、字段映射、样本结果、ArtifactManifest 和验证报告。
- 在允许的编译路径调用 LLM，并记录 provider、model、promptVersion 和 toolchainVersion。

编译 Worker 不得发布规则、写领域表、解析 Sink 凭据或访问其他 Tenant 数据。需要认证的样本请求由隔离 sample-fetch 能力执行；控制面重新验证并持久化候选结果。

### Python 执行 Worker

负责：

- 校验签名 JobEnvelope、RuleVersion digest、RuleAttestation 和 runtime 支持范围。
- 使用 Crawlee 的 RequestQueue、HTTP/Parsel/Playwright runtime 执行 GatherSpec。
- 上传 raw/Artifact 与 ArtifactManifest，按 ResultBatch 提交规范化候选和证据引用。
- 维护 lease、heartbeat、请求级重试、并发和资源预算。

执行 Worker 不得调用 LLM、修改规则、直接写 PostgreSQL 领域表或决定发布状态。Worker 进程可以水平扩展和被安全终止；旧租约通过 fenceToken 阻断提交。

### Crawl4AI 与 Crawlee

- Crawl4AI 用于编译和样本探索，提供页面理解、Markdown/DOM 观察和候选提取 Schema；自适应或 LLM 行为不进入生产运行路径。
- Crawlee 用于已发布 GatherSpec 的执行，承担请求队列、去重、HTTP/浏览器生命周期、会话、重试和并发控制。
- Extrio 的 GatherSpec、提取语义和 canonicalization 是运行权威；两套库的默认行为不得越过合同。
- Source 可由 HTTP runtime 完成时优先不用浏览器；浏览器版本和上下文按合同固定。

## 接口与数据所有权

| 数据/能力 | 唯一写入者 | 读取者 | 传输 |
| --- | --- | --- | --- |
| 领域对象与状态 | FastAPI 控制面 | Web、控制面、受限查询服务 | HTTPS JSON + PostgreSQL |
| 编译任务 | FastAPI 控制面 | 编译 Worker | Redis Streams 中的引用 |
| 编译样本请求 | 控制面授权、sample-fetch 执行 | 编译 Worker 读取脱敏结果 | 受控工具 API + 对象存储 |
| GatherSpecDraft/报告 | FastAPI 控制面接收并写入 | 编译 Worker 产生 | 内部 HTTPS JSON API |
| 运行任务 | FastAPI 控制面 | 执行 Worker | Redis Streams 中的引用 |
| raw/Artifact 内容 | sample-fetch 或执行 Worker 使用预签名写入 | 授权用户与服务 | S3 兼容对象存储 |
| ArtifactManifest 元数据 | FastAPI 控制面 | 控制面、Worker、授权用户 | PostgreSQL + 对象存储引用 |
| HarvestItem/Delivery | FastAPI 控制面 | Web、API、交付 dispatcher | 内部 HTTPS ingest API + PostgreSQL |
| secret material | 凭据代理 | 当前任务 Worker | 绑定 job 的短期 HTTPS 会话 |

Redis 消息不得携带 raw、secret、完整规则或可变领域副本，只携带对象 ID、不可变 digest、fenceToken 和 trace context。

## 协议规则

- Web API 使用版本化 HTTPS JSON 和机器可校验 OpenAPI；TypeScript client 由合同生成或验证。
- 异步消息、结果批次与错误 envelope 遵守 [`../contracts/platform-protocol.md`](../contracts/platform-protocol.md)。
- 消费者只在 PostgreSQL 状态提交成功后确认消息。
- 所有请求具有 requestId；重试命令使用稳定 idempotency key。
- 控制面拒绝不支持的 GatherSpec 或消息主版本。

## 备选方案

### Go 控制面 + Python Worker

具有更强静态约束和独立故障域，但首版需要维护跨语言领域模型、客户端和部署工具链。当前团队规模和闭环速度不要求该复杂度；达到性能、组织或隔离阈值时可通过新 ADR 引入。

### 单进程 Python 应用

部署简单，但会把 API、LLM、浏览器、重任务和领域写入放在同一故障与权限边界。未采用。

### Worker 直接写 PostgreSQL

吞吐路径更短，但会形成多写入者、重复领域逻辑和不可证明的状态机一致性。未采用；性能不足时优先扩展批量 ingest API。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 相同语言导致边界模糊 | 独立入口、进程、身份、网络策略、依赖方向和 contract tests |
| 浏览器/LLM 阻塞 API | 编译与执行只在 Worker；API 不使用 BackgroundTasks 承载长任务 |
| Python 控制面吞吐不足 | async I/O、批量 ingest、对象存储卸载、水平扩展和压测 |
| Crawl4AI/Crawlee 语义重叠 | 编译/执行职责分离，Extrio 适配层固定语义 |
| Redis 消息丢失或重复 | PostgreSQL outbox、稳定幂等键、fenceToken 和队列重建 |
| Worker 被恶意 Source 控制 | 沙箱、egress allowlist、短期凭据、资源预算和不可写领域边界 |

## 任务影响

- Web 控制台遵守 [`../frontend-prototype.md`](../frontend-prototype.md)，默认通过同源 `/api/v1` 连接 FastAPI 真实纵向闭环；MSW 只用于前端隔离开发与合同测试。
- 后端采用 FastAPI application factory，并为 API、compiler worker、runtime worker 提供独立进程入口。
- 控制面提供批量结果 ingest、预签名 Artifact 上传和凭据代理接口。
- CI 执行 Python/TypeScript consumer contract test、GatherSpec fixtures 和 OpenAPI compatibility check。

## 验收

1. Web 控制台无法访问数据库、内部对象存储地址或服务 secret。
2. 编译与执行 Worker 无法直接写领域数据库。
3. 执行 Worker 网络无法访问 LLM 和控制面管理接口。
4. 相同 job 重复投递只产生一个逻辑 Run/Delivery 结果。
5. 协议版本不兼容时任务在执行前明确拒绝。
6. 任意 Item 可跨进程追溯到同一 requestId、runId 和 ruleVersionId。
