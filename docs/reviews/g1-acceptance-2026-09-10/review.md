# G1 Review 与技术验收

日期：2026-09-10。结论：**G1 Technical Acceptance PASS**。本次发现的 3 类 P2 问题均已修复并复验，没有已知未处置的 G1 阻断问题。用户对页面风格的最终签收与 1.0 发布签署不由本记录代替。

## Review 对象

基准 HEAD：`86ebcc4b570f8b5b5acf3f1c6ba0f70ac7ed42f7`，包含当前未提交工作树。范围为 [G1 工作包](../g1-2026-09-06/packet.md) 的 P01/P19、现有核心页面和跨页上下文，不扩展到 G2 字段版本、迁移、模板或真实 AI 字段建议验收。

进入 review 时，工作树已有 G2 的 CollectionVersion、004 双数据库迁移、Store/Worker/API、需求字段界面、OpenAPI 与类型修改。它们均予以保留；全套测试绿色仅证明当前组合工作树的回归结果，不代表 G2 已完成。本次未提交 Git、未部署、未修改真实采集数据。

## 已关闭 Findings

| 级别 | 问题与可达影响 | 修复与复验 |
| --- | --- | --- |
| P2 | 来源列表将 queued/running/finalizing 的最近运行标为健康；cancelled 以及有 latestRunId 但列表未取得该 Run 的来源可能漏出「需处理」筛选，影响运营判断。 | `collectors-page.tsx` 区分活动进度、取消和结果不可用；探索中显示探索进度。5 个参数化反例先失败，再随修复通过。 |
| P2 | 来源详情最近运行读取失败时回退到候选预览，仍展示最近结果和完成元数据；统计从预览条数计算，不能代表 Run 的完整计数。 | `collector-page.tsx` 显示加载/不可用状态，不冒用候选预览；计数使用 acceptedCount/rejectedCount，并保留完整 Run 入口。读取失败及 205/23 计数两个反例先失败，再通过。 |
| P2 | 英文运行列表的 Partially succeeded 越过状态列，与 Accepted 数字重叠约 17.34px；AI 来源长 URL 侵入任务列。 | 为状态列保留足够宽度，长标识与 URL 截断且提供 title，宽表局部滚动。复测状态与下一列间距约 30.66px；运行/AI 列表四桌面视口截图通过。 |

当前工作树还有两项集成校验修正：PostgreSQL 两个测试的迁移清单补齐已有 `004_collection_versions`，并校验表存在；docset manifest 同步已有 OpenAPI 修改的哈希。没有借此变更业务迁移或放宽断言。

## 自动化结果

| 命令 | 最终结果 |
| --- | --- |
| `pnpm --dir web test --maxWorkers=1` | 160 passed / 34 files，150.10s |
| `uv run --project backend pytest backend/tests -q --ignore=backend/tests/test_store_pg.py` | 251 passed，96.07s |
| `EXTRIO_TEST_DATABASE_URL=<isolated-pg16-url> uv run --project backend pytest backend/tests/test_store_pg.py -q` | 18 passed，56.04s |
| `pnpm --dir web lint` | exit 0 |
| `pnpm --dir web build` | TypeScript 与 Vite 生产构建通过 |
| `uv run --project backend python scripts/update-docset-manifest.py --check` | exit 0 |
| `git diff --check -- <本次修改路径>` | exit 0；全工作树检查仅报告既有 G2 文件 `backend/src/extrio/collection_fields.py:180` 的 EOF 空行，未修改无关文件 |

后端合计 269 项，区分默认数据库测试与 PG 专项，不声称每项业务测试都在两种数据库运行。临时 PostgreSQL 16 容器仅用于本地隔离验证，已停止并移除；未接触共享数据库。前端下载测试的 JSDOM navigation 提示不是失败，不能替代真实下载验收。

## 桌面与交互证据

真实鉴权前端 `http://127.0.0.1:5173` 与 API `http://127.0.0.1:8000`，使用既有管理员会话。12 个页面/视图覆盖 1440x900、1280x800、1132x1028、1024x800，共 48 组，另有需求列表、来源列表和英文设置补充截图。所有带视口编号的 51 张截图均重新核对实际像素尺寸；[证据索引](browser-matrix.json)记录文件及来源。宽表局部滚动，不要求不受支持的移动端布局。

- 来源：筛选 `q=zycg&view=attention`，进入来源、完整 Run、被拒绝实体，查看质量分区后刷新；逐级返回保留来源和筛选上下文，清空搜索不清除需处理筛选。
- 接入：选择既有需求，输入一条有效 URL 和一条无效 URL，预览为 2 条、1 有效、1 无效；离开确认可继续编辑并保留输入，也可明确放弃未保存输入，没有真实创建来源。
- 概览：切换今日/本周/本月和趋势粒度，Asia/Shanghai 口径可见；本月为 134 接收/144 总实体/10 拒绝，14 天为 24 次运行。自然窗口无记录时真实显示零，未将其当作服务故障。
- 设置：用户与供应商弹层 Escape 关闭、动画结束后焦点回到触发按钮；中英文切换可用。验收结束恢复中文、原需求列表和默认视口。
- 运行、AI 任务与数据：真实失败及部分成功记录可读，AI 生成和人工发布状态区分；数据列表显示 158 实体、分页加载 50 条。没有把既有记录冒充本轮新执行结果。

代表性证据：[来源列表](06-sources-1440.jpg)、[来源详情](03-source-detail-1024.jpg)、[Run 详情](04-run-detail-1440.jpg)、[实体详情](05-item-detail-1024.jpg)、[接入](07-onboarding-1024.jpg)、[未保存保护](08-unsaved.jpg)、[概览](09-overview-1440.jpg)、[设置](10-settings-1024.jpg)、[英文运行列表](13-runs-en-1024.jpg)、[英文 AI 列表](14-ai-list-en-1024.jpg)、[英文 AI 详情](15-ai-detail-en-1024.jpg)、[英文数据列表](16-data-en-1024.jpg)。

截图 03/06 在最终来源修复后重新采集；13–16 在列表修复后采集。检查期间旧 Vite 进程未观察到文件变化，已仅重启本次本地前端服务，并确认当前源码和样式已加载。其余截图对应本轮未修改的页面。缺失 Run 的合成失败与大计数由隔离 UI 回归验证，不将正常真实数据截图当作这些负向状态的证明。

## 验收边界

- P01 范围映射、P19 全量聚合与 G1 现有页面的技术验收通过；四份产品合同范围未扩展，规划及 G1 状态与本记录对齐。
- 本轮不重新初始化或退出既有用户会话，不执行真实来源发布/运行、模型调用、Webhook 或数据删除。登录与导出的本轮证据是自动化回归；真实浏览器专项证据沿用明确标注日期的 [2026-09-06 记录](../g1-2026-09-06/validation.md)，不宣称本轮重新完成导出文件核验。
- 来源/运行列表仍有既有分页与有限投影边界；规模性能、真实写入全链路、升级恢复、故障注入、72 小时观察与生产发布属于 G3/G4，不由单元测试或此次走查替代。
- 浏览器为 Chromium，未验收 Safari/Firefox，也不是完整 WCAG 审计。用户视觉偏好与最终产品签收仍需产品负责人确认。
