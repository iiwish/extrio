# 1.0 发布收尾执行包

日期：2026-10-06。模式：Governed Direct Execute。用户明确批准上一轮三个发布收尾工作包并要求继续完成。产品范围采用 `docs/planning/v1.0-scope-matrix.md`、`docs/product-contract.md`、`docs/SSOT.md`；发布闸门采用 `docs/releases/v1.0.0.md`。不增加功能，不扩大来源/模型预算。

## 工作图与权限

| 任务 | 状态 | 依赖 | 成果与退出条件 |
| --- | --- | --- | --- |
| CLOSE1 / 安全收敛 | Needs_Review | RQA1 修复复验及用户批准的收尾计划 | 调查与基础镜像整改已有实测；完整发现扫描为 374 个 Debian 记录、1 CRITICAL / 67 HIGH，仍无可修复项；风险登记及最终对象复验独立，未授予风险接受 |
| CLOSE2 / 候选验收与 PR | Needs_Review | CLOSE1 调查完成；安全例外可呈交但不能代为接受 | 本地冻结验证847后端/265前端、272桌面、116 API、64键盘及90+80 axe完成；候选提交并以Draft PR送独立审查，精确head的远程结果由该PR Checks记录；不得冒充最终产品签收 |
| CLOSE3 / 正式发行 | Requires Decision | 稳定版安全决策、产品/技术签收、PR CI；另行合并及发行授权 | main 精确提交、正式双架构扫描/签名/provenance、摘要安装升级恢复与发布；本任务不能越过独立人工闸门，生产部署另行授权 |

任务串行执行，`parallel: false`。当前工作树包含本聊天已验证的 RQA1 修复与两个未跟踪审查目录；全部保留。基线为 `f612c745abbbcf966fcfa3e365b3a620335a5d49`，远程 main 为 PR #34 的合并提交 `fa453a8aad7a0bd91dbabbaab673c3e133f0b367`，产品树一致。创建新 `codex/` 候选分支承接现有修改，不能覆盖已合并 PR #34 或无关 Dependabot 分支。

宿主未获用户委派授权，直接执行；不创建子代理或新聊天。CLOSE2 可交接未发布候选 PR，但风险接受和最终 `Accepted` 不由 PR 或自动测试代替。

## CLOSE1 允许范围

- `docker/backend.Dockerfile`：官方 Python 3.12 Debian 13 基础镜像，匹配 PGDG suite，采用运维合同要求的 PostgreSQL client 16，保留非 root 用户、冻结项目依赖与真实 Chromium；删除确认不需要的安装工具/虚拟显示工具。不得删除浏览器共享库、修改第三方源码或隐藏扫描目录。
- `backend/tests/test_backend_image_contract.py`：镜像边界回归；先确认旧 Dockerfile RED，再最小实现 GREEN。
- 本审查目录：执行、证据、风险登记、候选审查与交接；`docs/releases/v1.0.0.md` 及现有 manifest 生成器同步候选证据。
- CLOSE2 的测试脚本仅访问自有本地 G4 实例；不修改产品行为，复用原协议 fixture 和实际 API/Worker。
- CLOSE2 实际打开供应商弹窗后，双库均复现 `.credential-help` 的 `#738087` / 白色对比度 4.06:1；来源是 `source-setup-and-import.css` 的 `.field-group small` 比 `.credential-help` 具有更高 specificity。允许在该文件及已由 RQA1 修改的 `web/src/styles/settings.css` 将两个辅助文字选择器复用 `--muted-foreground`。原桌面静态页面 axe 未覆盖该弹窗；以真实弹窗 RED/GREEN 和双库复验支持本次文字色修改，不扩展布局或功能。弹窗扫描等待实际 CSS 动画完成，不把淡入中间帧当作稳定截图或验收。
- 最终容器完整恢复负向实测：PG17.11 `pg_dump` 生成的 custom archive 使用 PG16 未定义的 `SET transaction_timeout = 0`，恢复退出 1。`docs/self-hosted-operations.md` 已要求容器携带 PG16 客户端；允许在 Dockerfile 修正该客户端主版本，并更新镜像合同测试、重建、双库完整恢复与镜像扫描。不更改备份格式、过滤 SQL、降低校验或扩展支持到 PG17/18。
- CLOSE2 的详细 incomplete 复核确认命名 generic div 不具备可支持的命名角色，包括共享页头、概览可聚焦统计点与数据工具栏。允许在 `web/src/app/{app-shell,router}.tsx`，`features/home/home-page.tsx`、`features/items/items-page.tsx`、`features/runs/{runs-page,run-page}.tsx`、`features/settings/model-settings-page.tsx`、`features/collectors/{collectors-page,collector-page}.tsx`、`features/collections/{collections-page,collection-page}.tsx` 为现有命名容器赋予匹配的 group/img/status 语义，保留标签、内容、焦点、布局和行为。先确认页头/统计点/数据工具栏三项代表性单测 RED，再批量添加角色；补充脚本须拒绝这些表面的 generic 命名反例，最终全量与桌面回归。不对每个同类容器建立微任务，不把 incomplete 一概判为无问题。
- 需求列表已经由 ListWorkspace 的唯一 live status 报告加载状态；其装饰骨架使用 `aria-hidden`，不增加第二个同义 status。原“加载/读取失败不报告零”回归保持不变，不能用放宽查询掩盖重复状态通知。
- 原生库核对发现 Python lxml 6.1.2 静态携带 libxml2 2.14.6，不能以 OS 包扫描代替该副本的风险判断。官方 lxml 6.1.3 已修复 `resolve_entities="internal"` 仍读取外部参数实体的默认策略问题；允许仅定向更新 `backend/uv.lock` 的 lxml patch 版本与新增 `backend/tests/test_lxml_boundary.py`，不扩大依赖范围、不变更 XML/采集功能、不修改第三方源码。先用真实解析器探针确认外部 DTD 回调 RED 和内部实体正控制，再升级、全量与镜像复验。该 patch 不宣称解决全部 libxml2 <2.15.4 的原生漏洞。
- 允许在 `docs/self-hosted-operations.md` 与升级手册明确 PG16 备份/恢复客户端同主版本要求及升级前空实例恢复验证；不是引入高版本归档转换或数据库原地降级功能。同步 manifest 仅通过现有生成器。

禁止修改：产品合同、存储 schema、NLP/采集引擎架构、依赖锁定结果、扫描等级/忽略规则、生产配置/数据、其他项目容器。发生新的必修应用缺陷时先记录反例与必要范围，不擅自扩大任务。

## 执行前检查与分析

1. 范围确认：用户批准收尾，不等于接受无补丁风险、合并、创建正式 tag、运行 release 工作流、发布镜像或部署。
2. 调查基线：RQA1 最终 backend 镜像 513 个 Debian 包记录，4 CRITICAL / 91 HIGH；Python 仅剩无补丁 NLTK。扫描级别不能替代实际攻击面判断，也不能从测试未命中推出全局不可达。
3. 主来源核对：Debian Security Tracker 当前结构化数据、NLTK 公告及 Dependabot #1；Astral 官方多架构 manifest 与 Playwright Debian 13 支持说明。镜像升级须实际重建和验证，不能由版本号推断消除告警。
4. 移除 NLTK 会影响 Crawl4AI 的非可选导入/策略路径，不采用不完整卸载、vendor patch 或核心引擎重写。受影响模型文件 API 的既有 15 项边界证据须复验，告警保持 open。
5. 非 root/匿名只读来源/Schema 拒绝模型路径是当前保护边界；存在调用或未知暴露的项保持待决策，不能自行标为不适用。
6. 安全调查预算采用用户确认计划中的 2–3 小时检查点；外部等待另记。预算不是修复完成保证，不创建后台定时执行。

## 验证循环

先运行新增镜像合同 RED/GREEN；执行 Ruff、相关 15 项 NLTK 与关联安全/浏览器测试。用自有 Docker 标签重建 arm64 候选，运行 SQLite/PG16 的 `scripts/verify-compose.sh`；在最终非 root 容器运行真实 Worker 离线基准、RestrictedBrowser/Chromium，以及数据库/备份恢复所需能力检查。完整镜像扫描保留所有等级及未修复项，并重跑原 `HIGH,CRITICAL / ignore-unfixed / exit-code 1` 门禁；当前源文件扫描包含开发依赖，保存原始退出状态。

候选验收采用独立 PG16 和自有 G4 SQLite/PG 实例，不访问其他项目数据库、生产来源或付费模型。后端全量、前端 test/lint/build、四桌面中英文旅程、原 API/axe、OpenAPI/docset/制品按最终变化范围复验，既有证据保留日期与对象，不累计重复测试次数。人工签收、完整读屏器/WCAG 合规与长期 SLA 不得由自动化替代。

CLOSE2 提交前确认原报告与候选记录不含私有 QA 凭据，执行 `git diff --check` 和双层代码复核；新分支从当前工作树承接用户修改并验证与最新 main 的差异。创建 PR 后必须附加到本聊天并检查精确 head、必需 jobs 与失败日志。不得自动 merge、dismiss 告警或 approve 自己的 PR。

失败重试最多三次；不得删测试或放宽门禁换取绿色。需要用户安全决策时呈交具体选项，同时继续不受该决策阻挡的安全准备工作；不伪造最终发布完成。

## 证据与清理

证据必须包含原始扫描对象、时间、完整/过滤结果、主来源映射、已修复及未修复登记、命令退出状态、TDD、有效测试数、环境隔离与清理。CLOSE1/CLOSE2 至多推进为 `Needs_Review`，CLOSE3 保持待授权。

只清理本次自有测试容器、卷、网络、镜像标签、源码副本和 scanner cache；保留原始日志与脱敏证据。不做全局 prune，不停止其他项目服务。真实密码、浏览器会话和临时数据库在结束时删除。
