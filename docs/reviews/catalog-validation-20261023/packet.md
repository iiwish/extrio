# 全清单第一轮核验执行包

任务 `CATALOG-20261023`。用户明确批准：补齐 CSV 驱动批量核验能力，391 个主列表每入口最多一页列表、两条详情；973 个待复核入口只诊断；交付可采/待适配/受限及失败原因矩阵。零付费模型、不访问现有业务库、不启调度、不合并发布部署。分支 `codex/catalog-validation-20261023` 基于本地 `9c6d3113c3e089a2866c45453b4ab3a39a66e942`，本任务不自动获得提交/推送权限。

## 合同、分析与验收

- 以两份实际 CSV 的 391+973=1364 行为分母，逐行保留输入组、行号、原始 URL、sourceId 与历史核验日期。811 个无 entryUrl 官网不在本轮请求范围；旧 1437/1480 统计不作分母。不覆盖原始 CSV 或现有来源数据。
- 沿用 `extrio.source_network.SourceNetwork` 的公开 IP 固定、精确主机集合、证书校验、禁止 HTTPS 降级和 robots；HTTP GET 匿名，无环境代理/Cookie/凭据，无 JS 执行、模型、账号、投递或业务应用导入。
- 按主机共享串行、至少 2 秒间隔、robots 缓存与熔断，最多 4 个不同主机并发；明确拒绝/限流/验证码/robots 禁止后立即停止该主机，后续行标记继承阻断而非再次请求。普通网络失败也不反复重试同站。所有底层请求（robots、重定向、TLS 兼容等）计数。
- 一行最多 12 次实际请求（待复核最多 3 次）、每响应 2MB、每行 60 秒、全批 8000 次实际请求/1GB/90 分钟。达到预算停止并为未执行行给出明确状态，不报完成；可恢复执行只处理未完成行，不重置终态熔断或重跑成功行。每站的请求节奏是全局共享，不因 CSV 多栏目或并发任务重置。
- 主列表只抓一页，不跟随分页。详情最多两个，只接受本页真实发现的、符合列表语义且已通过精确主机检查的 URL；不直接信任 CSV sampleDetailUrl，不采附件、PDF/OCR或未知跨站原文。已有六站确切入口可复用已验证解析；新模板采用保守静态解析与多证据门槛，弱证据标待适配，不推断原生运行或完整历史覆盖已通过。
- 成功字段最低要求：可匹配标题、明确发布日期、非空且非导航/登录/引导文本的公告主体及来源链接。通用启发式只能报告“样本可读/候选解析”，不能冒充已签名规则或完整业务字段验收。结构化字段、PDF、JS 壳、原文跳转和正文不完整分别标记。
- Review 组仅一页匿名可读性/结构诊断，不发送详情请求。历史明确登录/访问限制行允许不请求，标记历史依据及未复测；其他失败保持真实诊断，不从 HTTP 200 宣布可采。
- 输出包含逐行 JSONL、CSV 矩阵、状态/原因聚合、请求 trace/计数/时间/代码与输入指纹、可恢复账本及私人样本文件。每完成一行原子持久化。正文/响应/联系人不进入 Git；输出必须在仓库外 0700 目录且文件 0600。summary 中有输入/完成/未执行计数和限制。
- 本轮不修改生产运行时、网络安全边界、数据库 schema、Web、锁文件、主产品范围或发行状态；测试工具不等同控制台原生全旅程。

Checklist/分析：用户目标、输入、采样深度、费用、写入及终止边界均明确；风险主要为同站请求叠加、越域/私网、假阳性正文、预算重置和敏感输出。上述全局约束和先测后跑逐项覆盖；不存在需要放宽权限的 Critical/High 不确定项。发现不满足安全边界时停止真实执行，不扩大范围。

## 同一任务内的两个并行实现单元

### A001：目录和保守解析

允许 `scripts/tender_sources/catalog.py`、`backend/tests/test_tender_catalog.py` 和本目录 `catalog-evidence.md`。不得编辑 A002 文件，不再委派，不触网、不调用业务库、不回滚他人工作。

固定接口（供 A002 使用，dataclass 均可由 asdict 序列化）：

- `CatalogEntry(entry_id: str, group: str, row_number: int, entry_url: str, name: str, metadata: dict[str, str])`。
- `load_catalog(path: Path, group: str) -> list[CatalogEntry]`：UTF-8 BOM 标准 csv 解析；必需 entryUrl 列，逐行保留重复/无效输入以供报告，不丢分母。entry_id 使用 group、行号和原 URL 摘要；空白行不计数据行。
- `validate_entry(entry: CatalogEntry) -> str | None`：拒绝不安全 scheme、用户信息、非 80/443 端口、localhost/私网字面量、空 URL；DNS 由网络层再次核验。
- `historical_restriction(entry: CatalogEntry) -> str | None`：仅历史明确登录/访问限制，返回可追溯原因，不把一般网络/TLS、200 JS 壳或未核验当作禁止。
- `DetailCandidate(url: str, title: str, published_at: str, basis: str)`；`ListInspection(title: str, status: str, reason: str, candidates: list[DetailCandidate])`。
- `inspect_list(html: str, url: str) -> ListInspection`：保守静态列表诊断，可用强日期+公告链接语义，不把导航、新闻首页、搜索/登录、乱码、HTML 验证码当公告成功。候选只包含本页 href；解析不执行 JS。
- `inspect_detail(html: str, url: str, candidate: DetailCandidate) -> dict`：title/publishedAt/content/contentMode/status/reason；采用现有 BeautifulSoup 和标题一致性 helpers，只在明确公告字段/主体及列表绑定通过时标 `sample_readable`；其余 needs_adapter/body_incomplete/restricted 等，不伪造字段。

先增加应失败的离线测试并确认 RED，再最小实现。覆盖 BOM/引号逗号、缺列、重复/空URL保留、URL边界、历史限制区分、公告与首页/JS/登录/挑战、日期/标题匹配、导航/引导/PDF拒绝、跨站链接仅诊断。运行相关 pytest 和 Ruff；记录实际 RED/GREEN、文件、残余风险。

### A002：安全批量执行器与 CLI

允许 `scripts/tender_sources/catalog_run.py`、`scripts/test-tender-catalog.py`、`backend/tests/test_tender_catalog_network.py` 和本目录 `runner-evidence.md`。导入上述固定接口；可并行写自己的离线网络测试，等待 A001 接口到位再集成。不得编辑 A001 文件，不再委派，不触真实来源、不调用业务库、不回滚他人工作。

实现 packet 的共享限速/robots/熔断/请求预算、两组深度区别、私人外部输出、原子逐行回执、保留全部行的失败分类和 resume（终态安全限制/实际计数不得重置）。默认仅执行显式传入清单；提供 dry-run、limit 或 entry IDs 供无网络计划及先小批验证。复用 SourceNetwork，不从传入 CSV 自动扩大重定向/详情主机范围；同域/已明确内置关系以外只报告待核验。

CLI 预期：`python scripts/test-tender-catalog.py --main-csv ... --review-csv ... --output /private/tmp/... [--dry-run] [--limit N] [--resume]`。输出目录已存在时除 resume 外拒绝覆盖；拒绝仓库内部/符号链接逃逸输出。无后台调度/服务。

TDD：先确认正确测试 RED；用 MockTransport/本地 fixture 验证共享主机并发/节奏、403/429/中文限流/robots HTML 跨行停止，SSRF/越域与降级，预算包括 robots/重定向，review 不发详情，异常和中断回执/恢复不重置、同 ID 不重复执行、目录权限与仓库拒绝、总分母；全离线不访问真实网站。未知错误不可宽泛吞掉伪装成功。

## 主执行者验证与执行

主执行者仅整合接口/文档/范围 review、命令执行和证据，不与 worker 争用实现文件。两个单元返回后检查 diff 和 TDD、离线安全回归、相关既有网络/适配测试、Ruff、全后端及文档检查。邀请独立只读 review，未解决 P0/P1 不进行网络批量。

先 dry-run 核对 391/973 分母、输入指纹、限制；再受控小批，确认实际请求与输出正确后冻结代码。真实完整执行使用隔离 Python 和仓库外目录，不修改现有服务。每组状态与失败原因均真实汇总，未完成不能标完整验收。结束核对无活动进程、工作树范围与业务服务/数据未被接触，交付矩阵及后续适配优先级，状态待用户复核。
