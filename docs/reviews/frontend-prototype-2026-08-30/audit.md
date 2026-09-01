# Extrio 前端原型后端开发就绪审计

## 1. 审计范围

- 日期：`2026-08-30`
- 视口：`1440x900`、`1280x800`
- 核心任务：进入概览、批量导入 Source、审核字段、发布规则、立即运行、诊断部分成功和查看拒绝候选。
- 结论：产品闭环和桌面布局已具备后端接入条件，但真实后端编码前必须先关闭 API/机器合同就绪门。

## 2. 流程证据

1. **工作概览，健康度：良好。** 优先事项、运行质量、数据质量与主导航可以形成清晰入口。见 [`01-overview.png`](./01-overview.png)。
2. **创建需求，健康度：良好。** 一个需求与多个 Source 的关系表达清晰。见 [`02-create-collector.png`](./02-create-collector.png)。
3. **批量校验，健康度：中上。** 合法、重复和非 HTTPS URL 能逐项反馈；展开结果后主操作落到首屏以下，后续可增加吸底操作区。见 [`03-batch-validation.png`](./03-batch-validation.png)。
4. **采集流程审核，健康度：良好。** 两阶段、分页、详情发现、安全边界和证据能够同屏核对。见 [`04-collector-review.png`](./04-collector-review.png)。
5. **字段审核，健康度：中上。** 决策模型和键盘选择可用；字段风险被接受后顶部仍显示“需要明确决策”，状态文案没有同步。见 [`05-field-review.png`](./05-field-review.png)。
6. **发布确认，健康度：良好。** 不可变性、审核身份、digest 和字段决定均明确。见 [`06-publish-confirmation.png`](./06-publish-confirmation.png)。
7. **发布终态，健康度：良好。** 发布证明和下一动作清晰。见 [`07-published-rule.png`](./07-published-rule.png)。
8. **运行中，健康度：中。** 两阶段进度可理解，但当前由客户端定时器模拟，不是后端持久状态。见 [`08-run-progress.png`](./08-run-progress.png)。
9. **运行结果，健康度：良好。** accepted/rejected、Run 入口与 Item 谱系形成闭环。见 [`09-run-result.png`](./09-run-result.png)。
10. **Run 诊断，健康度：良好。** 第一视口回答终态原因、影响和恢复动作。见 [`10-run-detail.png`](./10-run-detail.png)。
11. **拒绝候选，健康度：中。** 拒绝原因和谱系完整，但页面仍将其标记为 `Revision 0`，与“未生成 Revision”的领域语义冲突。见 [`11-rejected-item.png`](./11-rejected-item.png)。

## 3. 后端就绪门

### P0

1. GatherSpec 页当前拼装的是 UI 摘要，却声明为 `extrio.gather.v1`；字段结构不满足冻结 Schema。后端必须返回真实 GatherSpecDraft，前端只展示服务端对象。
2. Explore 和 Run 当前等待请求返回终态，并用浏览器定时器伪造进度。真实接口必须采用 `202 + operation/run id`，状态由持久化任务和查询接口驱动。
3. MSW 当前在所有构建中启动。必须增加显式 mock 开关和版本化 API base URL，否则生产构建不会可靠切换到 FastAPI。

### P1

1. 实现已经确认的 `single | list_detail` 模式；前端不得把 `detail` 永远建模为必填。
2. 风险决定完成后更新或移除未决警告。
3. 将 rejected candidate 与 HarvestItemRevision 分开建模，不使用虚构的 `revision: 0`。
4. 补齐 `cancelled`、`timed_out`、Attempt、稳定错误码、requestId 和幂等键。
5. 增加跨页面谱系、完整审核发布、异步 Run 和 GatherSpec Schema 合同测试；当前 9 个测试不足以保护真实后端接入。

## 4. 开发计划

### Phase 0：合同与接入门，0.5-1 天

- 冻结 `/api/v1` OpenAPI、错误模型、分页模型和异步命令响应。
- 从 OpenAPI/JSON Schema 生成或校验 TypeScript/Python 类型。
- 让 MSW 与 FastAPI 使用同一响应 fixture；前端改为环境化 API client。
- 修复 P0 和上述三个直接产品语义问题。

### Phase 1：控制面纵向切片，1-2 天

- 建立 FastAPI application factory、PostgreSQL/Alembic、Redis Streams 和 S3 兼容存储。
- 实现 CollectionVersion、SourceRevision、Collector、RuleVersion、Run 与 Artifact 最小表和状态机。
- 实现批量 Source 导入、逐项错误、幂等约束、审计字段和 `202` 异步任务创建。

### Phase 2：编译 Worker，2-3 天

- 通过 Crawl4AI/受控 sample-fetch 探索 Source。
- 支持单阶段和固定 list/detail；生成真实 GatherSpecDraft、样本、质量报告和 ArtifactManifest。
- 控制面重新校验 Schema、allowedHosts 和 digest 后进入 NeedsReview。

### Phase 3：执行 Worker，2-3 天

- 使用 Crawlee 执行已发布 `extrio.gather.v1`，覆盖 `none`、`page`、`next_link` 和可选 detail。
- 实现预算、重试、URL 去重、ResultBatch、RunFinalization、accepted/rejected 与完整 lineage。
- Worker 只通过受控 API/对象存储提交，不直接写领域表。

### Phase 4：前后端联调与证据，1-2 天

- 用查询轮询接入真实状态，SSE 保留为后续优化；移除客户端定时器。
- 跑通批量导入、探索、审核、发布、运行、拒绝诊断和 Item 谱系。
- 增加合同测试、状态机测试、浏览器旅程、SSRF 反例和 1280/1440 桌面截图。

## 5. MVP 时间边界

两天可以完成一个真实的本地纵向闭环，但必须限制为单 Tenant、HTTP 优先、一个受控 Source fixture、手动运行、轮询状态和基础 Artifact。完整 v0.2 的 RBAC、Schedule、恢复、Kafka/Webhook、回放、灾备与生产安全证据不属于两天闭环。
