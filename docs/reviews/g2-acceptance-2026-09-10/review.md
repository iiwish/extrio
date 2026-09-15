# G2 Review 与技术验收

日期：2026-09-10。状态：Technical Acceptance PASS。验收对象为当前未提交的 G2 工作树，HEAD 为 `86ebcc4b570f8b5b5acf3f1c6ba0f70ac7ed42f7`。范围采用 [P02–P10](../../planning/v1.0-delivery-plan.md) 与 [G2 执行合同](../g2-2026-09-10/packet.md)，保留既有 G1 修改。按用户“review 检查并完成 G2 验收”的要求直接执行，不委派、不提交、不部署。

## Review 发现

### P2：HTML 字段的来源投影丢失类型，已修复

`project_source_contract` 将冻结合同的 JSON Schema 类型优先用于字段投影。HTML 的 JSON Schema 为 `string` 且没有 format，因此 HTML 字段被投影成普通文本。需求页展示及“复制来源字段为草稿”都消费此投影，复制后会丢失 HTML 类型。旧类型参数化测试只包含 date、datetime、url、object、array，未覆盖 HTML。

补齐全部 10 种字段类型后，HTML 用例实测失败：期望 `html`，实际 `string`，其余 9 项通过。修复保留 string Schema 下规则已声明的 HTML 语义，日期、对象、数组仍由冻结 Schema 决定。覆盖扩大到候选及已发布规则两条读取路径，不改已发布版本、摘要或运行合同。

- 实现：`backend/src/extrio/collection_fields.py`。
- 回归：`backend/tests/test_frozen_collection_contract.py::test_frozen_source_projection_preserves_semantic_type`。
- RED：`... pytest backend/tests/test_frozen_collection_contract.py -q -k projection`，1 failed / 9 passed。
- 初次 GREEN：冻结合同测试 27 passed；候选/已发布双路径扩展后的最终结果见下表。

## 范围与风险检查

| 合同 | 检查对象与结论 |
| --- | --- |
| P02–P04 | 004–006 双数据库迁移、不可变触发器、revision/权限/幂等/审计原子性、版本历史与发布预览；没有修改已发布记录的应用入口 |
| P05 | 来源创建绑定固定版本；编译/修复/发布/运行读取冻结合同，不读取可变草稿；未知及跨需求版本失败；补齐全部类型的来源投影 |
| P06–P07 | 固定计划摘要、全部差异确认、活动运行/任务阻断、候选合同校验后切换绑定；放弃迁移的来源定义保护；检查了事务锁顺序与异步消费者 |
| P08 | 三个内置版本化模板，预览不写，确认只改草稿，revision 和审计失败回滚 |
| P09–P10 | 输入/输出上限、真实网关、取消审计、租约恢复、过期 attempt 防覆盖、限额、选择应用与 revision 冲突；未发现额外确定性缺陷 |

真实供应商调用复用 [脱敏证据](../g2-2026-09-10/real-model-evidence.json)：`glm-5.3-flash` 一次调用、568 tokens；未自动应用、仅 title 被接受、未选字段及发布版本/来源绑定不变、审计链有效。本次未新增模型调用，也未恢复临时供应商凭据。

## 实际复验

| 检查 | 结果 |
| --- | --- |
| 初始后端全套，隔离 PostgreSQL 16 与 SQLite | 337 passed，319.37 秒；此进程在 HTML 修复前加载代码，不作为修复后的全套结果 |
| 最终后端全套，隔离 PostgreSQL 16 与 SQLite | `EXTRIO_TEST_DATABASE_URL=<本机隔离 PG> uv run --project backend pytest backend/tests -q`：352 passed，97.42 秒；包含 HTML 修复及候选/已发布规则 20 项类型投影检查，只有参数化数据库用例覆盖双数据库，不宣称全部测试各运行两遍 |
| 前端全套 | `pnpm --dir web test --maxWorkers=1`：最终 35 文件、171 passed，70.16 秒；与后端全套串行执行 |
| 超时用例单独复跑 | `pnpm --dir web test src/features/collectors/new-collector-page.ui.test.tsx --maxWorkers=1`：3 passed，7.08 秒；未改测试超时或前端代码 |
| 生产构建 | `pnpm --dir web build`：TypeScript 与 Vite 通过，2074 modules |
| 静态检查 | `pnpm --dir web lint`：通过 |
| API 类型 | `pnpm --dir web api:generate`：通过；生成文件前后 SHA-256 相同，无额外类型漂移 |
| 文档与差异 | `uv run --project backend python scripts/update-docset-manifest.py --check`、`git diff --check`：通过 |

首次前端失败为新来源页延迟加载用例超过既有 15 秒阈值，没有业务断言失败。当时后端全套同时运行且主机存在其他负载；单独复跑和最终全套均成功，支持环境时序因素的判断。保留该偶发超时风险，不将失败计入通过，不改测试阈值。

## 浏览器证据

复用隔离前端 5178/API 8018 的专用虚构需求，不修改用户业务对象。检查已应用 AI 建议恢复和迁移审核两个高风险工作面，各覆盖 1440x900、1280x800、1132x1028、1024x800，新增 8 张截图；`sips` 读取真实图片尺寸，8/8 与目标一致。[布局检查](browser-checks.json) 中无页面横向溢出或弹层越界，人工复核两个最小视口截图。

- 建议历史真实恢复为“已应用为草稿”，接受按钮及勾选禁用，未选 price 的变更检测仍保留。
- 来源保持 v1，需求活动版本为 v2；迁移计划显示 price 从 number 到 integer，未确认时提交禁用。本次只预览并取消，没有启动迁移。
- 取消后焦点恢复到迁移入口；最终返回中文字段页并重置临时视口。
- 上轮 [116 张中英文截图](../g2-2026-09-10/screenshot-inventory.json) 支撑完整状态矩阵，本次 8 张是针对性复核，不冒充重新执行整个矩阵。

## 验收边界

G2 P02–P10 技术验收通过；本次发现的 1 项 P2 已通过反例测试关闭，没有未关闭的 G2 P0/P1/P2。修改仅涉及来源合同投影、对应测试及验收/规划文档；未变更产品范围或四份产品合同。隔离 API 8018 已加载修复且 healthz 为 ok，测试用 PostgreSQL 容器已停止，原业务服务保持不变。

用户最终产品签收独立记录；不将技术验收等同于用户已签收。生产数据迁移、备份恢复、持续稳定性和跨流程发布验收属于 G3/G4，本次不宣称完成。未进行 Git 提交、合并或部署。
