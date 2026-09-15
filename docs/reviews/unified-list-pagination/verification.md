# 统一列表分页验收

日期：2026-09-14。范围：采集需求、采集来源、采集运行、AI 任务、数据五个一级列表。

## 实现

- 五个列表由 ListWorkspace 持有 ListPagination，useListQuery 统一 URL 页码、页大小、请求、超界回落与筛选重置。
- 固定底栏显示当前行范围、总行数、每页行数、页码、总页数及换页和跳页控件。顶部工具栏和表头固定，只有列表区域滚动。
- 全量服务端筛选与计数独立于当前页；运行和 AI 历史支持 SQL COUNT、LIMIT/OFFSET。来源待处理分类读取每个来源实际引用的最近运行，不受前 200 条运行限制。
- 未传 page 的旧 API 调用保持兼容。来源和运行写操作、鉴权、采集执行、数据库结构不在本次变更范围内。

## 自动验证

- `cd web && pnpm test`：42 个测试文件，256 项通过。
- `cd web && pnpm build`：通过。
- `cd web && pnpm lint`：通过。
- `cd backend && uv run pytest tests/test_workspace_pagination.py tests/test_item_query.py tests/test_pagination_navigation.py tests/test_api_output.py tests/test_store.py tests/test_collections.py tests/test_source_deletion.py tests/test_store_pg.py -q`：87 项通过，18 项 PostgreSQL 用例因未配置测试数据库跳过。
- `cd backend && uv run ruff check src/extrio/workspace_pagination.py tests/test_workspace_pagination.py src/extrio/app.py src/extrio/store.py`：通过。
- `pnpm api:generate` 重复生成的 schema.d.ts SHA-1 一致；`git diff --check` 通过。
- 隔离测试覆盖超过 200 条历史记录、任意页切换不追加、特殊字符搜索、完整筛选总数、来源精确最近运行、历史归属、空页与超界回落；四个新增分页视图覆盖 51 行的换页、页大小变化、搜索重置、URL 和滚动归零。数据页原有分页与导出用例通过。

## 桌面验收

真实本地 API，只读验收；未创建、删除、发布或执行采集。

| 页面 | 1440x900 | 1280x800 | 1132x1028 | 1024x800 |
| --- | --- | --- | --- | --- |
| 采集需求 | [截图](collections-1440.png) | [截图](collections-1280.png) | [截图](collections-1132.png) | [截图](collections-1024.png) |
| 采集来源 | [截图](collectors-1440.png) | [截图](collectors-1280.png) | [截图](collectors-1132.png) | [截图](collectors-1024.png) |
| 采集运行 | [截图](runs-1440.png) | [截图](runs-1280.png) | [截图](runs-1132.png) | [截图](runs-1024.png) |
| AI 任务 | [截图](ai-runs-1440.png) | [截图](ai-runs-1280.png) | [截图](ai-runs-1132.png) | [截图](ai-runs-1024.png) |
| 数据 | [截图](items-1440.png) | [截图](items-1280.png) | [截图](items-1132.png) | [截图](items-1024.png) |

- 所有尺寸的文档宽度等于视口宽度；分页底边距窗口底部 24px，底栏内容无重叠。宽表列在列表内部横滚，不撑宽页面。
- 最小桌面尺寸中 AI 列表滚动到 1600px 时，工具栏顶部保持 136px、表头保持 213px、分页顶部保持 744px，文档 scrollY 保持 0。
- 采集运行 25 行，切换每页 20 行后共 2 页；下一页显示第 21–25 行且只有 5 行，没有追加上一页内容，见 [末页截图](runs-last.png)。
- 从运行第 2 页切换 AI 任务回到首页；AI 任务 51 行、每页 20 行共 3 页，末页显示第 41–51 行。切换需处理筛选回到第 1 页，显示筛选总数 27 行。
- 本地需求 6 行、来源 9 行，真实页面只有一页；多页行为由隔离的前后端数据集验证。浏览器验收结束后恢复原视口，保留 `/runs` 页面。

## 验证边界

- 未进行 PostgreSQL 实库验收；相关用例的跳过不等于通过。
- 需求与来源的派生汇总仍复用现有服务端全量领域读取模型，再过滤分页；返回和客户端渲染是有界的，但尚未证明超大来源目录的服务端读取性能。
- 分页查询反映实时数据，不提供跨请求快照隔离；新增历史记录可能改变后续页面位置。深 OFFSET 的极端数据规模性能未做负载测试。
