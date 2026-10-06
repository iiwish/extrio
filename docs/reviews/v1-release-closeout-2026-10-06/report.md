# 1.0 发布收尾候选验收

日期：2026-10-06，Asia/Shanghai。状态 `Needs_Review`；正式稳定版 `Requires Decision`。

本地工程收尾、风险登记和冻结候选验证完成。候选可送独立审查，不能直接发行；无补丁依赖/原生库风险、产品与技术签收、合并及正式发行授权仍独立。原始 QA 与 RQA1 修复证据保留，不把历史 RC 的检查移作本候选证明。

## 候选身份

- 分支 `codex/v1-release-closeout-20261006`，从 main `fa453a8aad7a0bd91dbabbaab673c3e133f0b367` 承接 RQA1 工作树；该 main 与原 RQA1 基线 `f612c745abbbcf966fcfa3e365b3a620335a5d49` 的产品树相同。
- 396 个产品源文件、锁文件、测试、构建/工作流和合同文件的 SHA-256 指纹为 `231529f7dfd4d4aadd9a9d863669019c524cd016e69a87b962193cb4f373a3e5`，见 [candidate-source.json](evidence/candidate-source.json)。提交前快照不冒充 Git commit；PR 身份与远程结果使用该 PR 的精确 head 和 Checks。
- 最终本地后端 arm64 Image ID：`sha256:e5e2a4a710d1c9045f082182710044752ca8be29023304ccf743fc93916cc4c2`。
- 最终本地 Web arm64 Image ID：`sha256:a4d46244e3de14eb69eddfca536ef28aee1ed58a43640a1c5ef219ab592e351d`。
- 本地 Image ID 不是正式 registry digest，不是 amd64、签名或 provenance 证明。没有创建正式 tag、运行 release 工作流或生产部署。

## 收尾成果

| 范围 | 实现与反例 | 最终结论 |
| --- | --- | --- |
| RQA1 五项修复 | 严格 Collector 文本校验、依赖更新/删除无关 CLI、文字对比度、质量条语义和基准真实产出断言 | 原负向 API/axe 探针未删减，冻结候选复验通过 |
| 基础运行镜像 | 官方 Python 3.12 / Debian 13 基础镜像按多架构 index 摘要固定；匹配 trixie PGDG；移除仅用于安装的 curl 与有头显示工具 xvfb/xserver-common，保留 Chromium 共享库 | 完整 OS 包记录 513 → 374，CRITICAL 4 → 1，HIGH 91 → 67；不表示零漏洞，新增未修复项也已登记 |
| PG16 完整恢复 | 实际 PG17.11 客户端归档恢复 PG16 失败于 `SET transaction_timeout = 0`；按运维合同采用 PG16 客户端，不修改归档、过滤 SQL 或放宽校验 | 最终非 root 容器内 SQLite/PG16 的数据库、Artifact、签名 key 与加密凭据完整恢复通过；高主版本工具产生的历史归档不被宣称兼容，升级前须独立演练 |
| lxml patch | 官方 6.1.3 修复 internal 模式读取外部参数实体的问题；真实解析器 Resolver 探针在 6.1.2 触发外部 DTD 回调并失败，内部实体正控制通过 | 定向升级 lxml 6.1.3；主机与最终镜像均阻止外部参数实体回调、保留内部实体；不声称修复全部 libxml2 原生漏洞 |
| 弹窗对比度 | 双库实测供应商弹窗密钥说明 4.06:1；`.field-group small` specificity 覆盖 `.credential-help`，两个选择器均使用既有 muted token | 弹窗所有支持桌面尺寸、中英文自动扫描通过；不更改布局、字号或文案 |
| 命名容器语义 | incomplete 详细节点确认页头、趋势统计点、工具栏等 generic div 的命名角色不适用；为同类容器添加 group/img/status，已有 live status 的列表装饰骨架隐藏 | 三项代表性语义测试先 RED，批量实现后全量通过；补充浏览器扫描拒绝 `aria-prohibited-attr` incomplete，结果为 0 |

## 冻结候选验证

| 验证层 | 真实结果 |
| --- | --- |
| 后端全量，独立 PG16 | **847 passed，0 failed / 0 skipped，231.77s**；包含原回归、32 个双库输入、10 个基准、2 个镜像合同与2 个 lxml 边界用例；[JUnit](evidence/backend-junit.xml) |
| 前端全量 | **42 文件、265 passed，33.42s**；代表性 ARIA 断言加入既有用例，不累计重复执行；[输出](evidence/frontend-test.log) |
| 实际双库有鉴权旅程 | 创建需求/字段发布、候选审核发布、Run/Item、签名 Webhook、CSV/JSONL 导出和刷新恢复；中英文 x 四桌面 x 17 页，**272 组、0 page errors/文档横向溢出** |
| 原 API 探针 | SQLite/PG16 各 **58/58，notRun=0**；鉴权/角色、CSRF、撤销、幂等并发及发布后 Run 无模型调用检查保留 |
| 原页面 axe | 双库 **90 次、0 确定违规**；包含登录、长内容与错误密码，不代表完整 AA 认证 |
| 补充键盘与详细 axe | 双库 **64 个键盘用例**，实际 Enter/Tab/Shift+Tab/箭头/Escape、焦点限制和返回；**80 次详细扫描**，其中32 次弹窗、48 次主页面，0 确定违规及0 generic 命名反例 |
| 最终容器能力 | SQLite/PG16 冷安装、health/setup/login/logout、完整备份恢复、受限 Chromium、本地离线 Worker 流水线通过；2 Run / 14 页 / 8 accepted / 新增未变各4 |
| lxml 原生边界 | 镜像内 lxml 6.1.3 / libxml2 2.14.6，两项解析器边界实测通过；[输出](evidence/image-lxml.json) |
| 构建与静态检查 | Ruff、前端 lint、TypeScript/Vite、OpenAPI 无差异、sdist/wheel、文档 manifest/专项检查通过 |
| 安全审计 | Web 全依赖 audit 0；Python audit 仅 NLTK 无补丁项；源码含开发依赖扫描 0 secrets；两镜像原可修复 HIGH/CRITICAL 门禁退出0 |

证据：[SQLite 旅程](evidence/browser-sqlite.json)、[PG 旅程](evidence/browser-postgres.json)、[SQLite API](evidence/api-sqlite.json)、[PG API](evidence/api-postgres.json)、[页面 SQLite](evidence/accessibility-sqlite.json)、[页面 PG](evidence/accessibility-postgres.json)、[键盘 SQLite](evidence/keyboard-sqlite.json)、[键盘 PG](evidence/keyboard-postgres.json)、[恢复](evidence/image-recovery.log)、[流水线](evidence/image-pipeline.log)、[Chromium](evidence/image-browser.log)。具体执行边界见 [verification.md](verification.md)。

## 无障碍人工判断

程序驱动的真实键盘事件不是人工读屏器认证。已人工检查四桌面代表性弹窗及操作台截图：焦点环清晰、辅助说明可读、长英文折行且不遮挡控件。没有逐像素检查全部截图。

详细 incomplete 的 generic 命名问题已实际修复；模态背景与 Radix focus guards 的 `aria-hidden-focus` 通过实际焦点限制/返回用例支持，保留规则结果。部分描述文本因 backdrop/遮挡检测、背景“未保存”标签因 pseudo element 仍为 `color-contrast` incomplete；截图、样式与颜色支持被测弹窗判断，不宣称其自动规则已通过或全站完整 AA。Safari/Firefox、真实读屏器与长期观测不是本次新增已验证成果。

## 安全与发行决定

[安全登记](security.md)与 [27 个 OS CVE 的逐项映射](evidence/os-risk-register.json)保持 open。没有接受任何例外、关闭 Dependabot 告警、增加忽略项或降低扫描等级。完整镜像另保留所有等级/未修复项；“可修复门禁0”不是“零风险”。

1. NLTK 3.10.3 无官方补丁；既有15 项边界及关联回归通过，只证明覆盖路径，稳定版风险决定仍须独立。
2. OS libxml2 仍有1 CRITICAL；其余67 HIGH 对应原生解析/浏览器依赖及系统工具。升级使20 个基线高等级 CVE 不再出现，也新增5 个报告项，不能用净减少数量替代攻击面复核。
3. Python lxml 静态携带 libxml2 2.14.6；LD 链接检查与包扫描不能证明所有原生 API 不可达。6.1.3 的参数实体修复不覆盖全部 <2.15.4 原生问题。
4. 十万观察/两万实体的既有查询性能风险保留，未设新的延迟承诺；支持规模与该影响属于产品签收，不冒充已经优化。

代码预检未发现本次候选新增的未修复阻断性应用回归；该结论不关闭上述安全与验收风险。送审 PR 必须获取精确 head 的必需 CI；合并后 main 精确提交、正式双架构扫描/签名/provenance 与准确摘要安装仍独立。CLOSE3 保持 `Requires Decision`，产品/技术验收不能由本报告代签。
