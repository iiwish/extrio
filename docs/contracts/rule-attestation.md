# Extrio RuleAttestation v1 合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 规范标识 | `extrio.rule-attestation.v1` |
| 文档版本 | `v1.1.0` |
| 状态 | `Ready_For_User_Review` |
| JSON Schema | [`rule-attestation.schema.json`](./rule-attestation.schema.json) |
| 权威来源 | [`../SSOT.md`](../SSOT.md) 中的 `INV-002`、`INV-003`、`INV-007` |
| 最后更新 | `2026-08-30` |
| 审批责任 | 技术负责人、安全负责人 |

## 2. 目的与边界

RuleAttestation 是发布服务对不可变 RuleVersion digest、审批决定和评审策略的追加式发布证明。签名不内嵌到 GatherSpec，因此密钥轮换、吊销和重新证明不会修改 RuleVersion。

RuleAttestation 证明指定发布目的下的规则完整性以及被签名的审批事实，不替代 GatherSpec Schema、语义、安全、租户引用或 runtime 兼容性校验。

## 3. 字段语义

| 字段 | 语义 |
| --- | --- |
| `schemaVersion` | 固定为 `extrio.rule-attestation.v1` |
| `attestationId` | 不可变证明 ID，在 Tenant 内唯一 |
| `tenantId` | RuleVersion 所属 Tenant；必须与 job envelope 一致 |
| `ruleVersionId` | 被证明的不可变 RuleVersion |
| `ruleDigest` | 按 GatherSpec 合同重新计算得到的 SHA-256 digest |
| `approval` | 被签名的批准决定、提交者、审核者、策略和证据摘要 |
| `purpose` | 固定为 `extrio-rule-publish-v1`，防止跨协议复用签名 |
| `keyId` | SigningKey 信任注册表中的公钥 ID |
| `algorithm` | v1 固定为 `Ed25519` |
| `signedAt` | 发布服务完成签名的 UTC RFC 3339 时间 |
| `expiresAt` | 可选的证明失效时间；存在时必须晚于 `signedAt` |
| `signature` | 无 padding 的 base64url Ed25519 签名 |

## 4. Canonical payload 与签名

1. 深拷贝 RuleAttestation。
2. 删除 JSON Pointer `/signature`。
3. 使用 RFC 8785 JCS 生成 UTF-8 bytes。
4. 构造签名输入：`UTF8("extrio.rule-attestation.v1\n") || canonicalBytes`。
5. 使用 `keyId` 对应的 Ed25519 私钥签名，并以无 padding base64url 编码。

发布服务必须从控制面已确认的 RuleVersion 读取 `ruleDigest`，不得接受客户端提交的摘要或签名。私钥保存在 KMS/HSM 或等价受控签名服务中，不进入应用数据库、队列或 Artifact。

`approval` 必须包含：

- `decisionId` 和固定的 `decision=approved`。
- `submitterSubjectId` 与按 UTF-8 字节序排序且去重的 `reviewerSubjectIds`。
- `approvedAt`、`reviewPolicyDigest` 和包含样本、Schema、语义、安全及质量报告的 `evidenceDigest`。
- 受保护 Collection 的 submitter 不得出现在 reviewerSubjectIds；reviewer 数量必须满足 review policy。发布服务必须从不可变 ApprovalDecision 读取这些字段，不接受客户端拼装。

## 5. 验证规则

Worker 在任何 Source 请求前必须验证：

1. Attestation 通过 JSON Schema，且所有 ID 与固定 Run 上下文完全一致。
2. 重新计算的 GatherSpec digest 等于 `ruleDigest`。
3. `purpose`、算法与签名输入域正确。
4. `keyId` 在 `signedAt` 时处于可信区间，签名有效，且证明未过期；验证必须读取不早于 Run 固定 revision 的最新信任注册表，不能用旧缓存绕过紧急状态变更。
5. 密钥的 compromise policy 没有使该 `signedAt` 失效。
6. approval decision、review policy 和 evidence digest 可解析、租户一致，且仍满足发布时的四眼审批策略。
7. 活动 RuleVersion 至少有一份当前可用于新 Run 的有效证明。

验证失败使用 `RULE_ATTESTATION_INVALID`，不得回退到“只校验 digest”。

## 6. 密钥生命周期与事故处理

SigningKey 状态为 `Pending`、`Trusted`、`Retired` 或 `Compromised`：

- `Trusted`：可签发新证明。
- `Retired`：不得签发新证明；退休前签发的证明只可授权 `retiredAt` 前已经创建并固定该 trust revision 的 Run，以及历史审计和无副作用回放，不能授权新的生产 Run。
- `Compromised`：信任注册表必须记录 `compromiseEffectiveAt`。该时间及之后签发的证明失效；无法确定起点时，该密钥的全部证明失效。
- 需要继续执行的 RuleVersion 由新的 Trusted key 追加 RuleAttestation；不得修改或重新序列化 GatherSpec。

密钥状态变更、影响范围计算、规则暂停、重新证明和恢复必须生成 AuditEvent。紧急吊销优先于 Schedule 可用性目标。

## 7. 存储与唯一约束

- RuleAttestation 是只追加实体；数据库不得原地修改 payload 或 signature。
- `(tenantId, attestationId)` 唯一。
- `(tenantId, ruleVersionId, ruleDigest, approval.decisionId, keyId, signedAt)` 唯一。
- 删除 RuleVersion、SigningKey 或 User 不得级联删除证明。
- 信任注册表必须保存 `trustedAt`、可选 `retiredAt`、可选 `compromiseEffectiveAt` 与单调 revision；证明读取必须使用同一 Tenant 边界，并记录验证所用 key revision。

## 8. 验收

- [`rule-attestation.example.json`](./rule-attestation.example.json) 通过 Schema，并能由 [`示例公钥`](./rule-attestation.example.public-key.pem) 验证。
- 篡改 tenantId、ruleVersionId、ruleDigest、approval、purpose、signedAt 或 signature 均验证失败。
- Retired key 不能授权新 Run；Compromised key 按 `compromiseEffectiveAt` 使受影响证明失效。
- 使用新 key 追加证明不会改变 RuleVersion digest。
