# H001 数据正确性与本机运行修复

状态：Engineering Verified，等待用户复核。用户明确要求继续修复项目检查报告中的问题；不包含实现后续 1.0 新功能，也不创建其他 Codex 任务。验证结果见 `validation.md`。

## 执行合同

- 输入：`docs/reviews/project-health-2026-09-06.md`、`AGENTS.md`、`docs/SSOT.md`、API 和运行合同。
- 模式：Direct Execute，用户未授权委派。当前工作树已有大量产品迭代，直接在这些实现上追加小范围修复，不回退、不提交。
- H001-A：JSON 字段值保留类型比较，null、0、false、空字符串/容器可区分，真实变化增加 Revision 并进入更新交付。
- H001-B：数据页使用服务端实体级分页和筛选；实体按 collectorId + entityKey 选最新观测后再筛选。保留默认观测 API 的兼容性。导出与数据页使用同一实体/筛选合同，完整覆盖所有匹配页，不限于已显示页。
- H001-C：PostgreSQL 迁移测试采用明确排序；新增实体查询必须在 SQLite 和独立 PostgreSQL 验证。
- H001-D：检查并恢复本机 API/Worker 同库同 Artifact 运行。不得改变用户密码、启用真实站点调度或自动消费未经确认的外部任务。已有用户数据不用于增删改验收。
- 顺序：A 回归与修复，B 回归与修复，C 数据库验证，D 运行验证，完整测试与桌面 QA，最后分析 1.0 规划。
- 允许文件：backend 的 worker/store/app 与对应测试；web 的 items 页面、API client/handlers/types/生成类型、相关测试、items 中英文词条、必要的局部 CSS；scripts 的启动/停止/验证脚本及测试；API OpenAPI、产品四份同步合同、文档 manifest；本目录验证记录及独立 1.0 规划文档。
- 禁止：迁移或重写历史采集结果、规则、凭据；修改采集引擎或 AI 编译器能力；对真实外站发起采集或模型请求；覆盖其他已有修改。

## Checklist 与分析

- [x] 问题已在前一轮真实 API、浏览器和纯函数中复现。
- [x] 对外 API 采用可选参数扩展，默认观测查询、MCP 和现有调用方语义保留。
- [x] 先按实体选最新观测再做质量/关键词过滤，避免把旧的接收记录当成当前状态。
- [x] 服务端参数绑定；分页排序有 id 最终稳定键；查询失败不得显示为空数据。
- [x] 不把草稿发布、生产 HA 等未实现能力纳入本次修复完成声明。

## TDD 与验证

先新增 worker 假值、分页第二页/跨来源同 key、最新实体过滤、标题/域名导出一致性和前端分页/错误状态测试，实际执行并记录 RED；再实现并记录 GREEN。PostgreSQL 已有失败见输入报告，保留测试并修正排序假设。

验证命令：后端相关 pytest -> SQLite 全量 pytest -> 独立 PostgreSQL test_store_pg；前端相关 vitest -> 全量 test/lint/build；Ruff；OpenAPI 生成/合同测试；文档 manifest；git diff --check；四种支持的桌面视口浏览器验证。运行检查使用独立验收数据，不伪报真实供应商闭环。

完成标准：三个数据缺陷有能观察实际结果的回归测试；默认 API 兼容；相关测试和构建通过；运行环境及未验证项明确；1.0 估算列出范围假设、依赖、任务验收点和缓冲。不自动标记用户 Accepted。
