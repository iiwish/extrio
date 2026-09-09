# Extrio 控制面 API 合同

## 全量概览

`GET /overview?timezone=<IANA>` 对已认证用户提供全量数据库聚合，不使用 Run/Item 列表上限。默认时区 UTC；未知时区返回 422 / INVALID_REQUEST，定位 `/timezone`。响应包含 generatedAt、timezone、today、week、monthEntities、collectors 和日/周/月 14/12/12 个趋势桶。自然日、周一和自然月转换为 UTC 半开区间；运行按持久化 created_at 归桶，成功率分母只包含终态，cancelled/timed_out 计失败，queued/running/finalizing 单列。每个请求在一个数据库一致读事务内生成快照。

本月实体先按实体列表的来源/实体键和观测排序取最新行，再按该行 UTC 入库时间确定月份，避免依赖历史 observedAt 的未声明展示时区。counts 由服务端聚合而不是下载全表后在客户端计算。需要关注入口是独立的来源/最近运行列表投影，不是全量异常数量。MSW 隔离模式不回退读取真实概览，明确返回不可用。

## Item 查询

`GET /items` 与 `GET /items/export` 共享 `view=observations|entities`、`collectorId`、`runId`、`decision`、精确 `entityKey`、精确 `sourceHost` 与最多 500 字的 `q`。`q` 按标题、正文、来源名称和 entity key 做字面子串搜索，`%`、`_` 不作为通配符。

默认 `observations` 保持历史观测语义。`entities` 先按 `collectorId + entityKey` 取 observedAt 最新、id 降序打破同时间并列的观测，然后应用全部筛选；不同来源下相同 entity key 不合并。列表使用 observedAt/entityKey/id 降序游标，并返回筛选后、不含 cursor 限制的 `total` 和未筛选实体集的 `facets.sourceHosts`、`facets.collectors`。导出使用相同选择与排序，保留 CSV/JSONL 和导出上限合同。分页不提供跨请求快照隔离，持续写入时刷新以获得最新实体状态。

## 需求字段草稿与预览

`PATCH /collections/{collectionId}` 接受 `revision` 与 `fieldDraft: {fields: [...]}`，要求工程师或管理员、Idempotency-Key 及当前 revision；归档需求拒绝写入。每个字段包含 key、label、type、required、identity、fingerprint、description；最多 100 个，key 必须唯一、以英文字母开头、仅含字母数字下划线且不超过 64 字符，身份字段必须必填。空数组表示有意清空草稿，不回退为来源字段。草稿写入与幂等回执、AuditEvent 原子提交，不修改任何来源或已发布版本。

`GET /collections/{collectionId}` 返回 `fieldDraft`（存在时）与 `sourceContracts`，每个来源合同包含 sourceId、sourceName、state、ruleVersion、fields、完整 schema 与 quality。state 为 published、candidate、unavailable 或 empty。活动版本无法读取时返回 unavailable，不使用候选字段替代；没有活动版本时才可显示 candidate。字段投影包含输出 Schema 中的所有属性，不仅限于详情页样本字段。草稿是需求编辑状态，不是可执行 CollectionVersion。

## Collection 管理

`GET /collections` 返回全部独立需求摘要及来源统计；`GET /collections/{id}` 返回需求及全部关联来源，不受来源列表 50 条默认上限影响。来源中的 collectionName 是当前需求名称的投影。

`POST /collections` 接受 name（1–200 字符）和 intent（1–10000 字符），无需来源，返回 201。`PATCH /collections/{id}` 接受 revision 与 name/intent，或 revision 与 status（active/archived）；元数据编辑和归档/恢复分开提交。归档需求禁止修改元数据和接入来源；恢复后可继续使用。元数据编辑不改写已有 Collector.intent、候选规则、RuleVersion、Run 或 Item。

`DELETE /collections/{id}` 接受 revision，成功返回 200 和 `{id, deleted: true}`。存在关联来源时返回 COLLECTION_HAS_SOURCES（409），不执行级联删除。归档只控制需求的管理状态，不停止已有来源的运行与定时计划。

写操作要求 engineer/administrator 和 Idempotency-Key；幂等记录与需求写入在同一数据库事务提交。并发版本不匹配返回 COLLECTION_CONFLICT（409）；归档限制返回 COLLECTION_ARCHIVED（409）；不存在返回 COLLECTION_NOT_FOUND（404）。来源接入和需求删除/归档在相同 Collection 行锁下检查，禁止并发创建孤立来源。SQLite 使用写事务串行化，PostgreSQL 使用行锁与命令键事务锁。

迁移 003 创建 collections 表；启动按稳定 collectionId 回填缺失需求，保留同一需求不同来源的目标文本。既有需求元数据不被重复回填覆盖。空需求可通过现有 `/collectors/batch` 的 collectionId 添加来源，服务端使用当前需求名称、业务目标与 collectionVersion。

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 合同 ID | `extrio.control-plane.v1` |
| 合同版本 | `v1.16.0` |
| 对应产品版本 | `v0.6` |
| 状态 | `Confirmed` |
| 机器合同 | [`openapi.yaml`](./openapi.yaml) |

## 2. 边界

Web 只访问 `/api/v1`。FastAPI 控制面是领域状态的唯一在线写入者；浏览器不直接访问 Worker、PostgreSQL、Redis 或对象存储内部地址。OpenAPI 是浏览器 API 的机器权威，GatherSpec、平台消息和 Artifact 继续由各自 JSON Schema 管理。

所有响应均返回 `X-Request-ID`。错误使用稳定的 `PlatformError`，至少包含 `code`、`message`、`requestId` 和 `retryable`；字段错误使用 JSON Pointer `pointer`，不得要求前端解析自然语言判断行为。

控制面默认启用身份认证。`/auth/state` 提供首次设置和当前会话状态；`/auth/setup` 只允许原子创建首个管理员，密码长度为 8 至 256 个字符；`/auth/login` 创建不透明服务端会话；`/auth/logout` 立即吊销当前会话。除这些引导端点外，`/api/v1` 全部继承 `extrio_session` Cookie 安全要求。密码、密码哈希和会话 token 不进入响应合同。

## 3. 异步命令

Source 探索和 Run 是异步命令：

1. POST 请求校验权限、幂等键和领域前置条件后返回 `202 Accepted`。
2. 响应体是 `Operation`，`Location` 指向 `/api/v1/operations/{operationId}`。
3. 前端按 `pollAfterMs` 查询 Operation；服务端可通过 `Retry-After` 覆盖查询间隔。新建 Operation 同时返回 UTC `queuedAt`，供刷新后继续计算队列等待时间；历史迁移记录可以缺省该字段。探索 Operation 同时返回 `aiRunId`，使 Collector 进度可以直接进入同一 AI 任务详情。
4. Operation 状态只能按 `queued -> running -> terminal` 前进；终态为 `succeeded`、`failed`、`cancelled` 或 `timed_out`，不得回到非终态。
5. `progress` 和 `phase` 由服务端事实驱动。前端不得用定时器伪造阶段、数量或成功结果。
6. `resourceType/resourceId` 指向 Collector 或 Run。Operation 成功后前端重新读取该资源获得权威快照。
7. Collector 在探索期间通过 `activeOperationId` 暴露可恢复的 Operation；Run 通过 `operationId` 保留创建它的 Operation。页面刷新后必须继续读取原 Operation，不重新创建命令。

非终态 Operation 的 `error` 必须为空；所有终态的 `phase=completed` 且 `progress=100`。失败、取消和超时终态必须携带稳定 PlatformError，成功终态的 `error` 必须为空。

Run 仍是领域聚合，并固化 `collectionMode` 与 `operationId`；Operation 只表示创建/执行命令的可观察进度，不替代 Run、RunAttempt 或 RunFinalization。

规则生成与修复同时建立独立 `AiRun`。`POST /collectors/{collectorId}/explorations` 接受可选 `guidance`，`POST /collectors/{collectorId}/repairs` 接受兼容字段 `note`；两者最多 500 字，作为不可信操作指引固定到本次任务并提供给受约束模型编译器。指引不能改变网络边界、选择器方言、输出合同、确定性验证或人工发布门。`GET /ai-runs` 返回按创建时间倒序的任务投影，并可通过 `collectorId` 限定单个采集器；`GET /ai-runs/{aiRunId}` 追加全部 `AiAttempt` 与 `ModelInvocation`。AiRun 固定 Collector 名称、Source URL、任务类型、触发原因和发起人；`resultStatus` 表达候选是否生成，`reviewStatus` 独立表达 `not_ready`、`ready_review`、`published` 或 `superseded`。新的候选规则进入待审核时，更早的待审核任务标记为 `superseded`；发布事务把当前待审核 AiRun 关联至 `publishedRuleVersionId`。

每次 Worker 重试追加 AiAttempt；每次模型调用追加 purpose、provider、model、promptVersion、开始/结束时间、Token 用量、可空成本、响应摘要和归一化错误。新建 AiRun 和对应 Operation 追加同一份结构化 `activity` 阶段历史；阶段转换关闭上一条 running 记录并保存耗时和指标，失败时把实际失败阶段标记为 failed，终态 Operation 仍使用 `phase=completed`。AiRun 审计数据不得包含原始提示词、模型思维过程、Source HTML/JSON 样本、模型响应正文、API Key 或可用凭据。升级已有本地数据库时，历史 explore Operation 必须回填为 AiRun；无法恢复的阶段和模型用量保持缺省或零，不得推断伪造。

## 4. 幂等与并发

所有写请求必须携带 `Idempotency-Key`。同一 Tenant、actor、HTTP method、规范化资源目标和 key 的重试返回同一逻辑结果；相同 key 携带不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。当前版本禁止同一 Collector 存在重叠非终态 Run，并返回 `RUN_ALREADY_ACTIVE`；探索冲突返回 `OPERATION_ALREADY_ACTIVE`。

批量 Source 导入以一次逻辑命令处理。`POST /collectors/batch` 的 `sources` 每项包含必填 `entryUrl`，可选 `mode`、`name` 与 `scopeHint`；`mode` 省略时默认为 `exact`，当前拒绝其他模式。`exact` 入口必须是具体列表页或单页，站点根目录以 `EXACT_ENTRY_REQUIRED` 逐项拒绝。合法项独立提交，非法项进入逐项 `error`；业务部分失败仍返回 `200`，不使用 WebDAV `207 Multi-Status`。传输或命令级失败才返回非 2xx PlatformError。

Source URL 只接受 `http` 与 `https`。匿名公共 HTTP 默认允许，TenantAdmin 可以通过服务端风险策略关闭；携带 AccessProfile 或凭据的 Source 必须使用 HTTPS。`HTTPS_REQUIRED` 同时表示凭据传输不安全或当前租户不允许匿名 HTTP，`INVALID_URL` 表示协议或 URL 结构不受支持。

## 5. 分页与缓存

列表接口返回 `{items, page: {nextCursor}}`。cursor 是不透明值，客户端不得解析或拼接。`limit` 最大 200。领域命令成功后，前端按资源 ID 失效相关查询，不把列表缓存当成写入事实。

### 5.1 模型设置

`GET /settings/models` 返回供应商配置列表、模型配置列表、唯一默认模型 ID 和最近更新时间。供应商包含稳定 ID、唯一配置名称、供应商类型、HTTPS API 地址、启停状态和 `credentialConfigured`；模型包含稳定 ID、所属供应商 ID、真实模型 ID、启停状态和默认状态。`PUT /settings/models` 使用幂等键完整替换元数据，并允许供应商携带只写的可选 `apiKey`：非空值替换加密凭据，省略该字段保留原凭据。供应商允许零模型保存，模型必须引用存在的供应商，同一供应商下模型 ID 唯一，默认模型必须属于已启用供应商且自身已启用。

API Key 仅允许出现在 `PUT /settings/models` 请求的 `apiKey` 字段中。服务端使用独立主密钥加密保存，幂等记录只保存请求摘要；响应、日志和模型元数据均不得包含明文或密文。`credentialConfigured` 只表示服务端持有可解密凭据。`GET/PUT /settings/model` 作为单供应商环境变量引用兼容接口保留；新界面和后续客户端使用 `/settings/models`。该配置只属于探索和候选规则编译边界，Run API 与执行 Worker 不读取它。

Source 首次导航失败返回 `SOURCE_UNREACHABLE`。错误正文包含 Source 主机、归一化连接原因和检查动作，`retryable` 表示可在修正网址、网络或代理后重试；响应不得包含 Crawl4AI、Playwright 或浏览器内核的堆栈与源码路径。

## 6. GatherSpec 与候选规则

CandidateRule 包含适合审核的摘要和完整 `gatherSpec`。`gatherSpec` 必须通过 [`gather-spec.schema.json`](./gather-spec.schema.json)，前端只显示服务端返回的对象，不拼装或补全机器合同。

`PATCH /collectors/{collectorId}` 接受完整的可编辑定义 `name + intent + sourceUrl`。名称变化只更新展示身份；意图或规范化 Source URL 变化必须把 Collector 置为 `draft`、清除候选与审核决定并阻断 Run，历史 `activeRuleVersion` 只作为可追溯引用保留。异步 Operation 或非终态 Run 存在时返回 `OPERATION_ALREADY_ACTIVE`。

Collector 列表与详情响应必须包含稳定 `collectionId`、`collectionName` 与 `collectionVersion`。`POST /collectors/batch` 为一次需求导入生成一个 Collection 身份，并把同一身份写入每个成功 Collector 和批量结果；逐项失败不改变已成功对象的归属。`name` 是 Source 级 Collector 展示名，`collectionName` 是共享业务需求名称，两者不得在客户端混用。可选 `scopeHint` 是 Source 特定的规则编译提示，不改变 CollectionVersion 的输出语义；模型发现、首次编译和修复均使用该提示，确定性 Run 不读取它。

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
