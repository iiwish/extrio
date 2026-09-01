# ADR-002：调度、队列与存储基线

## 元数据

| 字段 | 内容 |
| --- | --- |
| 决策状态 | `Confirmed` |
| 决策版本 | `v1.2.0` |
| 对应产品版本 | `v0.2` |
| 最后更新 | `2026-08-31` |
| 审批责任 | 技术负责人 |
| 关联需求 | `FR-008` 至 `FR-013`，`NFR-003` 至 `NFR-007` |

## 背景

v0.2 需要 Cron 调度、可恢复任务、Artifact 留存、独立交付重试和清晰的数据真相源。现阶段采用 Temporal 会增加新的运行、可观测和数据迁移负担；仅使用 Redis 又无法承担领域一致性和灾备真相。

## 决策

### PostgreSQL

PostgreSQL 是以下数据的系统记录：

- 领域对象、不可变版本和状态机。
- Schedule occurrence、Run、RunAttempt 和 lease fence token。
- HarvestItem、Revision、HarvestObservation、ItemEvent、Delivery、RedeliveryRequest 和 DeliveryAttempt。
- AuditEvent、Artifact/ArtifactManifest 元数据和配额状态。
- transactional outbox 和 dispatcher 游标。

状态转换、活动版本指针、审计与 outbox 必须在同一事务完成。数据库使用唯一约束实现 occurrenceKey、entityKey、revisionKey、Observation、eventId 和 deliveryId 幂等。

### Redis Streams

Redis Streams 用于编译、执行和交付工作分发，不是权威状态存储。

- dispatcher 从 PostgreSQL outbox 发布任务引用。
- consumer group 分配任务，Worker lease 仍由 PostgreSQL fence token 决定。
- 消息确认只在领域结果提交后发生。
- 重复、乱序和队列重建是正常场景，消费者必须幂等。
- Redis 全量丢失后可以从 outbox、非终态 Run 和 Delivery 重建。

### S3 兼容对象存储

对象存储保存 raw response、样本、校验报告和大型错误证据。

- 数据按 environment/Tenant/分类分区。
- 数据库保存 objectId、digest、大小、媒体类型、分类、创建时间和删除时间。
- 上传使用短期预签名授权；读取通过控制面鉴权。
- 生命周期策略与 [`security-compliance.md`](../security-compliance.md) 保持一致。

### Cron 调度

- 控制面按 UTC 计算 occurrence，并使用唯一 occurrenceKey 创建 Run。
- 调度器使用数据库锁或租约协调多个实例，不依赖单实例内存定时器。
- 宕机恢复扫描未处理 occurrence，但受每个 Schedule 的 misfirePolicy 和最大补偿窗口约束。
- v0.2 默认 `misfirePolicy=run_once`、最大补偿窗口 24 小时；用户可以选择 `skip`，不支持无限补跑。
- v0.2 固定 `overlapPolicy=forbid`。支持列表时间降序、可提取发布时间且采用 `next_link` 的 Source；每个 Run 固定不可变 CollectionPolicyVersion，并在成功终结事务中持久化 CollectorCheckpoint。通用 cursor、无限滚动和任意增量表达式不在当前范围。

### Transactional outbox

所有异步副作用先写入同事务 outbox。dispatcher 至少一次发布，consumer 使用业务幂等键去重。outbox 在全部消费者确认并超过审计窗口后归档；清理不得早于 7 天。

## 容量基线

系统必须在 [`product-contract.md`](../product-contract.md) 的 v0.2 设计容量下满足：

- Schedule dispatch `p95 <= 5 分钟`、`p99 <= 15 分钟`。
- Redis 队列重建不会产生新的逻辑 occurrence、ItemEvent 或 Delivery。
- PostgreSQL 故障恢复满足元数据 `RPO <= 15 分钟`、`RTO <= 4 小时`。
- 对象存储恢复满足 Artifact `RPO <= 24 小时`、`RTO <= 8 小时`。

## Temporal 评估阈值

v0.2 不采用 Temporal。满足以下任一结构性条件，或任意两个规模/可靠性条件时，必须创建新的 ADR 评估工作流引擎：

结构性条件：

- 一个 Run 需要跨越超过 24 小时的人工批准、外部回调或可持久等待，并在等待后恢复。
- 一个业务工作流需要三个以上跨服务补偿步骤，且补偿顺序影响用户数据正确性。
- 产品要求多区域主动主动运行并在区域切换后保留工作流状态。

规模/可靠性条件：

- 连续 30 天同时存在超过 50,000 个非终态 Run/Delivery 工作流。
- p95 Run 时长超过 6 小时且至少包含三个需要独立重试的持久阶段。
- 自建调度恢复或补偿逻辑在一个季度内造成两次 SLO 违约或一次数据正确性事故。
- 调度、lease、重试和补偿相关代码连续两个版本占平台缺陷修复工作量的 20% 以上。

达到评估阈值不自动决定迁移。新 ADR 必须比较 Temporal 与增强现有方案的迁移成本、运维能力、双写策略和回滚方式。

## 备选方案

### Redis 作为唯一任务真相

实现简单，但无法可靠绑定领域事务、审计、RPO 和队列重建。未采用。

### PostgreSQL 轮询，不使用 Redis

组件更少，但高频 claim、优先级和长队列会增加数据库争用。可作为 Redis 故障降级与重建机制，不作为正常主路径。

### 立即采用 Temporal

工作流语义强，但 v0.2 的 Run 仍是有限阶段、有限时长的任务；当前收益不足以覆盖新平台的部署、数据和运维复杂度。未采用。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| PostgreSQL 成为吞吐瓶颈 | 批量写、分区、短事务、索引预算、压测和读副本 |
| outbox 积压 | 延迟指标、独立 dispatcher、按分区扩展和 15 分钟告警 |
| Redis 重复或乱序 | 稳定业务键、fence token、状态机检查 |
| Artifact 与元数据不一致 | 先上传再提交引用、定期 orphan/referential sweeper |
| 大规模补跑压垮 Source | misfirePolicy、配额、租户公平调度和速率限制 |

## 任务影响

- 数据库迁移必须建立关键幂等唯一约束和 outbox。
- dispatcher、Worker 和 Delivery consumer 必须通过队列丢失、重复与乱序测试。
- 发布前执行数据库恢复、Redis 重建和对象存储校验演练。

## 验收

1. Redis 清空后可从 PostgreSQL 重建所有非终态工作且不增加逻辑副作用。
2. 控制面在调度器双实例竞争下只创建一个 occurrence Run。
3. 结果写入与待交付 outbox 不出现单边提交。
4. Artifact 上传失败不会留下可回放的虚假元数据。
5. 同 SinkVersion redelivery 不会违反 Delivery 唯一约束。
6. 容量压测与灾备演练满足合同目标。
