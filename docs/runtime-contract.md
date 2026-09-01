# Extrio 运行时合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v0.6.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Confirmed` |
| 权威来源 | [`SSOT.md`](./SSOT.md) |
| 关联需求 | `FR-005` 至 `FR-015`，`NFR-001` 至 `NFR-013` |
| 最后更新 | `2026-08-31` |
| 审批责任 | 技术负责人、产品负责人 |

## 2. 运行时确定性的定义

Extrio 的确定性指规则和处理逻辑确定，而不是声称外部网络或 Source 内容不变化。

在以下输入一致时，运行时必须产生相同的请求计划、字段提取、规范化、身份键、内容指纹和事件判定：

- RuleVersion 的 canonical GatherSpec。
- CollectionVersion 与 SourceRevision。
- runtimeName、runtimeVersion、parserVersion、dialectVersion、tzdbVersion 和 Unicode 数据版本。
- 相同的响应字节、状态码、Header 和时间上下文。

运行时不得：

- 调用 LLM 或编译 Agent。
- 执行 Rule 中未声明的自适应选择器或回退策略。
- 执行用户提交的 Python、JavaScript、Shell 或动态插件。
- 修改 RuleVersion、CollectionVersion 或 SourceRevision。
- 因重试次数不同而改变标准化结果。

## 3. 编译、验证与发布

### 3.1 编译输入

每个编译任务必须固定：

- Tenant、Collector、CollectionVersion 和 SourceRevision ID。
- AccessProfileVersion ID、配置 digest 与认证类型，不包含 secret 明文。
- CollectorOverride ID 与 digest。
- 编译器、Agent provider/model、promptVersion 和 toolchainVersion。
- 样本来源、获取时间、ArtifactManifest ID 与 digest。

### 3.2 编译输出

编译任务必须产生：

1. 满足 [`contracts/gather-spec.schema.json`](./contracts/gather-spec.schema.json) 的 GatherSpec。
2. 语义校验报告，包括字段引用、身份、分页、预算、域名和 Sink 检查。
3. 最少一个成功样本 Artifact 与可验证 ArtifactManifest；失败样本必须保留为评审证据。
4. 字段级预览、必填完整度、身份唯一率、outputContractDigest 和 payloadFingerprint 结果。
5. canonical ruleDigest、独立 RuleAttestation 和完整编译谱系。

### 3.3 发布门

RuleVersion 只有同时满足下列条件才能发布：

- Schema 和语义校验全部通过。
- 安全检查确认 entrypoint、redirect、AccessProfileVersion、外部 `$ref` 禁止和资源预算合法。
- 样本中身份字段有效率为 100%。
- 样本必填字段完整度达到 CollectionVersion 门槛，默认不低于 95%。
- RuleReviewer 明确批准，受保护 Collection 满足四眼审批。
- ruleDigest 校验成功，并存在由当前 Trusted SigningKey 生成的有效 RuleAttestation。

发布事务必须原子记录 RuleVersion 状态、RuleAttestation 引用、Collector 活动版本指针、AuditEvent 和 outbox 事件。签名服务调用先于事务完成；失败时不得出现“已发布但未激活”“已激活但无有效证明”或“已激活但无审计”的中间状态。

### 3.4 回滚

回滚选择一个仍受当前 runtime 支持的历史 Published RuleVersion，并原子修改 Collector 活动版本指针。回滚不得修改历史 GatherSpec；如果历史证明不能授权新 Run，发布服务必须使用当前 Trusted key 追加新的 RuleAttestation 后再切换。已经创建的 Run 继续使用其固定版本和证明。

## 4. 调度与 Run 创建

### 4.1 Schedule occurrence

每个 Cron occurrence 使用以下稳定键：

```text
occurrenceKey = sha256(scheduleId + "\n" + scheduleRevision + "\n" + scheduledAtUTC)
```

数据库对 `occurrenceKey` 建立唯一约束。调度器恢复、重复扫描或主备切换不得创建重复 Run。

### 4.2 创建前检查

调度器必须确认：

- Tenant、Collection、Source、Collector 和 Schedule 允许执行。
- Collector 存在活动 Published RuleVersion。
- RuleVersion 的 Schema 主版本受当前 runtime 支持。
- AccessProfileVersion、SinkVersion、RuleAttestation 和合规授权未失效。
- Tenant、Source、Collector 和传输类型配额允许执行。
- 同一 Collector 不存在非终态 Run；v0.2 固定 `overlapPolicy=forbid`。

检查失败必须记录 `Skipped` 调度结果和稳定原因码，不得创建一个注定无法执行的 Run。

### 4.3 版本固定

Run 创建事务必须保存：

- RuleVersion ID、ruleDigest、RuleAttestation ID、SigningKey ID 与信任注册表 revision。
- CollectionVersion、SourceRevision、Collector 和 Schedule Revision。
- runtimeName、runtimeVersion、parserVersion、dialectVersion、tzdbVersion、Unicode 版本和 job envelope digest。
- 触发类型、触发者和 occurrenceKey，以及固定的 CollectionPolicyVersion、执行模式、窗口下界和 Checkpoint 前值。
- AccessProfileVersion ID 与 digest、SinkVersion 集合。

队列只传递符合 [`contracts/platform-protocol.md`](./contracts/platform-protocol.md) 的不可变 job envelope。Worker 必须从控制面获取并再次校验固定上下文。

## 5. Worker 执行协议

### 5.1 租约与心跳

- Worker 通过原子 claim 获得 RunAttempt 租约；同一 Attempt 同时只能有一个有效 lease owner。
- 默认租约 60 秒，每 20 秒续约；数值可配置但续约间隔必须小于租约的一半。
- Worker 失联且租约过期后，Attempt 标记为 `Lost`，控制面按 Run 重试策略决定是否创建新 Attempt。
- 旧 Worker 恢复后必须因 fence token 失效而停止写入，不得覆盖新 Attempt 状态。

### 5.2 请求执行

每次请求必须应用：

- SourceRevision 和 GatherSpec 的允许主机、重定向、速率、并发、超时和最大响应体积。
- AccessProfileVersion 的任务级凭据注入；注入发生在发送前，凭据不得进入 URL、请求计划日志或 Artifact。
- 全局、Tenant、Source 和 Collector 四级限流，以最严格结果为准。
- requestId、runId、attemptId、collectorId 和 ruleVersionId trace context。

HTTP 重试只适用于明确的瞬时错误：连接失败、超时、`408`、`429` 和经策略允许的 `5xx`。默认最多 3 次，采用带抖动指数退避，并尊重合法 `Retry-After`。认证失败、未授权域名、Schema 错误、页面结构错误和响应过大不得盲目重试。

### 5.3 分页与预算

- `page` 分页按声明的参数、起始值和步长生成请求，到达 `maxPages`、空页、重复页指纹或总预算时停止。
- `next_link` 分页只接受规则选择器提取的 URL；每次 URL 规范化后重新执行主机和重定向检查。
- Worker 必须检测规范化 URL 循环和重复响应摘要。
- 任意一项 `maxPages`、`maxItems`、`maxDurationSeconds` 或租户配额达到时结束采集，并根据规则的预算策略标记 `PartiallySucceeded` 或 `Failed`。
- 不得以截断成功掩盖预算耗尽。

### 5.4 list/detail

1. list 响应生成候选 item，并先提取身份、detail URL 和 list 阶段字段。
2. 身份字段缺失的候选 item 立即按 `onError` 拒绝或使 Run 失败。
3. detail 请求必须继承 Source 安全边界；detail URL 不得扩展允许主机。
4. detail 字段与 list 字段合并时，规则中显式声明的 detail 字段优先；冲突必须在编译期验证。
5. 所有字段完成类型转换和 transforms 后，再进行质量门、entityKey、outputContractDigest 和 payloadFingerprint 计算。

## 6. 结果暂存、终结与 Observation

### 6.1 Result staging

Worker 按 [`contracts/result-batch.schema.json`](./contracts/result-batch.schema.json) 提交 ResultBatch，控制面先写入 Run/Attempt 隔离的 staging 区：

- `(runId, attemptId, batchId)` 唯一；同 ID 不同 digest 是协议错误。
- staging 只保存 candidate digest、对象引用、错误和统计，不创建 HarvestItem、Observation、Revision、ItemEvent、Delivery 或 outbox。
- 只有持有当前 fenceToken 的 Attempt 可以追加批次或请求 finalization；旧 Attempt 的 staging 永不提升。
- 同一 Run 内相同 entityKey/revisionKey 的重复 candidate 合并并累计 occurrenceCount；相同 entityKey 对应不同 revisionKey 时产生 `ITEM_IDENTITY_CONFLICT`，该实体的候选全部拒绝。

原始 payload 写入对象存储后，数据库只保存对象引用、大小、分类、object version 和 digest。对象上传失败时不得提交声称可回放的 ArtifactManifest。

### 6.2 增量窗口与 Checkpoint

- GatherSpec 决定如何分页和提取；独立且不可变的 CollectionPolicyVersion 决定首次窗口、回看窗口和运行限额。Run 必须固定二者的版本与 digest。
- 首次运行默认以 Run 开始时间减 30 天为下界；具有相同 policy version 的后续运行以最近成功 watermark 减 3 天为下界。
- Worker 每次从列表第一页开始，不把易漂移的页码作为 Checkpoint。日期降序列表连续两页全部早于下界时，以 `time_window_reached` 或 `checkpoint_reached` 正常停止。
- `max_pages`、`max_items`、时长或字节预算停止属于截断，不得伪装为完整成功，也不得推进 Checkpoint。
- Checkpoint 只在 Run、Item、Collector 终态共同提交的成功事务中推进；失败、取消、超时和部分成功保持原值。
- 回看窗口内相同 entityKey 仍重新获取；内容未变记录 `unchanged`，指纹变化追加 Revision 并记录 `updated`。

### 6.3 Run finalization

控制面收到带 final batch digest 的 finalize 命令后：

1. 固定 staging 集合并计算候选数、冲突、字段完整度、错误比例、预算和最终质量门。
2. Succeeded 接受全部有效 candidate；PartiallySucceeded 只接受合同允许的有效 candidate；Failed、Cancelled 和 TimedOut 默认不提升生产数据或 Delivery，只保留 staging 证据和统计。
3. 创建不可变 RunFinalization 决定，记录 outcome、accepted set digest、rejected set digest、quality report digest 和 winning attempt。
4. 按稳定 entityKey 顺序分批提升 accepted set：创建/定位 HarvestItem 与 Revision，创建 Observation，并在锁定 HarvestItem 后按当前状态决定是否创建新的 ItemEvent。
5. 对当前 ItemEvent 和 Run 固定的适用 SinkVersion 幂等创建 Delivery/outbox，但 outbox 在全部提升完成前保持不可分发。
6. 最后一个短事务把 RunFinalization 标记 Complete、写入 Run 终态并释放 outbox。中断后按 batch digest 幂等续跑；Run 在此之前保持 Finalizing。

Run 进入 Finalizing 后，取消是 best effort，不得撤销已经持久化的 finalization 决定。accepted set 提升或 outbox 释放发生基础设施故障时，Run 保持 Finalizing 并幂等恢复，不得在部分提升后改写为 Failed。新增 SinkVersion 可以在下一次有效 Observation 时为当前 ItemEvent 创建缺失 Delivery，不伪造新事件。

## 7. 幂等与交付语义

entityKey、outputContractDigest、payloadFingerprint、revisionKey、eventId 和 deliveryId 的算法由 [`domain-model.md`](./domain-model.md) 定义。

### 7.1 平台承诺

- 采集和交付采用 at-least-once。
- 相同事件的重复执行必须复用 `eventId` 和 `deliveryId`。
- Extrio 不承诺外部 Sink 端到端 exactly-once。
- 未确认结果不得被静默标记为 Delivered。

### 7.2 Kafka

- Kafka message key 必须为 `eventId`。
- 消息体必须符合 [`contracts/item-event-envelope.schema.json`](./contracts/item-event-envelope.schema.json)，并与 Webhook 使用相同结构和 canonicalization。
- Producer 应启用幂等发送和 `acks=all`；成功仅以 broker ack 为准。
- Unknown outcome 必须按同一 deliveryId 重试，消费者应按 eventId 去重。

### 7.3 Webhook

- 只允许 HTTPS endpoint。
- 请求必须带 `Idempotency-Key: <deliveryId>`、`Content-Digest: <messageDigest>`、`Extrio-Timestamp` 和 `Extrio-Signature`；签名输入与编码以 [`contracts/platform-protocol.md`](./contracts/platform-protocol.md) 为准。
- `2xx` 视为确认成功；`408`、`429` 和策略允许的 `5xx` 可重试；其他 `4xx` 默认为永久失败。
- 网络断开且无法判断远端是否处理时记录 `UnknownOutcome`，复用 deliveryId 重试。

### 7.4 Delivery 重试

默认最多 8 次，使用带抖动的指数退避，最长延迟 6 小时，总重试窗口 48 小时。超过窗口或遇到永久错误进入 `DeadLettered` 并告警。同一 SinkVersion 的人工重新交付创建 RedeliveryRequest，并在原 Delivery 下追加 DeliveryAttempt；`eventId` 与 `deliveryId` 均保持不变。Delivered redelivery 不改变 Delivery 状态，由 RedeliveryRequest 单独记录结果；DeadLettered redelivery 只有成功后才把 Delivery 原子更新为 Delivered，失败仍保持 DeadLettered。只有目标 SinkVersion 改变时才创建新 Delivery。

## 8. Run 结果判定

| 状态 | 判定 |
| --- | --- |
| Succeeded | 采集阶段完成、强制质量门通过、没有未处理 item 错误；Delivery 可以继续异步处理 |
| PartiallySucceeded | 产生有效结果，但预算耗尽、部分请求失败或非强制字段错误超过规则门槛 |
| Failed | 无有效结果、身份或强制质量门失败、规则/安全错误，或失败比例超过规则门槛 |
| Cancelled | Finalizing 前收到取消并完成安全停止；staging 与证据保留，不提升 Item 或 Delivery |
| TimedOut | Finalizing 前达到 Run 最大时长；staging 与证据保留，不提升 Item 或 Delivery |

Run 必须保存候选数、成功 item 数、拒绝 item 数、未变化 item 数、各错误类别、请求统计、字节数和分页停止原因。

## 9. 漂移检测与处置

Collector 在至少 3 个成功 Run 后进入 `BaselineReady`，使用最近 14 个成功 Run 的滚动基线。在此之前状态为 `BaselineBuilding`，不应用依赖历史分布的阈值，但安全错误、身份字段失效、强制质量门失败和单 Run 结构提取失败比例超过 50% 仍立即告警。`BaselineReady` 后满足任一条件时记录 `DriftSuspected`：

- 连续 2 个计划 Run 结果为 0，而基线中位数大于 10。
- 连续 2 个计划 Run 的必填字段完整度低于 CollectionVersion 门槛。
- 单 Run 结构提取失败比例超过 50%。
- HTTP 封禁、验证码或登录页识别比例超过 50%。
- Item 数量相对基线中位数变化超过 80%，且绝对差异超过 20。

出现以下任一情况时自动暂停 Schedule：连续 3 个 Run Failed；检测到凭据泄露或越界请求；RuleAttestation 失效；跨租户校验失败。其他漂移默认告警，不自动发布新规则。

Schedule 间隔不超过 12 小时时，漂移发现目标是不超过 2 个计划 Run 且最长 24 小时；间隔更长时仅使用“不超过 2 个计划 Run”衡量，不承诺 24 小时内发现。跳过或未执行的 occurrence 不计为已检测 Run，但必须单独告警调度滞后。

恢复流程为：采集新样本、创建新 RuleVersionDraft、验证、人工批准、金丝雀 Run、切换活动版本。不得在运行中自动替换选择器。

## 10. 回放

| 模式 | 副作用 | 权限 | 用途 |
| --- | --- | --- | --- |
| `validate_only` | 不写 HarvestItem、Delivery 或生产 namespace | Operator | 使用 ArtifactManifest 验证相同或候选规则 |
| `reprocess` | 创建带 replay lineage 的 ItemRevision；默认不交付 | Operator + RuleReviewer | 修复规范化或数据合同问题 |
| `redeliver` | 不重新采集；追加 RedeliveryRequest 和 DeliveryAttempt | RuleReviewer | 修复 Sink 交付问题 |

只有 `evidenceMode=replayable`、`completeness.complete=true`、所有 chunk 连续且全部引用 Artifact 可验证的 ArtifactManifest 才能进行证据等价回放。回放必须固定 Manifest ID/digest、全部 chunk 与 Artifact digest、RuleVersion、runtime/parser/dialect/tzdb/Unicode/浏览器上下文版本、发起人和原因。条件不满足时系统只能创建新的实时 Run，不能标记为历史证据回放。

## 11. 可观测性与告警

### 11.1 指标

- 调度：`schedule_dispatch_delay_seconds`、`runs_queued`、`queue_lag_seconds`。
- 运行：`run_duration_seconds`、`run_outcomes_total`、`items_observed_total`、`items_rejected_total`。
- Source：`source_requests_total`、`source_request_duration_seconds`、`source_response_bytes`。
- 质量：`required_field_completeness`、`identity_rejection_ratio`、`drift_signals_total`。
- 交付：`deliveries_total`、`delivery_attempts_total`、`delivery_age_seconds`、`dead_lettered_total`。
- 安全：`egress_blocks_total`、`secret_access_failures_total`、`attestation_failures_total`。

常驻指标标签只允许有限集合，例如 environment、region、transport、outcome、errorClass 和 sinkType。Tenant、Collector、Run、URL 和 Item 维度通过日志或 trace 查询，不作为无界指标标签。

### 11.2 默认告警

- Schedule dispatch delay `p99 > 15 分钟` 持续 15 分钟。
- 队列最老任务年龄超过 15 分钟。
- Collector 连续 3 次 Run Failed。
- Delivery 最老待处理时间超过 30 分钟，或出现 DeadLettered。
- RuleAttestation 失败、越界网络请求、跨租户拒绝或凭据泄露信号立即告警。
- 单 Collector 24 小时 raw 体积超过过去 7 个同类日中位数的 3 倍且绝对增长超过 1 GiB。

每个告警必须链接到 Tenant、Collection、Collector、RuleVersion、Run/Delivery 和证据，但敏感 URL 与凭据不得进入通知正文。

## 12. 灾备与恢复

- PostgreSQL 使用持续归档或等效机制，实现元数据 `RPO <= 15 分钟`、`RTO <= 4 小时`。
- 对象存储启用版本保护、生命周期和跨故障域备份，实现 Artifact `RPO <= 24 小时`、`RTO <= 8 小时`。
- Redis 丢失不得造成领域数据丢失；dispatcher 必须从 PostgreSQL outbox 和非终态记录重建队列。
- 每季度至少执行一次数据库恢复、对象 Artifact 校验和队列重建演练。
- 恢复后必须使用 occurrenceKey、eventId 和 deliveryId 防止重复副作用。

## 13. 运行时验收

实现必须用自动化或演练证明：

1. LLM 和编译依赖在 Worker 网络策略中不可达。
2. 重复调度、Worker 丢失和重复消息不会创建不同幂等键。
3. RuleVersion 切换不影响已经创建的 Run。
4. 未授权重定向、响应过大和分页循环被确定性阻断。
5. UnknownOutcome Delivery 复用相同 deliveryId。
6. 同 SinkVersion 人工重新交付不创建重复 Delivery，只追加 RedeliveryRequest 和 Attempt。
7. 输出合同变化会创建新的 revisionKey，未变化执行仍创建 Observation。
8. 证据等价回放只消费完整 `replayable` ArtifactManifest 及连续有效 chunks，并严格遵守副作用边界。
9. PostgreSQL 恢复后可以重建队列，并在设计容量下达到 SLO。
