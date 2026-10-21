# Extrio 1.0 发布测试报告

测试日期：2026-10-06，Asia/Shanghai。结论：**NO-GO，当前候选不具备稳定版发布条件。**

核心功能回归、双库安装和主操作链通过，但本次新构建的后端镜像未通过现行安全发布门禁；独立负向 API 测试及无障碍测试也发现待处置缺陷。通过数量不抵消失败门禁。本报告不批准发布、部署或风险接受。

## 1. 测试对象与方法

| 项目 | 本次对象 |
| --- | --- |
| 工作区提交 | `f612c745abbbcf966fcfa3e365b3a620335a5d49`，`codex/v1-stable-closeout-20260927` |
| 远程 main | `fa453a8aad7a0bd91dbabbaab673c3e133f0b367`，PR #34 已合并 |
| 源码树 | 两者均为 `1755478777d3f62d7d135204cf11e817d99b1084`，不是两个不同源码版本 |
| 源码版本 | Python/Web 均为 `1.0.0`；正式稳定版 Release 不存在，最近相关制品为 `v1.0.0-rc.1` |
| 本地环境 | macOS 26.5.2 arm64、Python 3.12.13、Node 24.15.0、pnpm 11.24.0；容器前端使用 Dockerfile 的 Node 22 构建 |
| 数据库 | 独立 SQLite；新建本地 PostgreSQL 16 容器及临时数据库，不复用其他项目数据库 |
| 浏览器 | 实际 Chromium，生产构建预览，真实有鉴权 API/Worker；不是 MSW 页面测试 |
| 视口 | 1440x900、1280x800、1132x1028、1024x800；中文/英文，无移动端验收 |
| 外部边界 | 本地公开页面 fixture、HTTPS 模型协议 fixture、签名 Webhook 接收端；未调用真实付费模型、未访问生产数据 |

方法包括范围合同核对、全量回归、独立反例、持久化/并发验证、桌面截图检查、axe-core 自动化无障碍检查、十万行数据检查、冷安装、制品构建、当前漏洞数据库扫描和远程精确提交核对。

原有后端套件的大量控制面测试明确关闭鉴权，因此不能仅凭 801 项通过宣称完成角色验收。本次额外使用真实登录会话执行双库主旅程和角色/撤销/CSRF/API 负向测试。

## 2. 发布问题

### QA-01 / P1：后端候选镜像失败于现行安全发布门禁

**结果：Fail，必须阻断发布。** 新构建的本地 `linux/arm64` 后端镜像，在 `--ignore-unfixed --severity HIGH,CRITICAL --exit-code 1` 下退出 1，检出 **1 CRITICAL、7 HIGH，均有修复版本**。这是实际候选运行镜像扫描，不只是锁文件告警。

扫描绑定的后端 Image ID 为 `sha256:b941974973de7ed19944b339c8c27344a6a8277502040e07555887dd1cbcc321`。同轮 Web 运行镜像在相同等级门禁下通过。正式门槛见 [.github/workflows/release.yml:100](/Users/iiwish/self/extrio/.github/workflows/release.yml:100)。

| 依赖 | 已安装版本 | 本次镜像可修复 HIGH/CRITICAL | 扫描给出的修复版本 |
| --- | --- | --- | --- |
| PyJWT | 2.13.0 | 1 CRITICAL + 5 HIGH | 2.14.0；其他已知问题需要 2.15.0，升级须覆盖完整告警集 |
| urllib3 | 2.7.0 | 2 HIGH | 2.8.0 |

版本定位：[uv.lock:1533](/Users/iiwish/self/extrio/backend/uv.lock:1533)、[uv.lock:2089](/Users/iiwish/self/extrio/backend/uv.lock:2089)。[扫描证据](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/backend-image-security.json)。

PyJWT 经 `mcp[crypto]` 引入，urllib3 经 requests/Crawl4AI 等引入。应用登录使用持久化随机会话，MCP 使用静态 bearer 校验；本次未证明 PyJWT 公告中的混合算法前提在 Extrio 登录路径可达，**不能据此声称登录已经能被绕过**。发布阻断依据是确实失败的既定镜像门禁，而非未经验证的攻击结论。[PyJWT 官方公告](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9)、[urllib3 官方公告](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw)。

修复方向：更新受影响传递依赖及锁文件，覆盖 pip-audit 的完整修复集合，重新构建后端，回归 MCP、网络/TLS、浏览器和身份边界。不得降低扫描等级或把这些有修复版本的问题作为 NLTK 例外的一部分。正式发布仍需要 amd64/arm64 各自制品的扫描、签名和 provenance。

### QA-02 / P2：创建来源对非法字段类型返回 500 并错误标记可重试

**结果：Fail，SQLite/PostgreSQL 均复现。** 有权限的 engineer/administrator 调用 `POST /api/v1/collectors`，传入数字 `name`、数组 `name` 或数字 `intent`，返回 `500 INTERNAL_ERROR`、`retryable:true`，而非合同要求的输入校验错误。每库 3 个负向用例失败，共 6 次失败，对应同一个缺陷。

最小请求体示例：

```json
{"name":123,"intent":"QA","sourceUrl":"https://example.com/qa-release-probe"}
```

使用独立测试登录会话和新的 `Idempotency-Key` 即可复现，不需要请求来源站点。入口在 [app.py:1885](/Users/iiwish/self/extrio/backend/src/extrio/app.py:1885) 用 `str(...)` 检查非空，随后对原始值调用 `.strip()`，非字符串因此触发异常。

影响：API/MCP 集成客户端收到错误的服务故障分类和重试提示，不能准确定位字段错误。浏览器正常表单使用字符串，因此主 UI 成功路径和现有全量回归没有揭示此问题。未观察到该输入产生数据损坏。

修复方向：在任何字符串操作前验证 `name`/`intent` 为字符串，返回 `422 VALIDATION_FAILED` 与字段 pointer，并加入双库 API 回归。证据：[SQLite](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/api-probes-sqlite.json)、[PostgreSQL](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/api-probes-postgres.json)。

### QA-03 / P2：可见文本对比度不满足 1.0 的 WCAG AA 合同

**结果：Fail。** axe-core 4.13.0 对登录页及 11 个操作页面进行 45 次真实浏览器扫描：11 页 x 2 语言 x 2 视口，加中文登录页。41 个扫描出现 `color-contrast` 失败。扫描基于实际渲染颜色、字体和背景，不以截图观感替代测量。

| 示例 | 实测比值 | 要求 | 定位 |
| --- | --- | --- | --- |
| 概览辅助说明，12px | 3.69:1 | 4.5:1 | `#7a878d` / `#ffffff` |
| 来源当前阶段，10px | 3.44:1 | 4.5:1 | `#7a878d` / `#f5f7f8` |
| 登录说明，13px | 4.43:1 | 4.5:1 | [app-shell-and-auth.css:313](/Users/iiwish/self/extrio/web/src/styles/app-shell-and-auth.css:313) |
| 来源策略标签，12px | 4.41:1 | 4.5:1 | [review-schedule-and-policy.css:505](/Users/iiwish/self/extrio/web/src/styles/review-schedule-and-policy.css:505) |

这些是可见、非禁用的操作说明和状态标签，不能按装饰或禁用控件豁免。普通文本门槛依据 [W3C SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)。低对比度影响低视力用户和长时间运营扫描；本次不能签出 WCAG 2.2 AA 通过。

修复方向：按可见语义统一调整辅助文本颜色，保持实测比值留有余量，复验中英文、实际背景及错误/成功/禁用状态。没有要求重做界面。证据：[accessibility.json](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/accessibility.json)。

### QA-04 / P3：概览质量条使用被禁止的 ARIA 命名属性

**结果：Fail，非核心功能阻断项。** 两种语言和两个视口均检出 `aria-prohibited-attr`：`.overview-quality-bar` 是没有可命名语义角色的普通 `div`，却设置 `aria-label`。定位：[home-page.tsx:182](/Users/iiwish/self/extrio/web/src/features/home/home-page.tsx:182)。

旁边已有可见文字统计，因此不把这个问题等同于统计数据完全不可访问。建议赋予符合图形语义的角色和标签，或将其标为装饰并由现有文本表达统计，然后进行读屏验证。265 个失败节点实例包含不同语言/视口的重复结果；45 个规则实例不是 45 个独立缺陷。

### QA-05 / P3：基准脚本可在没有提取任何数据时假绿

**结果：测试基础设施缺口，不是生产时间窗口缺陷。** 原样运行 `scripts/benchmark.py --collectors 3 --pages 2` 退出 0，6 Run 均 `succeeded`，但总计只取 12 列表页、0 详情页、0 accepted Item。fixture 日期为 2026-08-29/30，已在当前日期默认 30 天首采窗口之外，`time_window_reached` 是合理生产行为。

脚本只检查终态：[benchmark.py:491](/Users/iiwish/self/extrio/scripts/benchmark.py:491)，因此该次绿色结果不能证明详情提取、实体提交或去重路径。不要把这次结果当成有效采集吞吐证明。

本次用独立正控制把**进程内合成页面 fixture 日期**设为当日，不改变产品源码、采集策略或真实 Worker/Crawlee：6 Run 均成功，42 页、24 accepted，其中初次新增 12、再次未变化 12；对正数产出和重复观察进行了明确断言。[正控制证据](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/pipeline-positive-control.json)。建议基础脚本采用相对 fixture 日期或明确窗口，并断言预期产出。

## 3. 安全扫描与风险决策

| 检查 | 当前结果 | 解释 |
| --- | --- | --- |
| tracked source secret 扫描 | 0 secret | 对 `git archive HEAD` 扫描，不读取用户 `.env`、运行数据库或私有目录 |
| Trivy 源码依赖 | 后端 19、Web 23 条 | 当前数据库范围内的发现数，不能与其他扫描器相加作为独立漏洞数 |
| pip-audit 安装环境 | 19 条 / 4 包 | PyJWT、urllib3、multidict、NLTK；项目自身不是 PyPI 包，审计器不评估其私有代码 |
| pnpm 官方 registry audit | 37 条：1 critical、13 high、17 moderate、6 low | 包含构建/测试工具链；不是 37 个生产浏览器可利用漏洞 |
| GitHub Dependabot | 45 open：1 critical、17 high、21 medium、6 low | 当前远程快照；安全状态已不同于 2026-09-27 的验收记录 |
| 本地后端运行镜像 | Fail：1 CRITICAL、7 HIGH 可修复 | 与发布规则一致的真实门禁失败 |
| 本地 Web 运行镜像 | Pass：0 可修复 HIGH/CRITICAL | Nginx + 静态构建制品，不包含 Node/shadcn 开发运行环境 |

前端 `shadcn` 列在 dependencies，但涉及的 Node 工具链经 `pnpm why` 定位，不应直接认定为线上浏览器运行攻击面。`proxy-addr` 的 critical 告警来自 shadcn/MCP SDK/Express；本次没有证明最终静态站点使用 Express。仍应治理工具链锁文件与构建输入风险。[依赖链](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/web-dependency-paths.txt)、[Python 依赖链](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/python-dependency-paths.txt)。

**NLTK 风险仍需稳定版独立决策。** `3.10.3` 的 `GHSA-8mgp-746c-j5xp` 仍无修复版本。全量回归包含现有 15 项 NLTK 边界测试，均通过；这只证明覆盖路径没有触发受影响 API，不是全局不可达证明。RC 风险接受不能替代稳定版接受。[官方公告](https://github.com/nltk/nltk/security/advisories/GHSA-8mgp-746c-j5xp)。

本次使用的 Trivy 为 0.75.0，扫描器镜像摘要为 `sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa`。正式流水线的版本、时点、平台和最终摘要仍必须独立核验，本地扫描不替代远程发行证明。

## 4. 本次实际执行结果

| 验证层 | 本次结果 |
| --- | --- |
| uv / pnpm 锁文件安装 | 通过，未更新锁文件 |
| 后端全量 | **801 passed，0 failed，0 skipped，282.89s** |
| 前端全量 | **42 文件、264 passed，37.44s** |
| Ruff、前端 lint | 通过 |
| TypeScript + Vite 生产构建 | 通过 |
| OpenAPI 类型重新生成 | 通过，生成文件与 Git 无差异 |
| docset manifest | `--check` 通过 |
| Python sdist / wheel | 构建通过，wheel 内存在合同、OpenAPI 和迁移资源 |
| 真实有鉴权主旅程 | SQLite / PostgreSQL 各一条完整旅程，通过 |
| 页面/语言/视口组合 | **272 组通过**，每库 136；0 page errors、无文档级横向溢出 |
| CSV / JSONL 导出 | 双库下载成功，解析后包含实际提取数据 |
| 签名 Webhook | 每库首次主旅程 1 次送达，HMAC / Content-Digest / Idempotency-Key 检验通过 |
| 补充 API 探针 | 每库 58 例：55 通过、3 失败；合计 110/116，通过未覆盖部分见 QA-02 |
| 发布后运行不调用模型 | 双库成功产出各 1 Item，模型调用日志无增加；重复请求复用同一 Operation |
| 同键并发创建 | 每库 12 个请求产生 1 个逻辑资源，11 个重放 |
| HTML / XSS / 长内容 | 200 字符需求名保持纯文本，4 个语言/视口组合无执行或横向溢出 |
| 错误与恢复 | 登录错误有可见 alert；503 读取故障显示错误，撤销故障并刷新回到已持久化需求 |
| 冷 Compose 安装 | SQLite / PostgreSQL 16 均 build/up/health/setup/login/logout 通过并清理 |
| 实体/导出规模 | 双库各 100,000 observations；遍历 20,000 最新实体无重复/遗漏，100,000 行导出计数一致 |
| 正控制真实流水线 | 6 Run、42 页、24 accepted，新增/未变化各 12，全部明确断言通过 |
| WCAG 自动化 | 45 次扫描，2 类失败规则；未签出完整 AA 合规 |

全量后端覆盖迁移与历史版本绑定、RC/Alpha/历史基线升级回退、备份校验/空实例恢复、权限与会话、限流/代理、SSRF/受限浏览器、租约/崩溃接管、交付重试/死信和证据访问等。完整逐例证据见 [JUnit](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/backend-junit.xml)。浏览器主旅程不能替代所有迁移/死信/恢复操作的人工 UI 验收。

### 存储层规模测量

数据为每库 100,000 条观察、20,000 个实体、每实体 5 个历史版本，正文约 1KB。首屏每种视图测 5 次；这是 Store 调用，不是 HTTP 全链路或长期 SLO。

| 指标 | SQLite | PostgreSQL 16 |
| --- | --- | --- |
| observations 首屏中位数 | 2.32ms | 11.79ms |
| entities 首屏中位数 | 1426.78ms | 1013.78ms |
| entities 首屏最大值 | 2251.91ms | 5409.38ms |
| 20,000 实体完整游标遍历 | 21.56s | 18.61s |
| 100,000 条观察导出 | 811.48ms | 1524.50ms |

计数正确性通过；实体聚合首屏明显比观察列表慢，需作为运营规模风险保留。共享本机上只有 5 个样本，不能当作 p95/p99、容量上限或生产延迟保证。[SQLite 测量](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/scale-sqlite.json)、[PostgreSQL 测量](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/evidence/scale-postgres.json)。

## 5. 桌面旅程与截图

所有截图来自本次实际运行，保存后进行了代表性人工图像检查，未借用历史审计图片。以下截图保留原始像素，不修改视觉证据。

1. 登录：功能正常，错误密码显示明确提示；登录说明有轻微但确定的对比度失败。对应 QA-03。
2. 创建需求、保存字段草稿、发布不可变字段版本、关联来源：双库正常，刷新后版本与数据保持。
3. 生成候选、样本校验、人工审核发布：双库正常；协议模型为合成 fixture，不是实际模型质量证明。审核弹窗 Escape 关闭后焦点回到发起按钮。
4. 已发布来源配置与运行：最小桌面布局正常，来源规则和字段版本有明确状态；辅助状态文本存在 QA-03。
5. Run/Item/AI 详情、签名交付、CSV/JSONL：真实数据链路正常，固定版本谱系可核对；详情辅助文字需改善对比度。
6. 故障与恢复：503 保持错误状态而非空数据/成功，解除故障后恢复同一需求。
7. 长名称、HTML 内容、概览、中英文及四视口：无脚本执行/文档溢出；概览质量条有 QA-04，辅助文字有 QA-03。

![登录：1440x900，中文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/01-login-zh-1440.png)

![候选审核：1440x900，中文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/02-rule-review-zh-1440.png)

![已发布来源：1024x800，中文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/03-published-source-zh-1024.png)

![Run 结果：1024x800，英文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/04-run-en-1024.png)

![503 读取故障：1440x900，中文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/05-read-error-zh-1440.png)

![200 字符纯文本名称：1024px 桌面，英文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/06-long-content-en-1024.png)

![概览：1440x900，中文](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/screenshots/07-home-zh-1440.png)

## 6. 远程证据与未验证范围

远程 main 的 CI 和 Container verification 在 2026-09-27 成功，绑定 `fa453a8...`；PR #34 的 head 检查也成功。本次核对的是实际远程状态，不把本地提交 SHA 与 squash merge SHA 混用。[远程检查快照](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/remote-checks.json)。

以下不计为本次通过：

- 没有执行正式 `v1.0.0` tag/release、发布镜像、生产部署、双架构正式制品签名或 provenance。
- 没有新做 amd64 制品验证。arm64 本地镜像失败已足以阻断，不能沿用 RC 的双架构成功结果。
- 未追加真实模型调用与真实来源兼容性测试；历史 P28 材料不标成本次新证据。
- 没有真实生产代理/HTTPS/证书链、外部 Webhook、线上 RPO/RTO、容量或月度 SLA 验收。
- 没有 72 小时观测。本版本既有豁免只表示豁免，不表示通过。
- 未使用 Safari/Firefox 或真实读屏器；axe、少量焦点检查与截图不能证明完整无障碍合规。axe 的 incomplete 结果需人工判断。
- 本次浏览器主要验证管理员主旅程；多角色实时 API 覆盖及现有 UI 单测不等于每个角色的所有浏览器操作都已完成。
- 没有逐像素人工审阅所有 321 次截图捕获；自动化覆盖 272 个页面组合和 45 次补充扫描，人工检查代表性状态。

## 7. 重现与证据索引

详细命令、环境变量边界与原始输出目录见 [verification.md](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/verification.md)。新增三个测试脚本仅用于隔离验收，不改变产品实现。

补充 API 脚本和无障碍脚本当前退出 1 是预期的真实失败记录，不能删除用例或改成容许 500/低对比度来取得绿色。`pipeline-positive-control.py` 为通过的正控制。

本地 npm 镜像 registry 缺少审计 endpoint，初次 audit 不可用，已切换官方 registry 成功取得漏洞结果；两个 Trivy 镜像扫描共用缓存时 Web 首次遇到缓存锁，后端结束后串行重试通过。这两项是测试环境失败，不归为产品缺陷，也未跳过检查。

## 8. 重新准出条件

1. 处置 QA-01：完整依赖风险集合修复，最终后端镜像可修复 HIGH/CRITICAL 为零；Web 工具链风险另行处置，不用静态 Nginx 镜像通过掩盖源码风险。
2. 对 NLTK 的未修复风险取得稳定版独立接受，或提供已验证修复与完整回归。
3. 修复 QA-02、QA-03 并使本次反例转绿；若有不阻断的 P2 例外，必须记录实际影响、负责人、期限和明确产品接受。QA-04/QA-05 不得标作已修复。
4. 重跑双库回归、真实有鉴权旅程、构建/类型/文档检查、安装与关键持久化验证，绑定修复后的精确提交。
5. 最终产品/技术签收后，按独立授权执行 main/tag/release 的双架构门禁。生产部署单独授权。

本次只增加测试脚本、报告、脱敏证据和截图；没有修改后端/前端实现、锁文件、产品合同、CI 策略或正式验收状态，没有提交/推送、合并或触发发布。
