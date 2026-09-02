# Extrio 领域模型

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v0.8.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Confirmed` |
| 权威来源 | [`SSOT.md`](./SSOT.md) |
| 最后更新 | `2026-08-31` |
| 审批责任 | 技术负责人、产品负责人 |

## 2. 建模原则

1. 所有租户数据对象必须包含 `tenantId`，跨对象引用必须属于同一 Tenant。
2. 稳定业务身份与不可变版本分离。稳定对象用于引用和权限，版本对象用于执行与审计。
3. 已发布、已冻结或已经被 Run 引用的版本不得原地修改。
4. 状态变化必须通过领域命令完成，并追加 AuditEvent；不得由数据库脚本绕过状态机。
5. 删除默认采用归档或不可变 tombstone。涉及审计、版本、运行和交付的记录不得物理覆盖。
6. 所有摘要均针对明确的 canonical payload 计算，摘要值不是对象的唯一数据库主键。

## 3. 聚合与对象

### 3.1 Tenant 聚合

| 对象 | 类型 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| Tenant | 聚合根 | 数据、配额和安全边界 | `tenantId` 全局唯一；只允许 `Active` 或 `Suspended` Tenant 执行任务 |
| User | 身份引用 | 平台用户身份 | 用户可加入多个 Tenant，不直接承载租户权限 |
| Membership | 实体 | User 在 Tenant 中的角色集合 | `(tenantId, userId)` 唯一；角色变更写入 AuditEvent |
| AuditEvent | 不可变实体 | 记录安全与治理操作 | 只追加；包含 actor、action、target、beforeDigest、afterDigest、requestId 和时间 |

角色及权限语义由 [`security-compliance.md`](./security-compliance.md) 定义。

### 3.2 模板与 Collection 聚合

| 对象 | 类型 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| CollectionTemplate | 聚合根 | 可复用行业模板的稳定身份 | 可归档；不直接作为运行输入 |
| TemplateVersion | 不可变版本 | 字段、身份、质量和默认输出模板 | `Published` 后不可变；版本号在 Template 内唯一 |
| Collection | 聚合根 | 一个业务采集目标的稳定身份 | 名称在 Tenant 内唯一；归档后不得新建 Collector |
| CollectionVersion | 不可变版本 | 冻结后的数据合同 | `Frozen` 后不可变；引用至多一个 TemplateVersion |

CollectionVersion 必须包含：

- 规范化字段 Schema，包括类型、必填性和格式。
- 身份字段集合，至少一个非空字段。
- 指纹字段集合，用于判断内容是否变化。
- 字段完整度、长度、枚举、时间格式等质量门。
- 输出事件模式和允许的 Sink 类型。
- 可选 TemplateVersion 引用和相对模板的显式差异。

CollectionVersion 的任何字段、身份、质量或输出语义变化都必须创建新版本。现有 Collector 不自动升级到新 CollectionVersion。

### 3.3 Source 与访问聚合

| 对象 | 类型 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| Source | 聚合根 | 一个经授权站点或数据来源的稳定身份 | `(tenantId, canonicalName)` 唯一；不保存凭据明文 |
| SourceRevision | 不可变版本 | 入口、允许域名、传输、速率和合规声明快照 | 每次边界变化创建新 Revision；被 RuleVersion 引用后不得删除 |
| AccessProfile | 聚合根 | 访问配置的稳定身份 | 作用域限制在 Tenant；不直接作为执行输入 |
| AccessProfileVersion | 不可变版本 | 认证类型、注入位置、凭据作用域、代理引用和 Secret Manager 引用 | `Active` 后不可变；不保存可用 secret 明文 |
| Sink | 聚合根 | 输出目标的稳定身份 | 类型为 Kafka 或 Webhook；不直接保存可用凭据明文 |
| SinkVersion | 不可变版本 | 端点、Topic、签名、超时和交付策略快照 | 新 Delivery 必须固定 SinkVersion；历史 Delivery 不随配置变化 |

SourceRevision 必须声明：

- 一个或多个 `https`/`http` entrypoint。
- 完整的允许主机列表；不得使用无界通配符。
- `http` 或 `browser` 传输方式。
- 重定向、速率、并发、响应体积和请求超时边界。
- 合法访问依据、数据分类和 robots/站点条款处理策略。

AccessProfile 与 Source 分离。Secret material 轮换不要求新建 RuleVersion；认证类型、注入位置、允许 origin、path scope、代理地域或权限范围变化必须创建 AccessProfileVersion，并触发受影响 RuleVersion 重新验证。

### 3.4 Collector 与规则聚合

| 对象 | 类型 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| Collector | 聚合根 | SourceRevision 与 CollectionVersion 的执行绑定 | `(tenantId, collectionId, sourceId, logicalKey)` 唯一 |
| CollectorOverride | 不可变实体 | 作者态的受控例外 | 只能使用平台允许的类型；修改产生新 ID；不得包含代码或 secret |
| RuleVersion | 不可变版本 | Collector 的最终 GatherSpec | 发布后不可变；摘要必须有效；活动规则必须具有有效 RuleAttestation |
| CollectionPolicyVersion | 不可变版本 | 首次窗口、回看窗口、连续旧页停止与 Run 操作限额 | 创建后不可修改；Collector 只指向一个活动版本 |
| CollectorCheckpoint | 可变实体 | 同一 CollectionPolicyVersion 最近一次成功 Run 的 watermark | 只在成功终结事务中推进；切换 policy version 时重置 |
| RuleAttestation | 不可变实体 | 对 RuleVersion digest 与审批决定的发布证明 | 追加式；绑定 Tenant、RuleVersion、approval、purpose、keyId 和 signedAt |
| SigningKey | 聚合根 | 发布证明密钥的身份与信任状态 | 私钥不进入数据库；状态变化必须审计并触发影响分析 |
| Schedule | 实体 | Collector 的 Cron 触发配置 | 每次变更增加 `revision`；Run 固定触发时的配置摘要 |
| AiRun | 聚合根 | 一次规则生成或修复任务的稳定审计记录 | 固定 Collector、Source URL、触发原因和发起人；执行终态与审核终态分离 |
| AiAttempt | 实体 | AiRun 的一次 Worker 尝试 | `(aiRunId, attemptNumber)` 唯一；重试只追加，不覆盖历史 |
| ModelInvocation | 不可变实体 | 一次受控模型调用的用量与响应摘要 | 固定 purpose、provider、model、promptVersion、Token 和耗时；不保存原始提示词、样本或响应正文 |

Collector 持有 `activeRuleVersionId` 与 `activeCollectionPolicyVersionId`。发布或回滚通过同一数据库事务原子修改规则指针并写入 AuditEvent；RuleVersion 本身的状态和内容不回退。活动 RuleVersion 至少需要一个由当前可信 SigningKey 产生、未被撤销的 RuleAttestation。创建新的 CollectionPolicyVersion 原子切换策略指针并清空旧策略 Checkpoint。

Collector 对外投影必须携带稳定 `collectionId` 与 `collectionName`，使运营界面能够跨需求平铺处理异常，也能够按业务 Collection 筛选和分组。文件夹、收藏夹或标签不替代 Collection 归属；这类组织能力不改变规则、Run、Checkpoint 或谱系边界。

CollectorOverride 仅是编译输入。GatherSpec 保存 Override ID 与摘要作为谱系，并保存展开后的确定性行为；运行时不得读取可变 Override 来改变规则。

Operation 是异步命令的短期进度信封，不替代 AiRun。AiRun 的 `resultStatus` 表达是否生成候选规则，`reviewStatus` 独立表达尚未审核、待审核、已发布或已被替代。规则发布事务把最新待审核 AiRun 关联到 `publishedRuleVersionId`，并将更早待审核结果标记为 `superseded`。ModelInvocation 只记录排障、用量和审计所需元数据，敏感上下文留在受控 Artifact 边界而不进入任务列表投影。

### 3.5 执行与证据聚合

| 对象 | 类型 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| Run | 聚合根 | 一次固定输入的采集执行 | 创建时固定 RuleVersion、CollectionVersion、SourceRevision、Schedule Revision 和 runtimeVersion |
| RunAttempt | 实体 | Run 的一次基础设施级尝试 | `(runId, attemptNumber)` 唯一；attemptNumber 单调递增 |
| RunFinalization | 不可变实体 | 固定 Run 的 winning attempt、质量判定和提升集合 | 每个 Run 至多一个；accepted/rejected set 与 quality report 均以 digest 固定 |
| Artifact | 不可变实体 | raw、样本、日志片段、验证报告和证据 | 内容写入对象存储；数据库保存 digest、分类、大小、保留期和对象引用 |
| ArtifactManifest | 不可变实体 | 分级记录运行证据与 runtime 上下文 | 必须通过 `extrio.artifact-manifest.v1` Schema；只有完整 replayable 模式可回放；不得包含凭据 material |
| ArtifactManifestChunk | 不可变实体 | replayable Manifest 的有序响应证据分片 | 单片至多 1,000 个响应；tenant、序号、计数、digest 与 root 引用一致 |

RunAttempt 不代表单个 HTTP 请求。请求级重试属于 Attempt 内部；Attempt 只处理 Worker 丢失、进程崩溃或可恢复基础设施失败。

### 3.6 数据与交付聚合

| 对象 | 类型 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| HarvestItem | 聚合根 | 规范化实体的稳定身份与当前事件指针 | `entityKey` 在 Tenant、Collection、Source 范围内唯一；持有 currentEventId 和 eventSequence |
| HarvestItemRevision | 不可变版本 | 一个输出合同下的实体内容版本 | `(harvestItemId, outputContractDigest, payloadFingerprint)` 唯一 |
| HarvestObservation | 不可变实体 | Run 对实体版本的一次有效观察 | `(runId, harvestItemId)` 唯一；包含 Revision、RuleVersion、observedAt 和 occurrenceCount |
| ItemEvent | 不可变实体 | HarvestItem 的一次 `upsert` 或 `tombstone` 状态转换 | `(harvestItemId, eventSequence)` 唯一；previousEventId 形成事件链 |
| Delivery | 聚合根 | ItemEvent 发往一个 SinkVersion 的逻辑交付 | `(eventId, sinkVersionId)` 唯一；`deliveryId` 在所有尝试中不变 |
| DeliveryAttempt | 实体 | 一次实际发送 | `(deliveryId, attemptNumber)` 唯一；可选关联 RedeliveryRequest，保存响应分类和下次重试时间 |
| RedeliveryRequest | 聚合根 | 对既有 Delivery 的人工重新发送操作 | 记录原 Delivery、审批、原因、请求者和新 Attempt 范围 |

HarvestItem 不保存“最新网页即真相”的假设。每个 Revision 记录 `outputContractDigest`、规范化 payload 和 payloadFingerprint；每个 Observation 记录 runId、ruleVersionId、collectionVersionId、sourceRevisionId、observedAt 与同一 Run 的重复出现次数。内容未变化时不创建新 Revision 或 ItemEvent，但仍创建 Observation，保证 Run 到 Item 的可查询谱系。

v0.2 只有 Source 明确提供删除、撤销或失效信号时才产生 tombstone。列表中缺失一个历史实体不得自动解释为删除。

## 4. 关系模型

```text
Tenant
  ├─ Membership ─ User
  ├─ CollectionTemplate ─ TemplateVersion
  ├─ Collection ─ CollectionVersion
  ├─ Source ─ SourceRevision
  ├─ AccessProfile ─ AccessProfileVersion
  ├─ Sink ─ SinkVersion
  ├─ SigningKey ─ RuleAttestation
  └─ AuditEvent

Collection + CollectionVersion
  └─ Collector ─ Source + SourceRevision
       ├─ CollectorOverride
       ├─ RuleVersion ─ RuleAttestation
       └─ Schedule
            └─ Run ─ RunAttempt + RunFinalization
                 ├─ Artifact
                 └─ HarvestItem ─ HarvestItemRevision ─ HarvestObservation
                              └─ ItemEvent ─ Delivery ─ DeliveryAttempt
                                                              └─ RedeliveryRequest
```

关键基数：

- CollectionTemplate `1-N` TemplateVersion。
- Collection `1-N` CollectionVersion。
- Source `1-N` SourceRevision。
- AccessProfile `1-N` AccessProfileVersion。
- Collection `1-N` Collector；Source `1-N` Collector。
- Collector `1-N` RuleVersion、CollectionPolicyVersion、CollectorOverride、Schedule 和 Run，`0-1` CollectorCheckpoint；RuleVersion `1-N` RuleAttestation。
- RuleVersion `1-N` Run。
- Run `1-N` RunAttempt、Artifact 和 HarvestItemRevision；Run `0-1` RunFinalization。
- HarvestItem `1-N` HarvestItemRevision、HarvestObservation 和 ItemEvent；Revision `1-N` Observation、`0-N` ItemEvent。
- ItemEvent `1-N` Delivery；Delivery `1-N` DeliveryAttempt。
- Delivery `1-N` RedeliveryRequest；每个 Request 追加一个或多个 DeliveryAttempt。

## 5. 状态机

### 5.1 版本对象

| 对象 | 合法状态流 |
| --- | --- |
| TemplateVersion | `Draft -> Published -> Retired`；`Draft -> Rejected` |
| CollectionVersion | `Draft -> Validating -> Frozen -> Superseded`；`Draft/Validating -> Rejected` |
| SourceRevision | `Draft -> Validated -> Active -> Superseded`；`Draft/Validated -> Rejected` |
| AccessProfileVersion | `Draft -> Validated -> Active -> Superseded/Revoked` |
| SinkVersion | `Draft -> Validated -> Active -> Retired` |
| RuleVersion | `Draft -> Validating -> NeedsReview -> Published -> Retired`；`Draft/Validating/NeedsReview -> Rejected` |
| SigningKey | `Pending -> Trusted -> Retired/Compromised`；`Retired -> Compromised` |

`Published` RuleVersion 可以不再是活动版本，但不得回到草稿或被修改。`Retired` 表示不能用于新发布，不影响历史 Run 和回放。

### 5.2 稳定对象

| 对象 | 合法状态流 |
| --- | --- |
| Tenant | `Active <-> Suspended` |
| Collection | `Draft -> Active -> Archived` |
| Source | `Pending -> Active <-> Suspended -> Archived` |
| Collector | `Draft -> Compiling -> NeedsReview -> Active <-> Paused -> Archived` |
| Schedule | `Draft -> Active <-> Paused -> Archived` |

Archived 为终态。恢复业务必须创建新对象，不能复活归档对象并破坏历史含义。

### 5.3 运行与交付

| 对象 | 合法状态流 |
| --- | --- |
| Run | `Queued -> Running -> Finalizing -> Succeeded/PartiallySucceeded/Failed`；`Queued/Running -> Cancelled/TimedOut` |
| RunAttempt | `Pending -> Running -> Succeeded/Failed/Lost/Cancelled` |
| Delivery | `Pending -> Delivering -> Delivered/RetryScheduled/DeadLettered/Cancelled`；`RetryScheduled -> Delivering`；经批准 redelivery 成功时 `DeadLettered -> Delivered` |
| DeliveryAttempt | `Pending -> Sending -> Succeeded/RetryableFailure/PermanentFailure/UnknownOutcome` |
| RedeliveryRequest | `Requested -> Approved -> Executing -> Completed/Failed/Cancelled`；`Requested -> Rejected` |

只有满足所有强制质量门且采集阶段没有未处理失败的 Run 才能进入 `Succeeded`。Delivery 状态不改变 Run 的采集结果；UI 必须分别展示采集与交付状态。

## 6. 身份、指纹与唯一约束

### 6.1 逻辑实体键

```text
entityKey = sha256(
  tenantId + "\n" +
  collectionId + "\n" +
  sourceId + "\n" +
  canonical({fieldName: typedValue, ...})
)
```

- identity canonical object 必须包含字段名、类型和值；字段名按 JCS 排序，禁止仅拼接无字段名值数组。
- `null`、缺失和空字符串不得作为合法身份值。
- URL 身份字段必须先执行规则声明的 URL 规范化。
- 变更身份规则必须创建 CollectionVersion，并且不会自动合并历史实体。

### 6.2 输出合同与 payload 指纹

```text
outputContractDigest = sha256(canonical({
  normalizedItemSchema,
  identityFields,
  fingerprintFields,
  eventSemantics: {
    emitUnchanged,
    eventTypes,
    tombstonePolicy
  }
}))

payloadFingerprint = sha256(canonical({
  fingerprintFieldName: typedValue,
  ...
}))

revisionKey = sha256(
  entityKey + "\n" +
  outputContractDigest + "\n" +
  payloadFingerprint
)
```

`eventTypes` 由 CollectionVersion 事件合同决定，按 UTF-8 字节序排序；v0.2 无 tombstonePolicy 时为 `["upsert"]`，存在时为 `["tombstone","upsert"]`。`tombstonePolicy` 不存在时取 JSON `null`。Sink 绑定和交付策略不属于 outputContractDigest；同一 `revisionKey` 的观察不会创建新 Revision，但必须创建 HarvestObservation。CollectionVersion 的质量门、描述或调度变化不改变 outputContractDigest；输出 Schema、身份、指纹字段或上述事件语义变化必须改变 outputContractDigest。

### 6.3 事件转换与交付键

```text
eventId = sha256(
  entityKey + "\n" +
  (previousEventId || "GENESIS") + "\n" +
  revisionKey + "\n" +
  eventType
)

deliveryId = sha256(eventId + "\n" + sinkVersionId)
```

事件创建必须在锁定 HarvestItem 的事务中执行：目标 `(revisionKey, eventType)` 与 currentEvent 相同时复用当前事件；不同时递增 eventSequence、引用 previousEventId 并创建新 ItemEvent。因此 A→B→A 与 `upsert→tombstone→upsert` 都产生新的状态转换事件，即使历史 Revision 被复用。

所有自动重试和同 SinkVersion 的人工 redelivery 复用同一个 `deliveryId`。Webhook 必须把它放入 `Idempotency-Key`；Kafka 必须用 `eventId` 作为消息键，并在消息体中携带 `deliveryId`。只有目标 SinkVersion 改变时才创建新的 Delivery。

同一 Run 中，同一 entityKey 和 revisionKey 的重复 candidate 合并为一个 Observation 并增加 `occurrenceCount`。同一 entityKey 出现不同 revisionKey 时产生 `ITEM_IDENTITY_CONFLICT`，该实体的本次候选全部拒绝，不得通过“最后一个覆盖”形成不确定结果。

## 7. 时间与并发规则

- 所有持久时间使用 UTC、RFC 3339 纳秒精度；用户界面可以按租户时区显示。
- 更新稳定对象必须使用乐观并发版本 `rowVersion`；冲突返回明确错误，不得最后写入覆盖。
- Schedule 触发与 RuleVersion 发布并发时，Run 创建事务读取并固定当时的 `activeRuleVersionId`。
- v0.2 的 Collector 固定 `overlapPolicy=forbid`。GatherSpec 固定分页与提取行为，CollectionPolicyVersion 固定运行窗口和预算；Run 从第一页开始，使用日期 watermark 与回看窗口，并在成功终结时推进 CollectorCheckpoint。通用 cursor、无限滚动和任意增量表达式不在当前范围。

## 8. 删除、保留与谱系

- Stable object 的归档不删除其版本、Run、Item、Delivery、Artifact 元数据或 AuditEvent。
- 租户数据删除遵循安全合同中的验证、保留和备份清除窗口。
- 删除 Collection 不自动删除共享 Source、AccessProfile 或 Sink。
- 物理删除前必须验证没有合法保留、争议保全或审计要求。
- 从 Delivery 必须能够反向定位 ItemEvent、HarvestItemRevision、HarvestObservation、Run、RuleVersion、Collector、SourceRevision、CollectionVersion 和 Tenant。
- Artifact 内容过期后仍保留最小元数据和 digest，以说明证据曾经存在以及何时按策略删除。

## 9. 数据库与 API 约束

- API 不得允许客户端直接设置已发布状态、摘要、签名、审计 actor 或租户归属。
- 外键除 Tenant 删除流程外默认使用 `RESTRICT`；历史对象不得级联删除。
- 状态转换、活动版本指针、AuditEvent 和 outbox 事件必须位于同一 PostgreSQL 事务。
- Redis 中的任务只能引用数据库中的不可变 job envelope，不是领域对象的权威副本。
- API 列表和批量导入必须具有稳定分页、逐项结果和部分失败报告。

## 10. 模型验收

领域模型实现必须证明：

1. 跨租户外键和对象引用被数据库或服务边界拒绝。
2. 已冻结或已发布版本无法更新。
3. 发布与回滚不会改变运行中的 Run。
4. 并发触发不会创建重复的同一 Schedule occurrence Run。
5. 相同 Item 和 Delivery 重试复用稳定键，Collection 输出合同变化产生新的 revisionKey。
6. Run 的采集结果与 Delivery 的交付结果独立且可追溯。
7. 归档和租户删除满足保留策略，不产生孤立 Artifact 或无法解释的审计记录。
8. 同一 SinkVersion 的人工重新交付只追加 RedeliveryRequest 和 DeliveryAttempt，不违反 Delivery 唯一约束。
9. A→B→A 和 tombstone 后恢复产生不同 eventId，重复提交同一状态转换复用已提交事件。
10. Failed、Cancelled 或 TimedOut Run 不释放 Delivery；Succeeded/PartiallySucceeded 只交付 finalization 决定接受的 Item。
