# Extrio GatherSpec v1 语义合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 规范标识 | `extrio.gather.v1` |
| 文档版本 | `v1.5.0` |
| 状态 | `Confirmed` |
| JSON Schema | [`gather-spec.schema.json`](./gather-spec.schema.json) |
| 提取语义 | [`extraction-semantics.md`](./extraction-semantics.md) |
| 权威来源 | [`../SSOT.md`](../SSOT.md) 中的 `INV-001`、`INV-002`、`INV-003`、`INV-005` |
| 作者指南 | [`../rules-guide.md`](../rules-guide.md) |
| 最后更新 | `2026-09-03` |
| 审批责任 | 技术负责人 |

## 2. 规范边界

GatherSpec 是 RuleVersion 的可执行 JSON 合同。它只表达受控请求、分页、字段提取、规范化、质量门、预算和输出绑定，不表达通用程序。

以下内容禁止出现在 GatherSpec：

- Python、JavaScript、Shell、Wasm 或其他可执行代码。
- LLM prompt、运行时模型调用或自适应规则生成。
- secret 明文、Authorization/Cookie 值、私钥或可用 session token。
- 未经 SourceRevision 允许的 URL、主机通配符或任意代理地址。
- 运行时从网页读取并解释为系统指令的配置。

一个 JSON 文档只有同时通过 JSON Schema、本文语义校验、安全校验和完整性校验，才能成为 Published RuleVersion。

### 2.1 LLM 编译边界

LLM 只在 Source 接入或漂移修复的编译阶段运行。模型读取经过裁剪的非可信 DOM/JSON 样本，先生成列表发现计划，再结合已抓取的详情样本生成满足 [`RulePlan 语义合同`](./rule-plan.md) 和 [`rule-plan.schema.json`](./rule-plan.schema.json) 的 `extrio.rule-plan.v1`。RulePlan 只能表达 transport、`single|list_detail` 拓扑、CSS/JSONPath selector、受控字段类型与 transforms、分页、语义绑定、身份字段和指纹字段。

平台编译器负责把 RulePlan 与固定的 Tenant、CollectionVersion、SourceRevision、安全策略、预算和输出绑定组合成完整 GatherSpec。模型不得直接提供凭据、安全边界、Sink、RuleVersion ID、digest 或签名；Schema、selector 命中、详情发现、必填完整度、身份和 allowedHosts 验证失败时不得形成 NeedsReview 候选。Published RuleVersion 的运行路径只消费 GatherSpec，不读取 RulePlan、模型配置或 prompt。

## 3. 顶层语义

| 字段 | 语义 |
| --- | --- |
| `schemaVersion` | 固定为 `extrio.gather.v1`，决定语法与语义主版本 |
| `ruleVersionId` | 在 digest 计算前分配的不可变 RuleVersion ID |
| `tenantId` | 所属 Tenant；Worker 必须与 job envelope 交叉校验 |
| `collectorId` | 规则所属 Collector |
| `collectionVersionRef` | 冻结的数据合同及版本身份 |
| `sourceRevisionRef` | Source 边界快照及其配置摘要 |
| `templateRef` | 可选的 TemplateVersion 谱系，不改变 CollectionVersion 权威性 |
| `compiler` | 编译器、Agent、输入和 Override 谱系 |
| `runtimeCompatibility` | 允许执行该规则的 runtime 名称和 SemVer 范围 |
| `contract` | Item 身份、内容指纹、规范化 Schema 和质量门 |
| `sourceContext` | 运行时请求安全边界和资源策略快照 |
| `collect` | list/detail 执行计划、分页、重试和总预算 |
| `output` | raw 保留和 SinkVersion 绑定 |
| `integrity` | GatherSpec canonical digest；发布证明由独立 RuleAttestation 承载 |

RuleVersion 必须完整保存这些字段。运行时不得用数据库中的可变默认值覆盖规则行为；仅凭据 material、动态配额收紧和紧急安全阻断可以在不改变规则的情况下影响执行。

`contract.fieldBindings` 把通用提取字段映射到 `detailUrl`、`listTitle`、`listPublishedAt`、`title`、`publishedAt` 与 `content` 等平台兼容角色。绑定采用 `list.field` 或 `detail.field`；完整业务字段仍由 `normalizedItemSchema` 与 Item `extractedData` 承载。运行时必须执行列表和详情两侧的必填质量门，并且 Revision 比较只使用 `fingerprintFields`。

## 4. 引用与编译谱系

- `collectionVersionRef.collectionVersionId` 必须处于 Frozen 状态，`version` 与领域对象一致。
- `sourceRevisionRef.sourceRevisionId` 必须处于 Active 或仍被允许回放的 Superseded 状态。
- `sourceRevisionRef.configDigest` 必须与 SourceRevision canonical payload 匹配。
- `compiler.inputDigest` 是 `{collectionVersionDigest, sourceRevisionDigest, accessProfileVersionDigest, overrideDigests, artifactDigests}` JCS object 的 SHA-256；数组按 ID 的 UTF-8 字节序排序。
- `compiler.overrideRefs` 只保存 ID 与 digest；运行行为必须已经展开到 `sourceContext` 和 `collect`。
- 使用 Agent 时必须记录 provider、model、promptVersion 和 toolchainVersion；不使用 Agent 时省略 `agent`，不得填入虚构值。

## 5. Runtime 兼容性

- `runtimeName` 必须匹配执行 Worker 声明的 runtime。
- 版本比较使用 SemVer 2.0.0。
- Worker 版本必须 `>= minVersion` 且 `< maxVersionExclusive`，并精确匹配 `dialectVersion`、`parserVersion`、`tzdbVersion` 与 `unicodeVersion`。
- Runtime 不支持组合时必须在任何 Source 请求前失败。
- Runtime patch 版本只有在 GatherSpec golden fixtures 行为一致时才可以被视为兼容。

## 6. 数据合同

### 6.1 身份字段

- `identityFields` 只能引用 `normalizedItemSchema.properties` 和 list/detail `fields` 中存在的字段。
- 所有身份字段经过类型转换与 transforms 后必须非 null、非空。
- 平台自动把 tenantId、collectionId 和 sourceId 加入实体键作用域，不应把这些系统字段写进 `identityFields`。
- 身份字段次序属于合同；改变次序或字段必须创建 CollectionVersion。

### 6.2 指纹字段

- `fingerprintFields` 只能引用规范化字段，至少包含一个能反映业务内容变化的字段。
- 指纹不应包含 `observedAt`、Run ID 或其他每次运行变化的系统字段。
- `outputContractDigest` 必须与 CollectionVersion 中规范化 Schema、身份、指纹字段和事件语义的 canonical digest 一致。
- digest 输入中的 `eventSemantics` 精确为 `{emitUnchanged, eventTypes, tombstonePolicy}`；无 tombstonePolicy 时 eventTypes 为 `["upsert"]`，存在时为按 UTF-8 字节序排序的 `["tombstone","upsert"]`，缺少 tombstonePolicy 时使用 JSON `null`。Sink 绑定和交付策略不进入该摘要。
- identity 与 payload fingerprint 输入必须包含字段名、规范类型和值，采用 JCS object；字段 transforms 在指纹前完成。

### 6.3 规范化 Item Schema

`normalizedItemSchema` 必须是有效的 JSON Schema Draft 2020-12，顶层 `type` 必须为 `object`，并明确 `properties`、`required` 和 `additionalProperties`。v0.2 不允许未声明字段进入 Sink。

- Schema 必须完全自包含；所有 `$ref` 只能以 `#` 开头，禁止 `http:`、`https:`、`file:`、`data:` 和其他外部引用。
- Validator 必须关闭网络和文件系统 resolution。
- Schema UTF-8 大小上限 256 KiB、结构深度 32、`$ref` 数量 256、单个 regex 512 bytes。
- `pattern` 只允许 RE2 兼容子集，禁止回溯引用、lookbehind 和实现相关扩展。

### 6.4 质量门

- `requiredFieldCompleteness` 为 `[0,1]`，默认产品门槛是 `0.95`，身份字段要求始终为 `1.0`。
- `maxItemErrorRatio` 计算为拒绝 candidate item 数除以全部 candidate item 数。
- `emptyResultPolicy=allow` 只适用于业务上允许空结果的 Collection；`suspect` 会进入漂移判断；`fail` 直接使 Run Failed。
- 质量门基于一次 Run 的最终统计，不因请求重试重复计数。
- 需要输出 tombstone 时，`tombstonePolicy` 必须指定一个规范化字段和一组精确值；该字段只能表达 Source 明确提供的删除、撤销或失效信号。
- `tombstonePolicy.field` 必须包含在 `fingerprintFields` 中，保证 upsert 与 tombstone 不会共享 revisionKey。

## 7. SourceContext

### 7.1 EntryPoint 与主机

- `entrypoints` 必须是绝对 HTTP(S) URL，不允许 userinfo 和 fragment。
- `allowedHosts` 使用精确、规范化的小写 DNS hostname；不得使用 `*`。
- entrypoint 主机、detail URL 和每次 redirect 都必须属于 allowedHosts。
- URL 在检查前必须解析、移除默认端口、规范化主机并解析 DNS；安全规则以 [`../security-compliance.md`](../security-compliance.md) 为准。

### 7.2 AccessProfile

`accessProfileRef` 包含 AccessProfile 与 AccessProfileVersion ID，不是 Secret Manager path。没有认证时省略。存在该引用时所有 entrypoint 必须使用 HTTPS；认证 Header、Cookie、签名和代理 material 在请求发送前由 Worker 按精确 origin/path scope 注入，不进入规则或日志。

### 7.3 Transport

- `http` 使用确定性 HTTP 客户端，不执行页面 JavaScript。
- `browser` 使用隔离浏览器上下文，并必须声明固定 Chromium engine/version、viewport、deviceScaleFactor、locale、timezoneId、waitUntil 与 postLoadDelayMs 的 `browserPolicy`。`postLoadDelayMs` 固定导航完成后等待异步列表渲染的时长，并进入不可变规则版本。
- 浏览器 transport 仍受 allowedHosts、redirect、请求数、体积、时长和下载禁用约束。
- 浏览器字段提取只消费导航完成后持久化的 canonical DOM snapshot；重放不得重新执行页面 JavaScript 并声称结果等价。

### 7.4 限流与请求策略

- `rateLimit.rps`、`burst` 和 `maxConcurrency` 是该规则允许的上限，不覆盖平台、Tenant 或 Source 更严格的动态限制。
- `timeoutMs` 是单请求总超时。
- `maxResponseBytes` 以解压后的响应体计算。
- `headers` 仅允许非敏感静态 Header；Authorization、Cookie、Proxy-Authorization 和平台保留 Header 由语义校验拒绝。
- Redirect 不继承凭据。目标 URL 通过 allowedHosts 和 AccessProfileVersion origin scope 后，Worker 才能为目标重新解析并注入凭据；禁止 HTTPS 降级。

## 8. Selector 与字段规则

### 8.1 Selector DSL

v0.2 支持：

- `css:<selector>::text`
- `css:<selector>::html`
- `css:<selector>::attr(<name>)`
- `jsonpath:<path>`

`itemsSelector` 只使用 `css:<selector>` 或 `jsonpath:<path>`，返回 item 节点集合。字段 selector 相对于当前 item 或 detail document 求值。CSS/JSONPath 方言、DOM、cardinality、类型和 transforms 完整语义以 [`extraction-semantics.md`](./extraction-semantics.md) 为准。

Selector 不允许脚本、网络请求、函数调用或正则替换。语法解析必须使用结构化 parser，不能用任意 `eval`。

### 8.2 字段规则

- `valueType` 为 `string`、`integer`、`number`、`boolean`、`datetime`、`url`、`html` 或 `json`。
- 每个字段必须声明 `multipleMatchPolicy=error|first`，不得依赖第三方库默认选择行为。
- `required=true` 且字段缺失时，`onError` 不能为 `null`。
- `datetime` 必须声明可解析格式或使用严格 RFC 3339；无时区输入使用 `defaultTimezone`。
- `url` 在 `absolute_url` transform 后仍必须经过 allowedHosts 检查，才可以作为 detail URL。
- transforms 按数组顺序执行；数组项既可以是既有纯字符串枚举（`trim`、`collapse_whitespace`、`lowercase`、`uppercase`、`absolute_url`、`strip_html`），也可以是仅用于 `regex_extract` 的对象形态 `{"type": "regex_extract", "pattern": "<RE2>", "group": <0-8>}`；两种形态不得混用于同一数组项以外的键。运行时不得增加未声明 transform。
- `label` 为可选展示字段（1–64 字符，任意 Unicode），用于审核界面与 LLM prompt 语义；省略时必须整体省略该键，编译器不得虚构占位值。`label` 不参与提取、指纹、`outputContractDigest` 或 `ruleDigest`。
- `html` 保留 Source 内容语义，但仍是不受信任内容，展示与输出遵守安全合同。

`regex_extract` 的 RE2 语法边界、捕获组语义与无匹配时同 `onError` 的交互，以 [`extraction-semantics.md`](./extraction-semantics.md) 为准；完整的编写视角解读见 [`../rules-guide.md`](../rules-guide.md) 第 4 节。

## 9. 模板变量

模板仅允许精确变量替换，不允许表达式：

- `{{page}}`：page 分页当前数值。
- `{{<fieldName>}}`：当前 list item 已提取并规范化的字段。

cursor、watermark、windowStart、windowEnd、lookback 和 Checkpoint 不属于 GatherSpec 模板变量。v0.2 由独立 CollectionPolicyVersion 与 Run 固定上下文提供时间窗口和 Checkpoint，运行时不得把这些值注入 selector、URL 或请求模板。

变量必须经过目标上下文编码：URL path、query、Header 和 body 分别编码。缺失变量是语义错误，不能替换为空字符串。不得允许变量改变 scheme、host 或 port。

## 10. list、detail 与分页

- list 的 `entrypointIndex` 必须指向现有 entrypoint。
- list `responseType` 与 itemsSelector 前缀必须一致：HTML 使用 css，JSON 使用 jsonpath。
- detail 是可选阶段；存在时 `urlTemplate` 必须引用 list 字段，并在发送前完成 URL 安全检查。
- `page` 分页由 runtime 注入 query `parameter`，列表请求中不得声明同名冲突值；v0.2 不支持向 body 动态注入分页参数。
- `next_link` selector 从当前 list document 提取下一页 URL。
- `maxPages` 是硬上限；响应摘要或规范化 URL 重复时提前停止并记录原因。
- `allowCrossHost=true` 只表示允许在 allowedHosts 集合内跨主机，不允许扩展集合。

## 11. 重试与预算

- `requestRetry.maxAttempts` 包括第一次请求。
- 只重试运行时合同列出的瞬时错误；结构、安全、Schema 和权限错误不可重试。
- `budget.maxPages` 必须大于或等于分页自身 maxPages，并提供全 Run 防线。
- `maxItems` 按 candidate item 计数，防止大量错误 item 绕过预算。
- `maxTotalBytes` 按解压后字节累计。
- `onExceeded=partial` 产生 PartiallySucceeded；`fail` 产生 Failed。两者都保留已提交数据和明确停止原因。

## 12. 输出

- `rawRetentionDays` 范围为 0 至 90；0 表示不保存成功 raw，但失败证据仍按 Tenant 策略处理。
- `emitUnchanged` 在 v0.2 固定为 `false`；内容未变化时不创建新的 ItemEvent。
- `sinks` 只绑定预配置 SinkVersion，不携带 endpoint、Topic 凭据或签名 secret。
- 同一 GatherSpec 中 `sinkVersionId` 必须唯一；Sink 绑定变化只影响 Delivery，不改变 Item Revision 身份。
- `eventMode=upsert` 不产生 tombstone；`upsert_tombstone` 必须同时存在合法 `tombstonePolicy`。
- Delivery 采用 [`../runtime-contract.md`](../runtime-contract.md) 的 at-least-once 和重试语义。

## 13. Canonicalization、digest 与签名

### 13.1 Digest

1. 深拷贝完整 GatherSpec。
2. 删除 JSON Pointer `/integrity/ruleDigest`。
3. 使用 RFC 8785 JSON Canonicalization Scheme 生成 UTF-8 字节。
4. 计算 SHA-256，格式为 `sha256:<64 个小写十六进制字符>`。

JSON 不允许重复 key、NaN、Infinity 或不能被 JCS 表达的数值。`ruleVersionId`、`digestAlgorithm` 和其他完整性以外字段都属于 digest。

### 13.2 发布证明

- GatherSpec 不内嵌签名，避免密钥轮换改变不可变规则载体。
- 发布服务必须生成满足 [`rule-attestation.md`](./rule-attestation.md) 的追加式 RuleAttestation。
- Worker 必须验证重新计算的 digest，并验证至少一个当前有效、purpose 正确且未吊销的 RuleAttestation。

## 14. 兼容与扩展

- `additionalProperties=false` 的对象不得接收未知字段。
- 向 v1 增加可选字段前必须证明旧 runtime 会明确拒绝或安全忽略；能力协商不能依赖静默忽略。
- Enum 新值只有在 runtime 声明支持时才能发布。
- 兼容性 minor 演进（新增可选字段、扩大值域，如 `label` 与 `regex_extract` 对象形态）不改变 `schemaVersion`；任何删除、改名或语义变化属于不兼容变化，必须发布新的 GatherSpec 主版本 `extrio.gather.v2`。旧 Worker 对未知字段的确定性拒绝（AC-012.4）是特性而非缺陷。完整演进政策见 [`../rules-guide.md`](../rules-guide.md) 第 5 节。
- 改变默认值、Selector 语义、规范化、身份、指纹、分页或 digest 属于不兼容变化。
- Rule 导入必须重新执行所有校验，不因签名来源可信而跳过安全检查。

## 15. 校验顺序与错误类别

1. JSON 解析：`RULE_JSON_INVALID`。
2. Schema：`RULE_SCHEMA_INVALID`。
3. 引用与 Tenant：`RULE_REFERENCE_INVALID`。
4. 语义：`RULE_SEMANTIC_INVALID`。
5. 安全：`RULE_SECURITY_INVALID`。
6. digest：`RULE_DIGEST_INVALID`。
7. RuleAttestation：`RULE_ATTESTATION_INVALID`。
8. runtime compatibility：`RULE_RUNTIME_UNSUPPORTED`。

错误必须包含稳定错误码、JSON Pointer、可理解说明和 requestId，不得回显 secret 或完整敏感 URL。

## 16. 发布验收

- Schema 自身通过 Draft 2020-12 meta-schema 校验。
- 正例 [`gather-spec.example.json`](./gather-spec.example.json) 通过 Schema、提取语义和 digest 验证；对应 RuleAttestation 通过独立 Schema 和 [`示例公钥`](./rule-attestation.example.public-key.pem) 验证。
- 缺少身份、非法 Selector、越界主机、敏感 Header、分页冲突、非法 runtime 范围和错误签名均有反例测试。
- FastAPI 控制面的 Python validator、执行 Worker 与 TypeScript 合同测试对全部 fixtures 给出相同结果、canonical bytes 和 digest。
- Worker 对未知字段、未知 enum 和不支持 runtime 采取拒绝，不静默降级。
