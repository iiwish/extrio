# P2 可靠性修复执行包

任务：`P2-RELIABILITY-20261022`。用户于 2026-10-22 明确要求按项目检查安排修复两个 P2、补回归、同步发行状态并复验，暂不发布或部署。实现可执行；最终结果等待用户复核，不代替稳定版签收。

## 合同与边界

- 基线：main `cd60804a60aaa7bbbcbd4a07ec7a3738b0699c75`；本地分支 `codex/p2-reliability-20261022`。
- 产品、安全和权限合同：`docs/SSOT.md`、`docs/product-contract.md`、`docs/runtime-contract.md`、`docs/contracts/api-contract.md`。仅修复已有行为，不扩产品范围。
- 原始诊断和用户批准的安排：[项目检查](/Users/iiwish/.codex/visualizations/2026/10/22/01a1624b-f39e-7cb1-a3df-52b5c8d6823e/extrio-health/project-health-and-plan.md)。仓库内复现目标如下，不要求执行者依赖聊天。
- 禁止发布、部署、推送、合并、重打标签、改共享虚拟环境、迁移真实数据库、启用来源调度、真实公网采集或付费模型调用。
- 临时 SQLite/PG16、签名密钥、Artifacts、合成 HTTP/模型/Webhook fixture 必须独立；不访问现有业务实例。临时服务和独占容器在验证后清理。

## 执行次序

### A001：恢复调度启动拒绝

允许：`backend/src/extrio/app.py` 的 RunStartError/恢复调度相关边界、`backend/src/extrio/bounded_recovery.py`、`backend/tests/test_bounded_recovery.py`，以及本目录 `recovery-evidence.md`。

先写正确预期的失败测试：合法恢复批次冷却时，已签名规则的 key 被退役或失信；到期 tick 不抛未处理启动拒绝，不启动不可信 Run，批次持久化为 `needs_attention`；重复 tick 不重试。另一个不同 host、有效规则的批次仍能推进。测试保留原始 Run、预算、签名和取消/期限约束。

确认 RED 后做最小修复，优先沿用已有异常/生命周期模式；不以捕获所有异常掩盖未知故障。SQLite 与 PG16 参数路径、既有恢复、签名、调度测试通过。完成后主执行者检查 diff，A002 才可编辑共享 `app.py`。

### A002：创建来源的不确定结果重试

依赖：A001 返回并完成共享文件检查。允许：`web/src/features/collectors/new-collector-page.tsx`、该目录 `new-collector-page.ui.test.tsx`、`web/src/api/client.ts`（仅如必要）、`web/src/api/types.ts`、`docs/contracts/api-contract.md`、`docs/contracts/openapi.yaml`、`web/src/api/generated/schema.d.ts`、`web/src/api/handlers.ts`、`web/src/api/async-contract.test.ts`、`web/src/api/contracts.test.ts`、`web/src/i18n/locales/zh/collectors.json`、`web/src/i18n/locales/en/collectors.json`、`backend/src/extrio/app.py` 的 batch collectors 路由、`backend/tests/test_collector_input.py`，以及本目录 `creation-evidence.md`。需要其他文件时先向主执行者说明必要范围。

先写失败回归：首次提交已完成但响应丢失，相同 payload 再提交复用同一幂等键并获得原结果；变更 payload 使用新 key；重复点击/提交中保护不退化。批量全部拒绝时不返回可导航但不存在的需求身份，不凭空创建空需求以掩盖失败。既有需求归属及部分成功语义不变。前端遵循新建需求页现有 payload/key 引用模式。

确认 RED 后最小修复；真实后端 replay 控制、全部拒绝与部分成功、前端 retry/UI/类型通过。新需求的零成功结果使用 `collectionId=null / collectionVersion=null` 明确没有创建需求，既有需求的零成功结果仍返回已存在的身份与版本；同步公开合同、生成类型、Mock 和结果页，保留真实逐项错误，不只改 TypeScript 强制断言。

### D001：发行状态文档批量同步

低风险文档批次，可与 A001/A002 并行；不编辑其业务代码。允许：`docs/SSOT.md`、`docs/product-contract.md`、`docs/frontend-prototype.md`、`docs/releases/v0.2-acceptance.md`、`docs/releases/v1.0.0.md`、`docs/releases/v1.0-rc.2.md`、`README.md`、`README.zh-CN.md`、`ROADMAP.md`、`backend/tests/test_docset_authority.py`、`docs/releases/v0.2-docset-manifest.json` 和本目录 `docs-evidence.md`。

实时只读核验 PR #49、RC2 Release、main/tag 与精确提交工作流；主合同明确 RC2 已预发布，稳定版 `Needs_Review`/未发布，本次修复尚未发布，既有实例不推断已升级。历史 NLTK/旧镜像扫描留在冻结证据，不作为当前制品剩余门槛。四主合同保持一致，README/ROADMAP 不扩大支持站点、SLA、OCR 或部署范围。正文写当前规范状态，不重写历史审计报告。先加强语义合同测试并记录 RED，再更新文档及现有 manifest 生成器输出。

## 检查清单与分析

- 目标和验收可测：两个已有复现均已确认，用户明确批准修复及测试。
- F1 是失败关闭下的状态/可用性修复，不放宽签名、预算、权限、网络或自动重试。
- F2 保留来源唯一性，修正逻辑命令重试和真实结果身份；不报模拟成功。
- D001 仅修正已发布事实及剩余边界，冻结历史证据不改。
- 共享写入冲突：A001/A002 都可能触及 app.py，强制串行；D001 文件不重叠，可并行。
- 当前没有未处置的需求/权限 Critical 或 High 不确定项；如实现要求改安全边界、迁移或对外能力范围，停止并回报。

## 验证与证据

- 每个实现 attempt 记录改动文件、RED/GREEN 命令与真实结果、保留边界和风险；不再委派，不覆盖用户/其他执行者改动。
- 后端使用 `/tmp` 干净冻结环境，先定向 pytest，再 SQLite 与独占 PG16 全覆盖，按 JUnit 身份去重；Ruff、docset、打包与升级恢复路径按既有测试执行。
- 前端：`pnpm --dir web test`、`pnpm --dir web lint`、`pnpm --dir web build`，OpenAPI 类型一致性检查；中英文资源保持兼容。
- 桌面真实浏览器：主旅程与修复涉及的创建重试/无创建结果视图；1440x900、1280x800、1132x1028、1024x800，逐次核对 CSS 尺寸。只用本地合成 fixture。
- 主执行者完成 scope/合同 review、独立 bug review、QA 后写 `verification.md`；状态为待用户复核，不自动 Accepted。
- 不在本轮建设完整 CI E2E lane，不扩来源测试或执行后续产品体验包。

## Git 交接授权

用户于 2026-10-22 明确授权将本轮修复提交并推送、创建 PR、跟进 CI，暂不合并、发布或部署。
本节授权仅覆盖本轮修复、回归和证据的 Git 交接，取代上文实现阶段的提交/推送限制；不构成稳定版产品签收。

- 只推送 `codex/p2-reliability-20261022`，PR 目标为 `main`；不直接写 main，不强推，不创建 tag。
- 沿用已完成的源码、合同、独立 review 和本地复验，不扩业务实现范围；提交前核对文件所有权、证据无真实秘密及 manifest。
- 创建 PR 前核对工作流：PR 只触发验证，不触发镜像发布、Release 或部署；不手动触发发行工作流，不启用 auto-merge。
- 跟进精确 PR head 对应的所有验证；失败读取日志、区分产品与环境原因，不跳过、放宽或冒称 CI 通过。
- 提交 SHA、PR 链接和最终 CI 回执由 PR 元数据、说明/评论及本次交接答复记录；没有合并、发布或部署权限。
