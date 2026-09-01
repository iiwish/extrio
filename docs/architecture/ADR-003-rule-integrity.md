# ADR-003：规则完整性与运行时固定

## 元数据

| 字段 | 内容 |
| --- | --- |
| 决策状态 | `Ready_For_User_Review` |
| 决策版本 | `v1.3.0` |
| 对应产品版本 | `v0.2` |
| 最后更新 | `2026-08-30` |
| 审批责任 | 技术负责人 |
| 关联不变量 | `INV-001`、`INV-002`、`INV-003`、`INV-010` |

## 背景

Extrio 的核心承诺是编译期可以使用 Agent，运行期只执行已审核规则。要让这一承诺可证明，规则必须有稳定语法、明确语义、不可变存储、完整编译谱系、可验证摘要和与运行时版本的兼容关系。

## 决策

### 规则载体

- 所有生产规则使用 JSON GatherSpec，不持久化或执行生成的 Python/JavaScript。
- v0.2 唯一支持主版本为 `extrio.gather.v1`。
- JSON Schema 决定语法，语义规范决定选择器、模板、身份、分页、预算和输出含义。
- RuleVersion 保存 canonical payload、digest、编译谱系和验证报告引用；签名由独立、追加式 RuleAttestation 承载。

### Canonicalization 与 digest

1. 从完整 GatherSpec 移除 `/integrity/ruleDigest`。
2. 对剩余 JSON 执行 [`contracts/gather-spec.md`](../contracts/gather-spec.md) 定义的 canonicalization。
3. 对 UTF-8 字节计算 SHA-256。
4. 写入 `ruleDigest = "sha256:" + lowercaseHex`。
5. 发布服务按 [`contracts/rule-attestation.md`](../contracts/rule-attestation.md) 使用 Ed25519 生成独立 RuleAttestation。

`ruleVersionId` 包含在 digest 中，因此 ID 必须在计算 digest 前分配。RuleAttestation 不属于 GatherSpec，密钥轮换和重新证明不会改变规则内容。

### 发布与验证

- 只有 FastAPI 控制面的隔离发布服务身份可以请求签名；API 进程、编译服务和 Worker 均不直接持有导出的私钥。
- Worker 从受控信任注册表读取当前和仍在审计窗口内的验证公钥、状态和 revision。
- Run 创建与 Worker 启动都必须验证 digest、RuleAttestation、SigningKey 状态、schemaVersion 和 runtime compatibility。
- 验证失败立即终止且不得降级为未签名执行。
- 发布后规则 payload、digest 和编译输入引用均不可修改；可以追加证明，不能修改既有证明。

### Runtime 固定

Run 保存 `runtimeName`、`runtimeVersion`、`parserVersion`、`dialectVersion`、`tzdbVersion`、`unicodeVersion`、适用的 browser engine/version、RuleAttestation ID 和信任注册表 revision。Worker 必须运行匹配版本或已证明行为兼容的 patch 版本；不得自动使用改变选择器、Unicode、时间解析、DOM 或 URL 规范化语义的新 runtime。

### 兼容性

- `extrio.gather.v1` 只允许增加可忽略的可选字段、扩展受控 enum 前的能力协商，以及不改变既有输入行为的修复。
- 新增必填字段、改变默认行为、改变身份/摘要算法或删除字段必须使用新主版本。
- Runtime 至少支持当前主版本和上一个仍有 Published RuleVersion 的主版本，直到迁移完成。
- 废弃必须包含使用量、迁移生成、样本对比、回滚和最终停止日期。

### 回滚

回滚只切换 Collector 活动指针到可验证且 runtime 支持的 Published RuleVersion。若历史证明不能授权新 Run，发布服务使用当前 Trusted key 追加新 RuleAttestation 后再切换。Retired 公钥保留到关联 RuleVersion、Run 和回放审计保留期结束。

### 密钥事故

- SigningKey 进入 `Compromised` 时记录 `compromiseEffectiveAt`；无法确定起点时，其全部证明失效。
- 受影响 Collector 立即停止创建新 Run；运行中 Run 在下一次租约续期或凭据解析前停止。
- 经过规则 digest、审批谱系和当前安全门重新验证后，发布服务可以用新 Trusted key 追加证明并恢复。
- 事故处置只追加 SigningKey 状态、RuleAttestation 和 AuditEvent，不修改历史 GatherSpec。

## 备选方案

### 保存生成代码

表达力高，但扩大任意代码执行、依赖漂移和审计风险，破坏规则层统一性。未采用。

### 只保存数据库 hash，不签名

可以发现部分意外修改，但不能独立证明发布来源，也不能让 Worker 在不信任传输层时验证。未采用。

### 签署数据库记录而不是规则 payload

与存储实现强耦合，不利于导出、迁移和离线验证。未采用。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| Canonicalization 跨实现不一致 | 共享 fixture、Python/TypeScript golden test、拒绝浮点 NaN/Infinity |
| 签名密钥泄露 | KMS/HSM、发布服务独占、compromiseEffectiveAt、暂停、重新证明和 AuditEvent |
| Runtime patch 改变语义 | compatibility test suite、行为版本、固定运行时 |
| 旧规则无法回放 | 保留兼容 runtime 制品和解析器 fixture，明确 Artifact 保留期 |
| Schema 合法但语义危险 | 独立语义与安全校验，发布门不只依赖 JSON Schema |

## 任务影响

- FastAPI 控制面、Python Worker 与 TypeScript 合同工具必须通过相同 canonicalization、digest 和 fixture 测试。
- 发布服务需要隔离的签名能力与 key rotation runbook。
- Worker 启动前执行完整性校验，并产生不含规则敏感内容的失败证据。
- Runtime 发布必须针对所有受支持 GatherSpec fixtures 执行回归对比。

## 验收

1. Python 控制面、Worker 与 TypeScript 合同工具对同一 fixture 计算完全相同的 canonical bytes 和 digest。
2. 修改任意 GatherSpec 或 RuleAttestation 字段都会导致 Worker 拒绝执行。
3. 密钥轮换和追加证明不改变既有 RuleVersion payload 或 digest。
4. 不受支持的 Schema/runtime 组合在发出 Source 请求前失败。
5. Retired key 不能授权新 Run；Compromised key 按有效时间阻断受影响证明。
6. 回滚规则与历史 Run 仍能使用固定证明和正确验证公钥完成审计与回放。
