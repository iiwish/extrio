# Extrio 平台消息协议

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v1.2.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Ready_For_User_Review` |
| 权威来源 | [`../SSOT.md`](../SSOT.md) 中的 `INV-003`、`INV-004`、`INV-005`、`INV-006`、`INV-009` |
| 最后更新 | `2026-08-30` |
| 审批责任 | 技术负责人、安全负责人 |

## 2. 适用边界

本合同定义 FastAPI 控制面与隔离的 Python 编译/执行 Worker 之间的消息和回调约束。领域对象仍以 PostgreSQL 为权威；Redis Streams 只传递可重建的任务通知，不承载可变业务状态或 secret。

本合同的机器可校验边界由 [`job-envelope.schema.json`](job-envelope.schema.json)、[`result-batch.schema.json`](result-batch.schema.json)、[`platform-error.schema.json`](platform-error.schema.json) 和 [`item-event-envelope.schema.json`](item-event-envelope.schema.json) 冻结。控制面、Worker 与 TypeScript 客户端合同工具必须使用这些 Schema 和共享 fixtures 验证 canonical bytes；本文定义跨对象语义，Schema 定义字段闭集。

## 3. JobEnvelope

所有 compile、run、validation replay 任务使用同一外层 envelope：

机器合同与签名样例分别见 [`job-envelope.schema.json`](job-envelope.schema.json)、[`job-envelope.example.json`](job-envelope.example.json) 和 [`job-envelope.example.public-key.pem`](job-envelope.example.public-key.pem)。

| 字段 | 约束 |
| --- | --- |
| `schemaVersion` | 固定为 `extrio.job-envelope.v1` |
| `messageType` | `compile`、`run` 或 `validation_replay` |
| `messageVersion` | 该 payload 的 SemVer 版本 |
| `jobId` | 稳定任务 ID；重投不得改变 |
| `tenantId` | 不可为空，必须与所有引用对象一致 |
| `payloadRef` | 控制面只读 API 中的不可变 payload ID |
| `payloadDigest` | payload canonical bytes 的 SHA-256 |
| `audience` | 固定目标服务身份，禁止通配符 |
| `fenceToken` | 控制面单调生成；旧租约不能提交结果 |
| `issuedAt` / `expiresAt` | UTC RFC 3339；过期任务不得执行 |
| `nonce` | 每次投递唯一，用于检测 envelope 重放；不参与 job 幂等身份 |
| `traceparent` | 可选 W3C trace context，不作为权限依据 |
| `attestation` | 包含固定 purpose、Ed25519 algorithm、keyId、signerServiceId、signedAt、envelopeDigest 与 signature |

消息体不得包含凭据、完整 GatherSpec、Source 响应、用户 token 或 Sink secret。Worker 用 mTLS 工作负载身份读取 payload，并同时验证 tenantId、jobId、payloadDigest、audience、期限和 fenceToken。

## 4. Canonicalization 与签名

- Envelope digest 对删除 `/attestation` 后的 RFC 8785 JCS bytes 计算。
- 签名输入为 `UTF8("extrio.job-envelope.v1\n") || JCS(attestation 删除 /signature)`；签名覆盖 purpose、算法、key、服务身份、signedAt 与包含 `sha256:` 前缀的 envelopeDigest。
- 签名身份与 RuleAttestation key 分离，不得让消息签名获得规则发布权限。
- nonce 重复、过期、audience 不匹配或 digest 不一致时，Worker 必须在执行任何请求前拒绝。
- `issuedAt < expiresAt`，`attestation.signedAt` 不得晚于 `issuedAt`；默认最大 envelope 有效期为 5 分钟，更长有效期必须由 messageType policy 显式允许。

## 5. 领取、心跳与结果

- Redis consumer group 领取只是候选所有权；有效执行权来自控制面租约和 fenceToken。
- 心跳必须包含 jobId、attemptId、workerId、fenceToken、阶段、计数和时间，不包含 payload 或 URL。
- 结果按 [`result-batch.schema.json`](result-batch.schema.json) 提交；批次只引用不可变 candidate/error artifacts，不内嵌大 payload。
- 同一 Attempt 的批次从 `batchSequence = 0` 开始，后续批次的 `previousBatchDigest` 必须等于上一批 `batchDigest`，序号必须连续且仅有最后一批 `isFinal = true`。
- `batchDigest` 是删除 `/batchDigest` 后对 ResultBatch RFC 8785 JCS bytes 计算的 SHA-256；`candidateCount = validCount + rejectedCount = candidateArtifact.itemCount`，存在 errorArtifact 时其 `errorCount = rejectedCount`。
- 控制面对 `(runId, attemptId, batchId)` 建唯一约束；同 ID 不同 digest 是协议违规并触发安全事件。
- 最终结果只引用已落库 Item、ArtifactManifest、错误摘要和统计，不以内嵌大 payload 替代对象存储。

## 6. 错误协议

错误 envelope 必须符合 [`platform-error.schema.json`](platform-error.schema.json)，包含 tenantId、稳定 `code`、`category`、`retryable`、`stage`、`requestId`、`jobId`、`attemptId` 和安全的 detail。禁止包含 secret、完整敏感 URL、响应正文或用户内容。

`errorDigest` 是删除 `/errorDigest` 后对错误 envelope RFC 8785 JCS bytes 计算的 SHA-256。`retryable=true` 只表达错误分类允许重试，不授权绕过 Attempt、租约、预算或审批策略。

只有明确的传输/基础设施错误可以由控制面创建新 Attempt。Schema、租户、签名、安全边界、runtime 不兼容或 deterministic extraction 错误不得通过盲目重试改变结果。

## 7. ItemEvent 输出合同

Kafka 与 Webhook 使用相同的 [`item-event-envelope.schema.json`](item-event-envelope.schema.json) 与 canonicalization；每个 SinkVersion 的 delivery binding 是目标特定字段。正例见 [`item-event-envelope.example.json`](item-event-envelope.example.json)。`payload` 必须通过该消息所引用 `outputContractDigest` 对应的 `normalizedItemSchema`，并满足以下约束：

- `payloadDigest` 是 `payload` RFC 8785 JCS bytes 的 SHA-256。
- `messageDigest` 是删除 `/messageDigest` 后整个 envelope 的 RFC 8785 JCS SHA-256。
- `eventSequence`、`previousEventId` 和 `eventId` 必须与 HarvestItem 的持久化状态转换链一致；lineage 与 Delivery 引用必须同租户。
- `entityKey`、`revisionKey`、`eventId` 和 `deliveryId` 必须按 [`../domain-model.md`](../domain-model.md) 重新计算；`eventSequence=1` 时 `previousEventId=null`，后续事件必须引用上一序号的 eventId。
- Kafka message key 固定为 `eventId`，消费者以 `delivery.deliveryId` 幂等消费。
- Webhook 请求的 `Idempotency-Key` 固定为 `delivery.deliveryId`，`Content-Digest` 固定为 `messageDigest`。
- Webhook 使用 SinkVersion 独立 secret 执行 HMAC-SHA256。签名输入为 `UTF8("extrio.webhook.v1\n") || ASCII(timestamp) || UTF8("\n") || ASCII(messageDigest)`，输出采用 base64url 无 padding，并放入 `Extrio-Signature: v1=<signature>`；`Extrio-Timestamp` 为 UTC Unix 秒。接收方必须校验允许时间偏差、digest 和 deliveryId 重放。

## 8. 演进与验收

- 未知主版本、未知 messageType、未知 enum 或额外字段默认拒绝。
- 可选字段只能在旧消费者明确安全忽略时加入；行为语义变化必须升级 messageVersion。
- FastAPI 控制面、Python Worker 与 TypeScript 合同测试必须共享 JobEnvelope、ResultBatch、PlatformError、ItemEvent 的正例，以及篡改、过期、跨租户、旧 fenceToken、断链 batch、事件链断裂和 unknown outcome 反例 fixtures。
- 验收必须证明任务重复投递不会创建重复 Run，失效 Worker 不能写入，且队列泄露不暴露 secret 或可执行 payload。
