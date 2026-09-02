# Extrio 单一事实来源

## 1. 文档元数据

| 字段 | 内容 |
| --- | --- |
| 文档名称 | Extrio 单一事实来源（SSOT） |
| 文档版本 | `v0.38.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Confirmed` |
| 最后更新 | `2026-09-02` |
| 维护责任 | 产品负责人 |
| 审批责任 | 产品负责人、技术负责人 |
| 文档职责 | 定义 Extrio 的权威事实体系、产品边界、不可违反原则与文档优先级 |

本文件使用以下规范词：

- **必须（MUST）**：实现、测试和运行均不得违反。
- **应当（SHOULD）**：默认遵守；例外必须记录理由、风险和批准人。
- **可以（MAY）**：允许但不强制。

## 2. SSOT 权威体系

单一事实来源是一个具有唯一入口、明确职责和冲突处理规则的文档体系，不要求所有事实写入同一个文件。

| 事实领域 | 权威文档 | 版本 | 状态 | 负责内容 |
| --- | --- | --- | --- | --- |
| 权威入口与产品原则 | [`SSOT.md`](./SSOT.md) | `v0.38.0` | `Confirmed` | 产品定位、范围、不变量、版本与治理 |
| 产品需求 | [`product-contract.md`](./product-contract.md) | `v0.38.0` | `Confirmed` | 用户、旅程、功能需求、非功能需求、成功指标 |
| 领域语义 | [`domain-model.md`](./domain-model.md) | `v0.7.0` | `Confirmed` | 聚合、关系、状态机、唯一约束、CollectionPolicyVersion 与 Checkpoint 语义 |
| RulePlan 语义与语法 | [`contracts/rule-plan.md`](./contracts/rule-plan.md)、[`contracts/rule-plan.schema.json`](./contracts/rule-plan.schema.json) | `v1.0.0` / `extrio.rule-plan.v1` | `Confirmed` | LLM 编译中间表示、字段位置、绑定、分页与支持边界 |
| GatherSpec 语义 | [`contracts/gather-spec.md`](./contracts/gather-spec.md) | `v1.5.0` | `Confirmed` | 规则字段语义、编译边界、完整性、兼容性、安全约束及与运行策略的边界 |
| GatherSpec 语法 | [`contracts/gather-spec.schema.json`](./contracts/gather-spec.schema.json) | `extrio.gather.v1` | `Ready_For_User_Review` | 可执行 JSON Schema |
| 提取与规范化 | [`contracts/extraction-semantics.md`](./contracts/extraction-semantics.md) | `v1.1.1` | `Ready_For_User_Review` | DOM/JSON、Selector、类型与 canonical 输出语义 |
| 规则发布证明语义 | [`contracts/rule-attestation.md`](./contracts/rule-attestation.md) | `v1.1.0` | `Ready_For_User_Review` | 签名、审批绑定、密钥轮换与事故处置 |
| 规则发布证明语法 | [`contracts/rule-attestation.schema.json`](./contracts/rule-attestation.schema.json) | `extrio.rule-attestation.v1` | `Ready_For_User_Review` | RuleAttestation JSON Schema |
| Artifact Manifest 语义 | [`contracts/artifact-manifest.md`](./contracts/artifact-manifest.md) | `v1.1.0` | `Ready_For_User_Review` | 证据等级、分片、digest、安全与保留 |
| Artifact Manifest 语法 | [`contracts/artifact-manifest.schema.json`](./contracts/artifact-manifest.schema.json)、[`contracts/artifact-manifest-chunk.schema.json`](./contracts/artifact-manifest-chunk.schema.json) | `extrio.artifact-manifest.v1` | `Ready_For_User_Review` | Root 与 Chunk JSON Schema |
| 平台消息协议 | [`contracts/platform-protocol.md`](./contracts/platform-protocol.md) | `v1.2.0` | `Ready_For_User_Review` | JobEnvelope、ResultBatch、PlatformError 与 ItemEvent Envelope |
| 平台消息语法 | [`contracts/job-envelope.schema.json`](./contracts/job-envelope.schema.json)、[`contracts/result-batch.schema.json`](./contracts/result-batch.schema.json)、[`contracts/platform-error.schema.json`](./contracts/platform-error.schema.json)、[`contracts/item-event-envelope.schema.json`](./contracts/item-event-envelope.schema.json) | `v1` | `Ready_For_User_Review` | 服务间输入、结果、错误和输出机器合同 |
| 控制面 API 语义 | [`contracts/api-contract.md`](./contracts/api-contract.md) | `v1.12.1` | `Confirmed` | 浏览器 API 边界、管理员认证、异步命令、幂等、多供应商与多模型设置、Collector 需求归属、Collector 定义与两阶段候选规则编辑、Source 传输策略、公告 Item 语义、增量策略与 Checkpoint、规则完整性证据、错误和兼容规则 |
| 控制面 API 语法 | [`contracts/openapi.yaml`](./contracts/openapi.yaml) | `extrio.control-plane.v1` | `Confirmed` | `/api/v1` OpenAPI 3.1 机器合同与生成类型来源 |
| 运行时行为 | [`runtime-contract.md`](./runtime-contract.md) | `v0.6.0` | `Confirmed` | 调度、终结、幂等、重试、时间窗口、Checkpoint、交付、漂移和回放 |
| 安全与合规 | [`security-compliance.md`](./security-compliance.md) | `v0.7.0` | `Ready_For_User_Review` | Alpha 管理员认证、租户演进边界、凭据、网络、内容、隐私和审计 |
| 平台边界 | [`architecture/ADR-001-platform-boundaries.md`](./architecture/ADR-001-platform-boundaries.md) | `v2.0.0` | `Ready_For_User_Review` | Web、FastAPI、编译与执行单元的职责、通信边界和数据所有权 |
| 调度与存储 | [`architecture/ADR-002-orchestration-storage.md`](./architecture/ADR-002-orchestration-storage.md) | `v1.2.0` | `Confirmed` | PostgreSQL、Redis、对象存储、增量 Checkpoint 和 Temporal 阈值 |
| 规则完整性 | [`architecture/ADR-003-rule-integrity.md`](./architecture/ADR-003-rule-integrity.md) | `v1.3.0` | `Ready_For_User_Review` | 不可变规则、摘要、证明和运行时固定 |
| 身份与访问 | [`architecture/ADR-004-identity-access.md`](./architecture/ADR-004-identity-access.md) | `v1.1.0` | `Proposed_Production_Target` | OIDC、会话、服务身份和 Tenant 授权 |
| Alpha 管理员认证 | [`architecture/ADR-005-local-authentication.md`](./architecture/ADR-005-local-authentication.md) | `v1.0.0` | `Accepted` | 首次设置、Argon2、本地可撤销会话与登录限流 |
| 前端原型 | [`frontend-prototype.md`](./frontend-prototype.md) | `v1.32.1` | `Confirmed` | 第一版前端闭环、管理员登录、多供应商与多模型设置、Collector 需求归属与运营列表、Run 与 Item 运营列表、Collector 任务工作区、按需证据、设计合同、技术栈和验收 |
| 真实纵向闭环 | [`backend-vertical-slice.md`](./backend-vertical-slice.md) | `v1.12.1` | `Confirmed` | FastAPI、管理员会话、Crawl4AI、LLM RulePlan 编译、同域嵌入入口解析、确定性运行、本地持久化、可信发布与受控增量运行 |
| 发布验收 | [`releases/v0.2-acceptance.md`](./releases/v0.2-acceptance.md) | `v0.38.0` | `Confirmed` | v0.2 范围、退出标准与验收证据 |

### 2.1 冲突处理

1. 本文件中的产品边界和 `INV-*` 不变量优先于其他文档。
2. 安全与合规要求对所有实现机制构成强制约束。
3. 各 JSON Schema 决定对应机器载荷的语法合法性，对应语义规范决定合法字段的跨对象业务含义。
4. 领域模型决定对象状态与关系，运行时合同决定执行和交付行为。
5. ADR 只能决定实现机制，不得降低产品需求、不变量或安全要求。
6. 发现跨文档冲突时，相关交付必须暂停；不得由代码、迁移或测试静默选择一种解释。

## 3. 产品定义

Extrio 是一个将采集意图转化为可审核、可版本化、可重复执行的数据采集程序的平台。

用户定义“要采什么”以及数据质量要求，平台把意图固化为版本化的数据合同；编译阶段结合 Source、CollectionVersion 与受控的 CollectorOverride 生成不可变 RuleVersion；运行阶段只执行已发布规则，不调用 LLM，也不隐式修改规则。每个结果必须能追溯到确切的规则、数据合同、运行记录和证据。

Extrio 的核心价值是：

1. 缩短合规 Source 从意图到首批有效数据的时间。
2. 将站点采集知识从一次性代码转化为可治理规则。
3. 让运行、数据质量、异常和回放具备统一证据链。
4. 在 Source 变化时快速发现漂移，并通过新规则版本恢复。

Extrio 是面向授权 Source 的通用结构化采集平台。通用性来自 LLM 在接入期理解网页并编译受约束规则，而不是运行期自由生成代码。平台不提供验证码破解、访问控制绕过、代理售卖或任意代码执行能力。对外唯一产品名为 `Extrio`；`RulePlan`、`GatherSpec`、`Collector` 与 `RuleVersion` 是内部领域术语。

## 4. 核心不变量

| ID | 不变量 |
| --- | --- |
| `INV-001` | 运行期不得调用 LLM、生成代码或修改已发布规则。 |
| `INV-002` | 已发布 RuleVersion 必须不可变并由有效 RuleAttestation 证明；行为变化必须发布新版本，密钥轮换只能追加证明。 |
| `INV-003` | Run 创建时必须固定 RuleVersion、RuleAttestation、CollectionVersion、SourceRevision、AccessProfileVersion 和完整运行时语义版本。 |
| `INV-004` | 所有领域对象、队列任务、Artifact 和交付记录必须带有不可伪造的租户边界。 |
| `INV-005` | 凭据明文不得出现在 GatherSpec、队列、日志、Artifact 或标准化输出中。 |
| `INV-006` | ItemEvent 必须表示有序状态转换并形成 previousEventId 链；每个转换和 Delivery 具有稳定幂等键，平台承诺 at-least-once，不宣称端到端 exactly-once。 |
| `INV-007` | 发布、回滚、凭据访问、生产回放和数据删除必须产生不可变审计事件。 |
| `INV-008` | Source 访问必须获得合法授权，并受域名、网络、速率和资源预算约束。 |
| `INV-009` | Run 必须先冻结 staging、质量决定和 accepted set 再提升并释放 Delivery；失败和部分成功不得被记录为完整成功，不得静默丢弃必填字段错误或交付失败。 |
| `INV-010` | RuleVersion 回滚只改变 Collector 的活动版本指针，不改变历史 RuleVersion 或运行中的 Run。 |
| `INV-011` | 控制面请求必须经过认证；公开 Alpha 使用单实例管理员权限，后续多租户形态再按 Tenant、资源与动作授权。客户端提交的 tenantId、对象 ID 或 trace context 不构成权限依据。 |
| `INV-012` | 只有 `evidenceMode=replayable` 且响应字节、URL 上下文、连续 chunk 和运行时语义均完整可验证时，执行才可称为历史证据回放。 |

## 5. v0.2 产品范围

### 5.1 当前范围

1. CollectionTemplate、TemplateVersion、Collection 与 CollectionVersion 管理。
2. Source 创建、批量导入、复用已有 Collection 需求身份与采集意图、合规边界和 AccessProfileVersion 引用；允许 TenantAdmin 策略显式接受匿名公共 HTTP 传输风险，任何 AccessProfileVersion 或凭据访问必须使用 HTTPS。
3. Source 与 CollectionVersion 绑定为 Collector，支持受控 CollectorOverride。
4. Collector 定义与候选规则工作区：名称可以独立编辑；意图或 Source 入口变化使当前候选失效并阻断新 Run，直到重新探索、审核和发布。探索阶段由默认模型根据受控 DOM/JSON 样本编译 `RulePlan`，平台将其校验并转换为 GatherSpec；规则编辑表单只呈现可修改的列表 Item selector、网页业务字段 selector 与分页参数，并以简洁阶段标题和 `detailUrl` 交接标识保持执行顺序；`source`、`crawlTime`、`observedAt` 等系统字段不进入编辑表单；请求配置、字段类型、错误策略、转换、安全边界和输出合同统一在只读 JSON 中查阅，不在表单重复展示。selector 与分页参数可以作为受控 CollectorOverride 直接编辑，经最近探索样本验证后形成新候选；字段语义服从 CollectionVersion，任何已发布 RuleVersion 均不可原地修改。
5. 编译、Schema/语义校验、样本测试、人工审核、RuleAttestation、发布和回滚 RuleVersion。
6. `single` 单阶段直接采集与 `list_detail` 两阶段采集；HTML 使用 CSS Selector，JSON 使用 JSONPath，列表阶段支持 `none`、query `page` 与 `next_link` 分页。Source 入口是同域 iframe 外壳且外壳本身不产生记录时，探索解析同域嵌入入口并把有效入口冻结进 GatherSpec。Item 边界、身份字段、指纹字段和业务输出字段由 RulePlan 明确表达，Run 只执行规则并写入采集时间。
7. HTTP 采集和受限浏览器采集；浏览器规则固定导航完成条件与异步内容沉降时长，运行时按规则生成可重放 DOM snapshot，不允许任意脚本或代码插件。
8. Cron Schedule、Run、RunAttempt、取消、暂停、失败重试和运行历史。
9. HarvestItem、Revision 与 Observation、稳定事件键、Webhook/Kafka 交付和受控 redelivery。
10. ArtifactManifest、原始响应采样、失败证据、证据等价回放和受控重新处理。
11. Tenant RBAC、不可变审计、基础 SLO、告警和 Source 漂移检测。
12. 面向 `1280px` 及以上视口的桌面端 Web 控制台，以任务优先的运营工作台作为 `/` 主页。概览以实际运行成功率、已发布规则覆盖和最新实体质量通过率建立聚合视角，并用最近运行数据量与终态趋势说明变化；只保留最多三项异常入口，不重复展示 Run 或 Item 列表、技术 ID、推断式质量分或继续工作入口。待处理判断基于 Collector 生命周期与最近 Run 的真实异常终态，健康且成功运行的已发布 Collector 不进入队列。控制台以固定列运营列表呈现 Collector、Run 与 Item，并以详情证据卡组承载对象深度信息。顶部栏只显示当前一级页面标题，不重复工作区名称或层级分隔。侧栏只保留品牌、一级导航和底部设置入口，不常驻显示 API 或 Mock 环境提示。Collector 使用稳定 `collectionId` 与 `collectionName` 归属一个业务采集需求，列表首行集中放置状态筛选、可按需求名称或合同版本输入搜索的需求筛选器和新建操作，不显示需求标签、布局切换、页面标题或概览指标卡，不使用任意文件夹作为领域归属。Collector 列表固定对齐 Source 身份、所属需求、状态、活动规则、最近运行与下一动作；需求筛选写入 URL，完整采集说明和策略进入详情。从全部需求上下文新建 Collector 时默认定义新需求，从具体需求筛选上下文新建时默认选中并复用该需求。Run 列表首行集中状态筛选、按 Collector 名称或 Run ID 搜索、开始时间排序提示和刷新操作，不重复展示页面标题或概览指标卡；列表固定对齐 Run 身份、终态、接收与拒绝数量、执行范围与停止原因、开始时间与耗时。Item 列表首行把 Source、Collector、质量决定筛选置于左侧，把标题、正文、Collector 或 entity key 搜索置于右侧，不重复展示页面标题或概览指标卡；列表固定对齐实体身份、质量决定、变化与 Revision、发布时间、最近采集和 entity key，Collector 展示名与 Source host 相同时只显示一次。Run 与 Item 的搜索和筛选写入 URL。Collector 详情首屏明确区分只读需求归属、可编辑来源定义和规则工作区，区分重新生成候选规则、两阶段候选规则工作台与不可变活动规则。规则工作台以可视流程明确 Stage 01、`detailUrl` 交接、Stage 02 和公告级输出合同，并按需提供完整 GatherSpec 只读视图；内部版本 ID 与 digest 不作为产品主信息展示。控制台通过符合 `/api/v1` OpenAPI 的 FastAPI 控制面跑通一个需求批量导入多个采集入口、逐项创建 Collector、`single` 或 `list_detail` 探索、审核、规则发布、Collector 级 Cron 定时计划、版本化采集范围、异步增量运行、Checkpoint、最新 Item 实体与谱系查看的真实纵向闭环；MSW 只承担前端隔离测试与合同模拟，移动端和窄屏适配不在当前产品范围。
13. Collector 详情的返回操作进入顶部栏当前页面标题区域，使用可访问的箭头图标按钮，正文不重复返回文字链接。批量导入顺序不是 Collector 业务身份，不进入名称或详情主标题；同域 Source 由网址路径区分。详情页收敛为“概览、规则、采集配置”三个一级视图：概览承载当前状态、活动规则、运行范围、最近运行和最多五条最近结果；存在候选或活动规则时才显示规则视图，`ready_review` 默认进入规则审核，其余状态默认进入概览；采集配置承载 Source 定义、规则编辑、定时运行和增量策略；定时运行优先提供常用频率，按需接受五段 Cron，固定中国标准时间与禁止重叠运行。字段审核和样本数据在规则审核内协作；已发布规则的状态、采集流程、输出字段、验证结果和审核结论直接显示在规则页，不通过额外 Dialog。完整 GatherSpec 只在采集配置的“编辑规则”Dialog 内以“JSON”Tab 按需只读查阅；规则页不重复展示，内部版本 ID 与 digest 不作为独立信息项展示。原始 JSON 不允许直接编辑，规则修改通过结构化表单形成受控 Override、新候选与完整验证链。字段和 Item 证据默认不占据页面宽度，只在用户选择对应对象后以可关闭的右侧 Sheet 显示。
14. 运行终态必须同时反映数据质量与抓取完整性。`list_detail` Run 发现的详情 URL 未全部取得响应时使用 `detail_fetch_incomplete`，终态为部分成功（存在 accepted Item）或失败（没有 accepted Item），不得推进 Checkpoint；Run 列表与详情同时展示已抓取数和发现数。
14. 一级“设置”页面按供应商分组同屏管理模型，不把存在归属关系的两个对象拆成平级 Tab。顶部左侧只提供唯一默认模型选择，右侧提供添加供应商，不展示缺少决策价值的供应商或可用模型计数；每个供应商组展示连接、密钥与启停状态，并在组内添加、启停、编辑或删除模型。用户在供应商对话框中直接录入 API Key；浏览器只在保存请求中短暂提交，不写入本地存储，控制面使用独立主密钥加密落库，所有读取响应只返回 `credentialConfigured`。供应商可拥有零到多个模型；模型能力只属于探索与候选规则编译边界，不改变运行期禁用 LLM 的不变量。
15. Source 首次抓取失败必须归一为稳定的 `SOURCE_UNREACHABLE`，向用户说明域名、连接失败类别和检查动作；第三方抓取库的堆栈、源码行号和内部路径只允许进入受控日志，不进入操作错误正文。
16. Run 详情的返回操作位于顶部栏，不在正文重复展示。首屏以 Source 根 URL 作为主标题，以完整入口的路径、终态、开始时间、耗时和执行模式作为次级上下文；同域名下的不同入口仍可通过路径区分。页面不显示“运行记录”等无信息眉题，也不把 Run ID 作为主信息；结果、执行过程、范围与增量、质量与证据使用与 Collector 详情一致的全宽等分线型任务导航。结果摘要以单行结论和指标带呈现接收、拒绝、变化与耗时，不重复堆叠统计卡。执行证据先表达规则证明、固定范围、结果集冻结和 Artifact 保留方式等人可理解的结论，对象 ID、版本 ID、digest、attestation 与 SigningKey 收纳在默认折叠的技术信息中，页面不常驻右侧 evidence rail。
17. Item 详情的返回操作位于顶部栏，首屏以公告标题、质量终态、Source 身份、发布时间与 Revision 建立对象上下文。“数据内容、版本与观察、质量决定、来源与谱系”使用与 Collector、Run 详情一致的全宽等分线型任务导航。数据内容先展示规范化字段与正文；版本变化与观察历史合并为同一任务视图；质量决定呈现可读结论和拒绝原因；来源与谱系先提供 Collector、详情来源和最近 Run 的可操作入口，Entity key 与完整 lineage ID 收纳在默认折叠的技术信息中。页面不常驻右侧 evidence rail，也不在主标题下展示 Entity key。

### 5.2 不在当前范围

- 验证码破解、登录绕过、付费墙绕过或违反 Source 条款的采集能力。
- 用户提交并在 Worker 中执行 Python、JavaScript 或其他任意代码。
- 多区域主动主动部署、复杂财务计费、代理交易市场。
- 端到端 exactly-once 承诺。
- 自动删除 Source 中已经消失的实体；v0.2 只输出显式识别的删除或撤销事件。
- 无人审核的生产规则发布；自动发布只能在后续版本通过独立风险决策引入。
- 通用 cursor、无限滚动、任意增量表达式和双向回填；v0.2 增量只覆盖具有列表发布时间、时间降序和 `next_link` 的 Source。

## 6. 技术基线

- Python FastAPI 控制面是租户、领域对象、权限、发布、调度、审计和交付状态的唯一写入入口；生产长任务不在 API 请求进程内执行。
- Python 编译服务使用 Crawl4AI 获取完成导航并经过固定沉降时长的渲染 Source 样本；当前默认模型先编译列表发现计划，再结合详情样本编译受约束 `extrio.rule-plan.v1`。服务端对 selector、分页、字段类型、身份、指纹、样本命中与安全边界进行确定性验证，将合法 RulePlan 转换为 GatherSpec，并固定 provider、model、promptVersion 与浏览器 snapshot 时点。Python 执行 Worker 只解释已发布 GatherSpec，不读取模型配置或调用模型。两者采用独立工作负载身份和权限边界。
- 本地开发纵向闭环使用 SQLite WAL 持久化领域对象、不可变 RuleVersion/RuleAttestation/AuditEvent、幂等记录、Operation 与 leased job，使用文件型开发 Ed25519 key 完成 RFC 8785 签名验证，并把 sampled HTML 写入本地 Artifact 目录；该配置只用于开发验收，生产系统记录仍为 PostgreSQL，签名仍由 KMS/HSM 承担，工作分发仍为 Redis Streams，raw 与 Artifact 仍进入对象存储。
- Web 控制台采用 pnpm、Vite、React、TypeScript、Tailwind CSS 与 shadcn/ui；浏览器只通过 `/api/v1` 访问控制面，类型生成自 [`contracts/openapi.yaml`](./contracts/openapi.yaml)，不读取数据库、对象存储凭据或 Worker 内部状态。
- PostgreSQL 是领域状态的系统记录；Redis 只承担可恢复的工作分发与短期协调；S3 兼容对象存储保存 raw 和 Artifact。
- GatherSpec 统一使用 JSON，并通过 `extrio.gather.v1` Schema、固定提取语义、ruleDigest 和独立 RuleAttestation 校验。
- v0.2 使用 Cron、PostgreSQL transactional outbox 和 Redis Streams，不引入 Temporal。
- 公开 Alpha 使用首个本地管理员、Argon2 密码哈希和服务端可撤销会话；外部 OIDC、多用户角色、Tenant 授权和独立工作负载身份属于生产演进边界。
- 同一 Python 代码库可以承载控制面、编译与执行模块，但部署、数据写入、网络权限和运行生命周期必须保持逻辑隔离。
- 探索和 Run 通过持久化 Operation 以 `202 Accepted` 启动；阶段、指标和终态由服务端事实驱动，页面刷新通过 `activeOperationId` 或 `operationId` 恢复，不得由客户端定时器伪造。
- Source 入口只允许 HTTP(S)。公共 HTTP 默认关闭，只能由 TenantAdmin 策略显式开启并在界面标记风险；该策略不放宽 exact allowedHosts、私网/metadata 阻断、DNS 复检、重定向复检、速率或资源预算。
- 所有服务边界、消息 envelope、失败语义与演进阈值由权威合同、OpenAPI 和版本化 JSON Schema 定义；实现不得以框架或采集库默认行为替代合同。

## 7. 版本与变更治理

### 7.1 独立版本

- 文档体系版本使用 `vMAJOR.MINOR.PATCH`。
- 产品发布版本独立编号，例如 `v0.2`。
- GatherSpec 兼容版本使用稳定标识，例如 `extrio.gather.v1`。
- RuleVersion 是业务实体版本，不与文档或产品版本复用。

### 7.2 版本变化规则

- `MAJOR`：产品边界、核心不变量或已发布合同发生不兼容变化。
- `MINOR`：新增向后兼容能力、对象或约束。
- `PATCH`：不改变行为的澄清、链接或文字修正。

### 7.3 审批与落地

1. 产品合同、领域模型、运行时合同、安全合同或 ADR 发生行为变化时，必须先更新相应文档及版本矩阵。
2. 产品负责人审批产品范围和验收合同；技术负责人审批领域、运行时、安全和 ADR。
3. 代码、数据库迁移、API、Schema 和测试必须引用对应的 `FR-*`、`NFR-*`、`INV-*` 或 `AC-*`。
4. 破坏性变更必须包含迁移、兼容窗口、回滚路径和受影响对象清单。
5. 文档进入 `Confirmed` 后才能作为发布阻断合同；该文档体系经责任人明确批准后统一进入 `Confirmed`。
6. 每个产品版本至少复审一次权威矩阵、外部依赖、容量基线和安全边界。
7. 每次待审批文档集必须生成 [`releases/v0.2-docset-manifest.json`](./releases/v0.2-docset-manifest.json)，记录每个权威文件的 path、version、SHA-256、生成时间和文档集状态；批准后追加 `approvedBy`、`approvedAt`、产品版本和 repository revision（存在 Git 时），不得重写已批准快照。

## 8. 权威术语

- **CollectionTemplate**：可复用的数据合同模板。
- **TemplateVersion**：已发布且不可变的模板版本。
- **Collection**：一个业务采集目标的稳定身份。
- **CollectionVersion**：Collection 在特定时点冻结的数据合同版本。
- **Source**：经授权访问的站点或数据来源身份及安全边界。
- **AccessProfileVersion**：认证类型、精确注入作用域和 Secret 引用的不可变访问配置版本。
- **Collector**：Source 与 CollectionVersion 的执行绑定。
- **CollectorOverride**：作者态的、类型受控的 Source 例外配置。
- **RuleVersion**：Collector 的已编译不可变执行规则。
- **RuleAttestation**：对 RuleVersion digest、批准决定、评审策略、发布目的和 SigningKey 的追加式证明。
- **Schedule**：触发 Collector 运行的版本化 Cron 配置。
- **Run**：固定规则和输入上下文的一次执行。
- **RunAttempt**：Run 的一次可恢复执行尝试。
- **RunFinalization**：冻结 winning Attempt、质量决定及 accepted/rejected set 的不可变终结记录。
- **HarvestItem**：租户、Collection 与 Source 范围内的逻辑实体。
- **HarvestItemRevision**：HarvestItem 内容变化形成的不可变版本。
- **HarvestObservation**：一次 Run 对某个 HarvestItemRevision 的有效观察记录。
- **ItemEvent**：HarvestItem 的有序 upsert/tombstone 状态转换，previousEventId 形成不可变事件链。
- **Delivery**：一个 Item 事件向一个 Sink 的逻辑交付。
- **RedeliveryRequest**：对既有 Delivery 追加发送尝试的受控人工命令。
- **Artifact**：原始响应、样本、日志或验证报告等不可变证据对象。
- **ArtifactManifest**：按 metadata_only、sampled 或 replayable 等级记录响应、URL、runtime 与 Artifact digest 的证据索引。
- **ArtifactManifestChunk**：replayable Manifest 引用的有序响应证据分片。

### 概览看板时间范围

概览看板同时呈现今日采集、本周运行成功率、本月有效数据和当前规则覆盖，使日、周、月经营口径可以并列比较。日、周、月只作为“采集产出趋势”的聚合粒度，分别覆盖最近 14 天、12 周和 12 个月；柱形按接收与拒绝数据堆叠，运行质量面板同步说明该趋势范围内的成功、部分成功、失败和数据通过率。看板最多读取 200 条 Run 与 Item 观测，并保留最多三项需要人工推进的异常。

## 9. 审核结论

该文档体系不包含高影响未决问题。当前状态等待产品负责人和技术负责人对完整合同进行明确审批；在审批前可以用于设计和评审，不应被标记为生产发布基线。
