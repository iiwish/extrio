# 异常复验与三包适配执行包

任务 `CATALOG-FOLLOWUP-20261023`。用户批准：先复验受工具异常影响的 143 个入口并更新矩阵，再推进高校、河南交易中心、浙师大三个模板适配包并补回归。零付费模型、不访问现有业务库、不启调度、不合并发布部署；本任务不自动提交推送。沿用本地 `codex/catalog-validation-20261023`，保留全部既有未提交工作。

## 范围与验收

- 第一阶段严格选择原批次 `unexpected_error:AttributeError` 40 行和 `host_blocked:unexpected_error:AttributeError` 103 行，合计主表 54、复核表 89。使用已修复代码及独立账本；主表最多一页列表、两条详情，复核表只读列表。不覆盖原批次或把离线修复当成实测。
- 第一阶段代码冻结期间，worker 仅编辑独立的新模板文件和测试，不修改被执行的 catalog/runner。复验结果与原 1364 行按稳定 ID、输入指纹合并，保留原状态、最新状态、批次、代码与结果指纹。未选择行沿用原证据，不伪造复验时间。
- 第二阶段以原报告候选池为边界：高校 16 个精确主机的 `index.chtml` 栏目、河南内乡/南阳/镇平 3 主机、`cgzx.zjnu.edu.cn`。候选池为主表 69 行、相关复核 33 行共 102 行。西电 1 行有原批次网络停止且无详情结构证据，保留旧证据、不用新账本重请求；实际采样 101 行（主表 68、复核 33），19 个主机。复核行的最多两条详情需显式 opt-in，原 group/ID 不变；默认 review 仍不抓详情。
- 只采用保存响应证明的精确主机、路径与 DOM 结构；路径相似不等于同模板。不放宽全局标题、发布日期、未来日期、公告语义、非导航正文及 PDF/iframe 拒收规则。未知结构明确待适配，不以候选列表或 HTTP 200 报成功。
- 真实请求统一由主执行者运行，沿用 SourceNetwork 的公开 IP、robots、精确主机、80/443、证书与 HTTPS 禁降级。每主机串行且至少 2 秒、最多 4 主机并发、单页 2 MB、单行 60 秒。每行列表诊断最多 3 次物理请求、两详情采样最多 12 次；每批最多 8000 请求/1 GB/90 分钟，不靠恢复清零预算或重试限制。跨阶段同主机的真实限制不得被新账本清除。
- 无分页、JS 执行、PDF/OCR、附件遍历、未知跨站原文、账号或代理。正文及响应仅在仓库外私有目录（0700/0600），不进入 Git、测试 fixture、日志或发行包。可用最小合成模板做回归，不拷贝真实联系人或公告正文。
- 三包集成后先离线回归与独立审查，再冻结代码、真实限量采样、合并最终矩阵。样本通过仍不代表原生签名规则、完整业务字段、近 30 天覆盖、增量或生产就绪。

## 并行执行单元

均为 `parallel: true`，文件所有权不重叠；worker 不得再委派、触网、修改原输出或回滚他人工作。共同接口：`extract_detail(soup: BeautifulSoup, url: str) -> tuple[str, str, Tag | None] | None`，返回页面提取的原始标题、原始发布日期文本、正文 Tag；不匹配精确主机/路径/结构返回 None。禁止从列表 candidate 填造详情标题/日期。质量门槛由 catalog 共用，不在模板模块自行宣称通过。

- A001 高校：仅 `scripts/tender_sources/catalog_template_university.py`、`backend/tests/test_catalog_template_university.py`、本目录 `university-evidence.md`。先检查保存样本的结构，确认实际共享布局后按精确主机映射选择器。覆盖正常、缺字段、错误主机/路径、页脚日期、导航伪正文和嵌入正文，先 RED 后最小实现。
- A002 河南：仅 `scripts/tender_sources/catalog_template_henan.py`、`backend/tests/test_catalog_template_henan.py`、本目录 `henan-evidence.md`。主机仅内乡、南阳、镇平；核对交易路径、标题及日期/正文区域，保留公告类型与栏目身份。相同负例与 RED/GREEN。列表锚点的独立标题与日期节点允许通过精确结构 helper 提取，禁止通用字符串截日期或放宽标题一致性。
- A003 浙师大：仅 `scripts/tender_sources/catalog_template_zjnu.py`、`backend/tests/test_catalog_template_zjnu.py`、本目录 `zjnu-evidence.md`。精确 `cgzx.zjnu.edu.cn` 的详情路径与对应 DOM；日期不能借页脚或当前时间，跨站原文仍不读取。相同负例与 RED/GREEN。

隔离 Python `/tmp/extrio-health-20261022/backend-venv/bin/python`；后端依赖由 `-c backend/pyproject.toml` 提供。worker 的证据包括实际采样结构覆盖范围（只输出选择器/哈希/计数，无正文）、RED/GREEN、Ruff 与风险，不虚称已做真实网络复验。

集成单元 A004 在第一阶段网络结束后运行：catalog 连接三包提取结果，runner 增加严格显式复核详情采样策略及指纹（保持默认行为）；新增对应离线合同测试，补全新依赖文件指纹。不得更改生产后端、Web、schema 或依赖锁。主执行者负责回执合并、文档、原始证据不变性、完整双库回归、独立 review 与收尾清理。

风险检查已完成：授权范围/深度、费用/写入/终止边界明确；主要风险为误套模板、日期/导航假阳性、review 默认深度改变、依赖变动漏记指纹和跨批清除限制。以上精确 scope、共享质量门槛、显式 opt-in、完整依赖指纹及停止继承分别覆盖；发现未解决 P0/P1 或越界即不执行下一网络批次。
