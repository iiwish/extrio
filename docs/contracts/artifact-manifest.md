# Extrio ArtifactManifest v1 合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 规范标识 | `extrio.artifact-manifest.v1` |
| 文档版本 | `v1.1.0` |
| 状态 | `Ready_For_User_Review` |
| JSON Schema | [`artifact-manifest.schema.json`](./artifact-manifest.schema.json) |
| Chunk Schema | [`artifact-manifest-chunk.schema.json`](./artifact-manifest-chunk.schema.json) |
| 权威来源 | [`../SSOT.md`](../SSOT.md) 中的 `INV-003`、`INV-004`、`INV-005`、`INV-007`、`INV-012` |
| 最后更新 | `2026-08-30` |
| 审批责任 | 技术负责人、安全负责人 |

## 2. 目的

ArtifactManifest 是编译样本、生产 Run 或验证回放的不可变证据索引。它通过证据等级区分元数据、抽样证据和证据等价回放，避免把不完整采样冒充历史回放。大型 Run 使用不可变 chunk 引用，不把全部响应内联到根 Manifest。

Manifest 不保存请求凭据、Cookie、Authorization、私钥、Secret Manager 路径或可恢复的 token。v0.2 禁止 AccessProfile 把 secret 注入 URL，因此 Manifest 中的请求和最终 URL 不得含 userinfo 或 secret query 参数。

## 3. 执行与运行时上下文

- `executionRef.kind` 为 `compile`、`run` 或 `validation_replay`，并通过 `executionId` 引用对应不可变记录。
- `ruleVersionId` 对 run/replay 必填；compile 可以省略，但必须固定 CollectionVersion、SourceRevision 和编译任务。
- `runtime` 必须固定 runtime、parser、dialect、tzdb 和 Unicode 数据版本。
- Browser 执行还必须固定 engine/version、viewport、deviceScaleFactor、locale 和 timezoneId；canonical DOM snapshot 是回放输入。
- Manifest 的 `createdAt` 是索引完成时间；每个响应有独立的请求和完成时间。

### 3.1 证据等级

| evidenceMode | 内容 | 可声明证据等价回放 |
| --- | --- | --- |
| `metadata_only` | 请求/响应计数、统计、digest 和运行时上下文，不要求响应正文 | 否 |
| `sampled` | metadata 加受控 `samples[]`，不保证覆盖全部请求 | 否 |
| `replayable` | `complete=true`，全部请求按 sequence 写入经过 digest 固定的 response chunks | 是 |

`capturedResponseCount` 必须等于实际保存的 response 数；只有 replayable 模式允许且要求 `capturedResponseCount == totalResponseCount`。GatherSpec `rawRetentionDays=0` 的成功 Run 使用 metadata_only，或按 Tenant 策略保存 sampled 失败证据，不得生成虚假的 replayable Manifest。

## 4. 请求与响应证据

sample 或 chunk 中的每个 response 按 `sequence` 严格递增，包含：

- `requestId`、stage、HTTP method、canonical request URL 与 request-plan digest。
- redirect chain 中每一跳的状态和 canonical URL。
- 最终响应状态、media type、content encoding 与 allowlist Header。
- 解压前 raw body Artifact 引用、digest 和字节数。
- 解压后 body Artifact 引用、digest 和字节数；parser 以该字节序列为输入。
- Browser response 额外包含 canonical DOM snapshot Artifact；提取与回放只读取该 snapshot，不重新执行页面 JavaScript。
- `startedAt`、`completedAt` 与 response truncation 标记。

允许精确保存的响应 Header 仅限解析与缓存证据所需字段：`Content-Type`、`Content-Encoding`、`Content-Language`、`ETag`、`Last-Modified`、`Date` 和 `Location`。其他 Header 只保存规范化名称和值 digest；`Set-Cookie`、`Authorization`、`Proxy-Authorization` 和安全策略判定的敏感 Header 不保存值。

## 5. Digest 与不可变性

- 每个引用 Artifact 和 chunk 在对象存储写入成功后才能写入 Manifest；数据库保存对象版本、SHA-256、大小、分类和保留期。
- `manifestDigest` 对删除 `/manifestDigest` 后的完整 Manifest 使用 RFC 8785 JCS 和 SHA-256 计算。
- `chunkDigest` 对删除 `/chunkDigest` 后的完整 chunk 使用相同算法计算；chunk sequence 范围必须连续、不重叠并覆盖 `0..totalResponseCount-1`。
- 相同 digest 不代表相同权限；每次读取仍必须校验 tenantId、classification 与 purpose。
- Manifest、引用对象或 runtime 版本缺失时，系统必须声明“无法完成证据等价回放”，不得自动访问实时 Source 代替。

## 6. 回放模式

- `validation_replay` 只接受 evidenceMode=replayable 且所有 chunk/body/DOM digest 可验证的父 Manifest，默认禁止 Source 请求、Delivery、Checkpoint、副作用写入和活动版本切换。
- Worker 按 chunk 与 response sequence 读取固定响应，以记录的最终 URL 作为 HTML base URL，应用固定 parser/dialect/tzdb/Unicode 和 browser context。
- 验证回放输出写入隔离 namespace，并记录新 Manifest 对原 Manifest 的 `parentManifestId` 引用。
- 生产重新处理或重新交付是独立高风险命令，必须授权、审批、审计并复用领域幂等键。

## 7. 安全与保留

- URL 和响应内容按 Source 数据分类加密；UI 默认只显示 host、path 模板或 digest。
- Artifact object key 不得包含 tenant 名称、URL、凭据或业务 payload。
- 下载使用短期、单对象、单租户授权；服务端再次校验 membership 和 purpose。
- 内容过期后保留 Manifest 最小元数据、digest、删除时间和策略依据；正文引用标记为 `Expired`。

## 8. 验收

- [`artifact-manifest.example.json`](./artifact-manifest.example.json) 与 [`artifact-manifest-chunk.example.json`](./artifact-manifest-chunk.example.json) 通过 Schema 和 digest 校验。
- response bytes、最终 URL、parserVersion 或顺序任一变化都会改变 replay 结果证据或 Manifest digest。
- Artifact 上传失败不会产生声称可回放的 Manifest。
- Manifest 与相关日志、队列和 API 响应均不包含凭据 material。
- 100,000 Item 的 list/detail Run 可以通过 chunks 表达，根 Manifest 大小不随 response 数线性增长。
