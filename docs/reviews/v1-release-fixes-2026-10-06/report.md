# 1.0 发布测试问题修复复验

日期：2026-10-06，Asia/Shanghai。任务 RQA1，状态 `Needs_Review`。

**QA-01 至 QA-05 的可修复问题已修复并复验通过；稳定版仍须安全风险决策、产品/技术签收和正式发行门禁，不直接签出发布。** 未修改扫描等级，未接受 NLTK 或基础系统的残余风险，未提交、推送、发布或部署。

## 候选身份

- 基线提交：`f612c745abbbcf966fcfa3e365b3a620335a5d49`。
- 对象：该基线上的未提交工作树，不冒充新的 commit、PR head 或 main 检查。
- 394 个产品源码、锁文件、测试、构建与合同文件的 SHA-256 指纹：`d9deb26aa0338be76901c6dd17b8680cc9db9bfaee891d7dd0eb059c0a2fd4fb`。逐文件哈希见 [candidate-source.json](evidence/candidate-source.json)，含新文件的差异见 [candidate.patch.gz](evidence/candidate.patch.gz)（无损压缩，保留统一 diff 的上下文空行）。
- 原始失败基线保留在 [发布测试报告](../v1-release-qa-2026-10-06/report.md)，没有覆盖历史失败或修改探针预期。

## 修复与反例

| 问题 | 实现 | 当前结果 |
| --- | --- | --- |
| QA-01 / 安全依赖 | PyJWT 2.15.1、urllib3 2.8.0、multidict 6.9.1；前端移除不需要的 shadcn CLI，保留实际使用的 8 个等价 Radix 状态变体；定向更新 source-map-js 1.2.2、fast-uri 3.1.8、brace-expansion 2.1.7、undici 8.11.2 | pnpm 全依赖审计 0 告警，pip-audit 仅剩无补丁 NLTK；最终后端/Web arm64 镜像可修复 HIGH/CRITICAL 均为 0 |
| QA-02 / 非法 Collector 文本 | 字符串操作前验证 `name`/`intent` 的类型及非空值；返回 422、字段 pointer 与 `retryable:false`；保留合同未定义上限的原有兼容性 | 32 个双库回归覆盖 null、数字、布尔、数组、对象、空串、纯空白；无 Collector/Collection 写入，修正输入可复用同一幂等键并重放；原探针每库 58/58 |
| QA-03 / 对比度 | 辅助文色复用 `--muted-foreground: #596b74`，Tabs 不使用半透明前景色；不改布局、字号、状态色、边框或图表填充 | 在原失败背景上的计算比值为 4.93–5.56:1；双库实际 axe 各 45 次扫描，无 `color-contrast` 违规 |
| QA-04 / ARIA | 质量条使用 `role="img"` 与已有双语统计名称；加载或读取失败且无数据时隐藏图形语义，不报告虚假零值 | 单测覆盖已加载、加载中、读取失败三种状态；双库中英文浏览器扫描无确定 ARIA 违规 |
| QA-05 / 基准假绿 | 仅进程内合成 demo 日期设置在当前窗口内；逐 Run 验证详情数、accepted/rejected、初次新增、重复未变化及完整 Run 覆盖 | 10 个回归覆盖空产出、详情缺失、少量产出、拒绝、新增/未变误分类、更新异常、失败终态、漏 Run 及 2026/2040 日期；真实 6 Run、42 页、24 accepted、新增/未变各 12 |

后端输入修复见 [app.py:1885](/Users/iiwish/self/extrio/backend/src/extrio/app.py:1885)。前端状态变体是已检入组件所需的 CSS，不引入新的运行框架；生成组件、Radix、Tailwind 和动画行为保留。移除 CLI 同时消除了其无补丁 `braces` 与 Express/MCP 等不必要工具依赖，而非移动到 devDependencies 隐藏告警。

TDD：实现前新增回归为 25 failed / 1 passed / 16 skipped，跳过部分是尚未启动 PG 的用例；原发布测试已对双库各复现 3 个类型失败。前端新增语义断言为 1 failed / 3 passed；补充加载/错误状态保护前为 2 failed / 3 passed。启动独立 PG16 后，42 个新增后端回归全部通过，全量套件无跳过；原 API/axe 探针未删减、未放宽。

## 实际复验

| 层次 | 结果 |
| --- | --- |
| 后端全量，独立 PostgreSQL 16 | **843 passed，0 failed，0 skipped，444.83s**；包含 32 个双库输入用例、10 个基准用例及原迁移/恢复/权限/租约/网络/NLTK 回归 |
| 前端全量 | **42 文件、265 passed，29.02s**；包含质量条加载/失败状态回归 |
| 真实有鉴权主旅程 | SQLite/PostgreSQL 均通过创建需求、字段版本、候选审核发布、Run/Item、签名 Webhook、CSV/JSONL 导出与刷新恢复 |
| 桌面矩阵 | 两语言 x 四尺寸 x 17 页面 x 双库，**272 组通过**；0 page errors，无文档横向溢出 |
| 原 API 探针 | **116/116**，每库 58；保留角色/CSRF/撤销/最后管理员/同键并发/发布后运行无模型调用检查 |
| axe-core 4.13.0 | 双库合计 **90 扫描、0 确定违规**；包含登录、长内容、11 个页面、中英文及 1440/1024 视口 |
| Ruff、前端 lint、TypeScript/Vite build | 通过；Docker 前端 Node 22 构建也通过 |
| OpenAPI、docset、sdist/wheel | 类型无差异、文档 manifest 检查、制品构建通过 |
| 最终镜像冷安装 | SQLite/PostgreSQL16 均 health/setup/login/logout 通过，独立数据卷、自动清理 |
| 最终非 root 容器 Worker | `--network none` 下真实离线流水线，2 Run、14 页、8 accepted、新增/未变各 4 |
| 最终容器受限 Chromium | 真实 RestrictedBrowser 获取本地页面 200，检查实际 DOM；基础解释器不存在 pip，未依赖被移除工具 |

证据：[后端 JUnit](evidence/backend-junit.xml)、[前端全量](evidence/frontend-test.log)、[SQLite 浏览器](evidence/browser-sqlite.json)、[PostgreSQL 浏览器](evidence/browser-postgres.json)、[SQLite API](evidence/api-probes-sqlite.json)、[PostgreSQL API](evidence/api-probes-postgres.json)、[SQLite 无障碍](evidence/accessibility-sqlite.json)、[PostgreSQL 无障碍](evidence/accessibility-postgres.json)、[基准](evidence/pipeline-benchmark.log)、[容器流水线](evidence/image-pipeline.log)、[容器 Chromium](evidence/image-browser.log)。详细命令及未通过的中间尝试见 [verification.md](verification.md)。

## 安全边界

镜像扫描使用 Trivy 0.75.0，扫描器摘要 `sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa`。最终门禁保持 `--ignore-unfixed --severity HIGH,CRITICAL --exit-code 1`，两镜像退出 0；另保留不筛选等级、不忽略未修复项的后端完整扫描。

| 最终本地对象 | Image ID / 结果 |
| --- | --- |
| 后端 linux/arm64 | `sha256:4836277e2b0e4b1e305d2f6ba9e6169c798486c3ece92449ea679c20174c6ccd`；[门禁](evidence/backend-image-gate.json) 0 可修复 HIGH/CRITICAL |
| Web linux/arm64 | `sha256:86781a050a9cf39c0a20a5a4db4dd655bb75071f27ff09a0615e1c358a4cf399`；[门禁](evidence/web-image-gate.json) 0 可修复 HIGH/CRITICAL |
| Python 安装环境 | [审计](evidence/python-audit.json) 1 条、NLTK 3.10.3、无 fix version |
| Web 全锁文件 | [官方 registry audit](evidence/web-audit.json) 0，包含开发/测试依赖 |

完整镜像扫描识别出基础 pip 25.0.1 的 6 条可修复告警。升级 26.2.0 的中间候选仍有受影响 vendor 包并失败于门禁，未用于最终准出。最终 Dockerfile 在浏览器/Crawl4AI setup 和 frozen uv 同步完成后卸载基础 pip；不修改项目虚拟环境、不忽略扫描路径，保留 uv 与生产能力。最后一次完整扫描的所有可修复告警为 0。

**未修复风险没有被关闭：**

- NLTK `GHSA-8mgp-746c-j5xp` 仍无官方补丁。15 个既有边界用例本次仍通过，只能证明覆盖路径未触发受影响 API，不是全局不可达证明。[官方公告](https://github.com/nltk/nltk/security/advisories/GHSA-8mgp-746c-j5xp)。
- [完整镜像结果](evidence/backend-image-full.json) 还包含 513 条 Debian 包-漏洞记录，均无 FixedVersion，其中 4 CRITICAL、91 HIGH。Status 分为 367 affected、125 fix_deferred、21 will_not_fix；包记录不是独立可利用漏洞数。既定门禁排除未修复项，不代表这些风险被消除或接受；发行前需结合运行攻击面复核基础系统风险。
- 未修改基础发行版、擅自修补第三方源码或隐藏告警。更换基础系统与 NLTK 依赖架构不是本次局部修复的已验证成果。

## 人工复核与剩余门槛

已检查概览 1440、来源 1024、AI 详情 1132、模型设置 1280 的本次截图：辅助文本清晰，密度与列布局保持，无遮挡/错位。实际交互覆盖审核弹窗 Escape/焦点返回、Tabs、菜单、开关、错误恢复与长名称。精选截图在 [screenshots](screenshots/)。未人工逐像素检查全部截图。

axe 的 incomplete 仍需人工判断，本次不宣称完整 WCAG 2.2 AA 或真实读屏器验收；未新测 Safari/Firefox、真实付费模型、外部生产来源/证书链、长期 SLA、72 小时观测或实体查询性能优化。原十万行实体首屏性能风险保留，不因颜色/API 修复消失。

范围合规复核：只修复已报告边界与工具链，产品合同与存储结构不变。代码复核未发现新的阻断性应用回归；自动化与实测结果支持五项修复，但无补丁依赖/系统风险、正式双架构制品、远程精确提交 CI、签名/provenance 与产品/技术签收仍独立。不得把未提交工作树或本地 arm64 验证当作正式 `v1.0.0` 发布证明。

测试服务与临时数据库已关闭，自有 Compose 容器/网络/卷及测试镜像标签已清理；真实账号、生产数据和其他项目服务未动。原始日志在受忽略的 `backend/data/v1-release-fixes-20261006/`，QA 密码与会话文件已删除。
