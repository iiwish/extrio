# Extrio 控制面 API 合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 合同 ID | `extrio.control-plane.v1` |
| 合同版本 | `v1.12.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Confirmed` |
| 机器合同 | [`openapi.yaml`](./openapi.yaml) |

## 2. 边界

Web 只访问 `/api/v1`。FastAPI 控制面是领域状态的唯一在线写入者；浏览器不直接访问 Worker、PostgreSQL、Redis 或对象存储内部地址。OpenAPI 是浏览器 API 的机器权威，GatherSpec、平台消息和 Artifact 继续由各自 JSON Schema 管理。

所有响应均返回 `X-Request-ID`。错误使用稳定的 `PlatformError`，至少包含 `code`、`message`、`requestId` 和 `retryable`；字段错误使用 JSON Pointer `pointer`，不得要求前端解析自然语言判断行为。

控制面默认启用身份认证。`/auth/state` 提供首次设置和当前会话状态；`/auth/setup` 只允许原子创建首个管理员；`/auth/login` 创建不透明服务端会话；`/auth/logout` 立即吊销当前会话。除这些引导端点外，`/api/v1` 全部继承 `extrio_session` Cookie 安全要求。密码、密码哈希和会话 token 不进入响应合同。

## 3. 异步命令

Source 探索和 Run 是异步命令：

1. POST 请求校验权限、幂等键和领域前置条件后返回 `202 Accepted`。
2. 响应体是 `Operation`，`Location` 指向 `/api/v1/operations/{operationId}`。
3. 前端按 `pollAfterMs` 查询 Operation；服务端可通过 `Retry-After` 覆盖查询间隔。
4. Operation 状态只能按 `queued -> running -> terminal` 前进；终态为 `succeeded`、`failed`、`cancelled` 或 `timed_out`，不得回到非终态。
5. `progress` 和 `phase` 由服务端事实驱动。前端不得用定时器伪造阶段、数量或成功结果。
6. `resourceType/resourceId` 指向 Collector 或 Run。Operation 成功后前端重新读取该资源获得权威快照。
7. Collector 在探索期间通过 `activeOperationId` 暴露可恢复的 Operation；Run 通过 `operationId` 保留创建它的 Operation。页面刷新后必须继续读取原 Operation，不重新创建命令。

非终态 Operation 的 `error` 必须为空；所有终态的 `phase=completed` 且 `progress=100`。失败、取消和超时终态必须携带稳定 PlatformError，成功终态的 `error` 必须为空。

Run 仍是领域聚合，并固化 `collectionMode` 与 `operationId`；Operation 只表示创建/执行命令的可观察进度，不替代 Run、RunAttempt 或 RunFinalization。

## 4. 幂等与并发

所有写请求必须携带 `Idempotency-Key`。同一 Tenant、actor、HTTP method、规范化资源目标和 key 的重试返回同一逻辑结果；相同 key 携带不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。v0.2 禁止同一 Collector 存在重叠非终态 Run，并返回 `RUN_ALREADY_ACTIVE`；探索冲突返回 `OPERATION_ALREADY_ACTIVE`。

批量 Source 导入以一次逻辑命令处理，合法项独立提交，非法项进入逐项 `error`；业务部分失败仍返回 `200`，不使用 WebDAV `207 Multi-Status`。传输或命令级失败才返回非 2xx PlatformError。

Source URL 只接受 `http` 与 `https`。匿名公共 HTTP 需要服务端 TenantAdmin 风险策略显式开启；携带 AccessProfile 或凭据的 Source 必须使用 HTTPS。`HTTPS_REQUIRED` 同时表示凭据传输不安全或当前租户未批准匿名 HTTP，`INVALID_URL` 表示协议或 URL 结构不受支持。

## 5. 分页与缓存

列表接口返回 `{items, page: {nextCursor}}`。cursor 是不透明值，客户端不得解析或拼接。`limit` 最大 200。领域命令成功后，前端按资源 ID 失效相关查询，不把列表缓存当成写入事实。

### 5.1 模型设置

`GET /settings/models` 返回供应商配置列表、模型配置列表、唯一默认模型 ID 和最近更新时间。供应商包含稳定 ID、唯一配置名称、供应商类型、HTTPS API 地址、启停状态和 `credentialConfigured`；模型包含稳定 ID、所属供应商 ID、真实模型 ID、启停状态和默认状态。`PUT /settings/models` 使用幂等键完整替换元数据，并允许供应商携带只写的可选 `apiKey`：非空值替换加密凭据，省略该字段保留原凭据。供应商允许零模型保存，模型必须引用存在的供应商，同一供应商下模型 ID 唯一，默认模型必须属于已启用供应商且自身已启用。

API Key 仅允许出现在 `PUT /settings/models` 请求的 `apiKey` 字段中。服务端使用独立主密钥加密保存，幂等记录只保存请求摘要；响应、日志和模型元数据均不得包含明文或密文。`credentialConfigured` 只表示服务端持有可解密凭据。`GET/PUT /settings/model` 作为单供应商环境变量引用兼容接口保留；新界面和后续客户端使用 `/settings/models`。该配置只属于探索和候选规则编译边界，Run API 与执行 Worker 不读取它。

Source 首次导航失败返回 `SOURCE_UNREACHABLE`。错误正文包含 Source 主机、归一化连接原因和检查动作，`retryable` 表示可在修正网址、网络或代理后重试；响应不得包含 Crawl4AI、Playwright 或浏览器内核的堆栈与源码路径。

## 6. GatherSpec 与候选规则

CandidateRule 包含适合审核的摘要和完整 `gatherSpec`。`gatherSpec` 必须通过 [`gather-spec.schema.json`](./gather-spec.schema.json)，前端只显示服务端返回的对象，不拼装或补全机器合同。

`PATCH /collectors/{collectorId}` 接受完整的可编辑定义 `name + intent + sourceUrl`。名称变化只更新展示身份；意图或规范化 Source URL 变化必须把 Collector 置为 `draft`、清除候选与审核决定并阻断 Run，历史 `activeRuleVersion` 只作为可追溯引用保留。异步 Operation 或非终态 Run 存在时返回 `OPERATION_ALREADY_ACTIVE`。

Collector 列表与详情响应必须包含稳定 `collectionId`、`collectionName` 与 `collectionVersion`。`POST /collectors/batch` 为一次需求导入生成一个 Collection 身份，并把同一身份写入每个成功 Collector 和批量结果；逐项失败不改变已成功对象的归属。`name` 是 Source 级 Collector 展示名，`collectionName` 是共享业务需求名称，两者不得在客户端混用。

`PATCH /collectors/{collectorId}/candidate-rule` 只编辑候选规则，不更新 RuleVersion。请求完整覆盖列表 Item selector、分页和当前输出字段 selector；`list_detail` 客户端通过可选的 `listFields` 完整覆盖全部列表阶段字段 selector，并保持其中 `detailUrl` 与兼容字段 `detailLinkSelector` 一致。服务端将编辑记录为编译 `overrideRefs`、重算候选 digest 和 GatherSpec `ruleDigest`、执行 Schema 校验，并使用最近一次成功探索的 sampled HTML 验证列表发现和必填字段。缺省 `listFields` 的 v1 客户端继续只更新 `detailUrl`；未知或不完整的列表字段集合被拒绝。验证失败返回 `CANDIDATE_VALIDATION_FAILED`，没有样本返回同一稳定错误；成功后 Collector 进入 `ready_review`，旧审核决定清空。发布仍通过独立命令创建新的不可变 RuleVersion。

MVP 支持：

- `single`：只执行必填 list stage，detail 不存在。
- `list_detail`：list stage 发现并规范化 detail URL，随后执行可选 detail stage。

accepted 结果必须具有 `revision >= 1`、非空 Observation 和空 `rejectionReason`。rejected 结果只是本次 Run 的拒绝候选，`revision`、`observationId` 必须为空且 `observationHistory` 为空；不得用 Revision 0 或伪 Observation 表示拒绝。

公告类 `list_detail` 的 `HarvestResult` 使用公告级语义：`listTitle` 来自列表阶段，`title`、`publishedAt` 与 `content` 来自详情文档，`sourceUrl` 是实际详情 URL，`observedAt` 是本次 Run 的采集时间。列表标题与详情标题必须同时保留以支持一致性审核；详情正文里的表格行不自动改变 Item 粒度。

CollectorDetail 返回当前不可变 CollectionPolicyVersion 与可空 Checkpoint。`POST /collectors/{collectorId}/collection-policy` 创建新版本并重置旧 policy 的 Checkpoint；首次窗口、回看天数、连续旧页数、最大列表页和最大 Item 均为显式字段。新 Run 的 `policyContextStatus=fixed`，并固定 `policyVersion`、`policyDigest`、`executionMode`、`windowStart` 和 `checkpointBefore`，完整成功后返回 `checkpointAfter`。引入该合同前的历史 Run 使用 `policyContextStatus=legacy_unavailable`，上述四个不可恢复字段返回 `null`，不得绑定当前策略伪造历史证据。

CollectorDetail 同时返回当前 CollectorSchedule。`PUT /collectors/{collectorId}/schedule` 原子创建并启用新的 Schedule revision，支持启停、五段 Cron、`Asia/Shanghai` 时区和固定 `overlapPolicy=forbid`。启用后服务端计算 `nextRunAt`；调度扫描使用稳定 occurrence key 去重，遇到未发布规则或活动 Run 时记录 skipped occurrence，不创建重叠 Run。

分页属于 list stage 内部策略，不是额外 Stage；批量入口是多个 Source，不是多阶段。

## 7. 规则完整性证据

发布事务必须持久化不可变 RuleVersion、追加式 RuleAttestation、活动规则指针和不可变 AuditEvent。Run 接受前重新计算 RFC 8785 canonical rule digest 并验证 Ed25519 证明、Tenant、RuleVersion、SigningKey 状态和 trust revision；Worker 在任何 Source 请求前使用固定上下文再次验证。

Run 必须返回 `ruleDigest`、`ruleAttestationId`、`signingKeyId`、`trustRevision` 和 `integrityStatus`，并在证据区展示。`RULE_ATTESTATION_INVALID` 表示完整性门阻断，不得回退到只检查 digest。

## 8. Mock 与真实 API

MSW 必须使用与 OpenAPI 相同的 `/api/v1` 路径、状态码和响应结构。开发环境可通过 `VITE_ENABLE_MOCKS=true` 启用；生产构建默认禁用。`VITE_API_BASE_URL` 可以指向真实 FastAPI，但不得改变 API 主版本语义。

## 9. 兼容与冻结

- `/api/v1` 只允许向后兼容扩展；删除字段、收紧已发布请求、改变状态语义或错误码需要新的 API 主版本。
- 未知 enum、未知必填字段和不支持的 GatherSpec/runtime 必须在 Source 请求前失败。
- OpenAPI、TypeScript 类型和 Python 模型在 CI 中生成或比较；手工页面类型不得覆盖机器合同。
