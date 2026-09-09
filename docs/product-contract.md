# Extrio 产品合同

## 1.0 交付范围

1.0 的交付范围为单组织自托管稳定版，面向一个组织内的数据运营团队，保留本地账号角色、SQLite 评估和 PostgreSQL 部署路径。多租户、SSO/MFA、分布式高可用和移动端不属于本次交付范围。全站页面的内容组织、桌面布局、操作流程和状态反馈属于 1.0 的体验验收范围，不以功能测试通过或单纯调整样式代替。具体页面方案需以真实界面走查和用户复核为依据，沿用唯一正式前端。

1.0 的功能、AC/NFR、部署依赖和退出条件以[单组织自托管验收范围](planning/v1.0-scope-matrix.md)为版本适用合同。功能实现、工程验证、页面设计签收和生产目标达成分别记录，不将范围确认视为已实现或已验收。

## 核心操作上下文

来源、运行、AI 任务和数据详情通过安全的站内 returnTo 保留入口筛选及 section 分区，返回不丢失来源页面的上下文。搜索可独立清除，刷新保留筛选；首次读取失败提供重试，不显示伪空列表，后台错误保留已读取数据。运行时间使用持久化 ISO 时间，不把历史运行显示为“刚刚”。正文中的 HTML 仅以惰性解析后的纯文本阅读或转义源码显示，不挂载源站脚本、图片和 iframe。来源概览区分已发布规则与最近异常运行；只读角色不能触发来源执行、定义/规则/策略修改或 Webhook 发送。接入表单的录入和导入预览具有离开确认，刷新/关闭使用原生未保存提醒；提交失败保留输入，成功创建可进入详情。设置弹层关闭后恢复原操作按钮焦点，退出失败保留会话并可重试。

## 数据查询与导出

数据页使用 `GET /items?view=entities`，服务端按 `collectorId + entityKey` 选择最新观测后应用筛选，返回匹配实体总数、全局筛选选项和游标。页面每次加载 50 个实体，支持继续加载至游标结束；筛选变化重新开始分页，读取失败显示错误与重试。`q` 对标题、正文、来源名称和 entity key 做字面子串搜索，`sourceHost`、`collectorId`、`decision` 为精确筛选。CSV/JSONL 导出复用相同的实体视图和全部筛选，覆盖全部匹配数据而非仅已显示页；超出已有导出上限明确拒绝，不静默截断。默认 API 仍提供观测视图，`entityKey` 仍表示精确匹配。桌面工具栏的搜索区可收缩，导出操作在最小支持视口中可达；宽表格在自身区域滚动。

字段变更比较保留 JSON 类型，`null`、`0`、`false`、空字符串、空数组和空对象不合并为同一值；对象键顺序和数值等价表示不制造 Revision。有效变化追加 Revision 并进入已配置 Sink 的交付队列，不重写历史结果。

## 单前端实现边界

Extrio 只有一套正式前端：`web/index.html` → `src/main.tsx` → `app/router.tsx`，共享 AppShell、AuthGate、QueryClient 与 API 客户端。一级导航为概览、采集需求、采集来源、运行、数据、设置。需求列表读取独立持久化的 Collection，点击进入 `/collections/:collectionId` 明细，展示完整目标、字段要求、来源执行合同与关联来源；明细支持添加来源，来源归属链接返回需求明细，需求列表的搜索、状态筛选和更新时间排序通过 URL 保留，详情返回不丢失列表上下文。需求列表把名称与两行目标摘要放在同一业务单元，按来源发布覆盖、最近更新时间和合同引用进行比较；使用中、已归档和全部筛选显示各自数量，清除搜索只清除关键词，刷新保留当前条件。初始加载与失败不显示零需求，空列表、当前状态为空和搜索无匹配分别提供反馈。合同引用与来源发布覆盖不代表统一字段版本已冻结、调度开启或运行健康。需求支持独立新建、名称与业务目标编辑、空需求删除、归档和恢复；工程师与管理员可操作，其他角色只读。有关联来源的需求禁止删除；归档禁止编辑需求与添加来源，不停止已有来源、定时采集或运行，不删除历史数据。编辑使用 revision 冲突校验，不覆盖已有来源采集说明及不可变规则；新来源使用当前业务目标。模型、凭据、审核、运行与数据保留现有后端能力。旧 `experience.html` 地址仅用于兼容跳转，不提供独立应用或模拟业务数据。

需求详情以“采集字段 / 关联来源”组织工作面，字段仅展示一次。头部集中需求身份、使用/归档状态、来源发布覆盖与更新时间，长目标或多段目标支持摘要与全文展开。当前分区通过 section=sources 写入 URL，采集字段为默认分区；刷新恢复分区，返回列表保留 q/status/sort 且不携带详情 section。字段名称、技术标识和业务说明归入同一列，编辑操作列固定宽度；来源覆盖和约束差异在同行表达，按需打开该字段的来源详情与完整合同。字段草稿支持手动增改删、名称、标识、类型、必填、去重标识、变更检测与说明，真实保存到 Collection，使用 revision、权限、幂等和审计保护。没有草稿时按 key 合并来源输出，每个字段一行，差异保留而非视为统一已发布合同；有草稿时以草稿为主，来源额外字段可按需展开且不自动写入草稿。已发布字段只读取不可变活动 RuleVersion，候选规则另行标注。来源合同差异和草稿缺失字段可见，完整输出 Schema 与质量规则可查。字段编辑采用顶部保存操作条，长表编辑时持续可达。未保存标记在分区标签中可见，分区切换保留本地字段草稿；应用内跨页面离开需确认，浏览器刷新/关闭保留原生提醒，保存期间不允许通过离开确认放弃正在提交的内容。后台详情读取失败保留已有数据和本地字段编辑，失败与 revision 冲突不自动覆盖输入，放弃重载使用明确动作。字段编辑和来源证据弹层关闭后恢复触发位置。关联来源把名称和入口网址归组，状态与真实输出字段数并列；合同未知或不可用显示无法确认，不解释为零。草稿不自动应用于新旧来源或运行，不等于字段版本发布；模板入口、真实 AI 字段建议、版本发布和来源迁移属于后续实现。设置分为系统设置和模型设置两个 URL 同步页签（`?tab=system|models`）。系统设置包含语言、账号、环境及管理员专属的采集策略与用户管理；模型设置保留供应商、模型、默认模型及凭据管理，非管理员只读，读取失败提供重试且不得显示为空配置。桌面下限为 `1024px`，主验收 `1440x900`，补充 `1280x800`、`1132x1028`、`1024x800`；宽表格在自身区域滚动，移动端不在范围内。

设计见 [核心体验重构方案](core-experience-redesign.md)，实现与验收见 [前端说明](experience-prototype.md)。

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v0.44.0` |
| 对应产品版本 | `v0.6` |
| 状态 | `Confirmed` |
| 权威来源 | [`SSOT.md`](./SSOT.md) |
| 最后更新 | `2026-09-06` |
| 审批责任 | 产品负责人 |

## 2. 产品定位

Extrio 面向需要持续采集公开或已授权网页、并要求每条数据可验证的数据运营团队。首要场景是招投标、监管公告和公共通知等列表/详情型来源。平台把采集意图转化为数据合同和不可变规则，使 Source 上线、审核、运行、漂移恢复和数据交付能够被非爬虫专家治理。

核心差异不是“AI 会写采集代码”，而是“AI 参与规则编译，运行期只执行可审核合同，并让每条数据具有完整谱系”。

产品采用“AI 辅助接入、人工审核发布、确定性持续运行”的边界，不定位为通用爬虫工具箱、网页聊天机器人或自主 Agent 平台。

### 2.1 产品成熟度

- **当前可用**：本地自托管纵向闭环、受约束 AI 规则生成与修复、人工审核发布、确定性运行、规则签名、Item 谱系、Webhook 与 MCP。
- **实验性**：跨真实站点的规则生成泛化能力、浏览器采集稳定性、较大来源下的性能和恢复体验；结论只来自仓库内 fixture 与显式 benchmark，不作为外部生产证明。
- **规划中**：可公开访问的体验环境、外部设计伙伴验证、公开来源回归语料、模板与 SDK 生态、生产级多租户和高可用部署。

## 3. 目标用户与职责

| ID | 角色 | 核心目标 | 主要权限 |
| --- | --- | --- | --- |
| `ACT-001` | TenantAdmin | 管理租户、成员、安全策略和连接 | 成员、角色、AccessProfile、Sink、保留策略 |
| `ACT-002` | CollectionEditor | 定义数据需求并接入 Source | Template、Collection、Source、Collector 草稿和样本测试 |
| `ACT-003` | RuleReviewer | 对数据合同、样本和风险负责 | 批准、发布、拒绝和回滚 RuleVersion |
| `ACT-004` | Operator | 保持采集稳定并处理异常 | Schedule、Run、暂停、恢复、验证回放和告警处置 |
| `ACT-005` | DataConsumer | 使用规范化数据 | 查看数据合同、Delivery 状态和允许访问的输出 |
| `ACT-006` | Auditor | 核验规则、数据和操作历史 | 只读访问版本、Artifact 和 AuditEvent |

同一用户可以拥有多个角色。受保护 Collection 可以启用四眼审批，要求 RuleReviewer 与规则提交者不是同一用户。

## 4. 核心用户场景

### `US-001` 从意图创建数据合同

CollectionEditor 用自然语言或模板描述需要的实体、字段、身份、质量和输出。平台生成 CollectionVersion 草稿；用户可编辑和校验，在冻结后获得不可变数据合同。

### `US-002` 批量接入 Source

CollectionEditor 创建或导入 Source，声明入口、允许访问域名、访问方式和 AccessProfileVersion，然后将 Source 绑定到冻结的 CollectionVersion 形成 Collector。

### `US-003` 编译并发布规则

平台结合 Source、CollectionVersion 和 CollectorOverride 生成 RuleVersionDraft。每个 Collector 通过稳定 `collectionId` 与 `collectionName` 归属一个业务采集需求；工作区同时显示只读需求归属、可编辑来源采集说明、Source 入口、活动 RuleVersion 与候选规则摘要。CollectionEditor 可以修改 Collector 名称；修改来源采集说明或 Source 入口会使候选失效并暂停新 Run，随后重新探索。探索通过 Crawl4AI 固定网页证据，当前默认模型先理解入口拓扑并编译列表发现计划，再结合详情样本编译 `RulePlan`；平台只接受受约束的 CSS/JSONPath、字段、分页、身份和指纹声明，并把通过 Schema、安全与样本验证的结果转换为 GatherSpec。规则编辑表单按执行顺序呈现列表 Item selector、网页业务字段 selector、分页、`detailUrl` 交接和详情字段 selector，不展示系统管理字段，也不重复展示不可编辑的请求配置、字段语义与输出合同；CollectionEditor 可以直接编辑两个阶段的 selector 与分页参数；系统把编辑记录为受控 Override，使用最近探索样本重新验证并生成新的候选 digest。字段语义服从 CollectionVersion。RuleReviewer 查看字段预览、失败样本、网络边界和编译谱系后发布规则；任何编辑都不能改写已发布 RuleVersion。

### `US-004` 持续运行和交付

Operator 为 Collector 配置 Schedule。每次 Run 固定 RuleVersion 与输入版本，记录 HarvestObservation，在输出合同或内容变化时产生 HarvestItemRevision，并通过配置的 Kafka 或 Webhook Sink 进行幂等交付。

### `US-005` 发现并修复 Source 漂移

平台从空结果、结构提取失败、必填字段完整度和响应状态识别漂移。Operator 暂停受影响 Collector，基于新样本重新编译并经审核发布新 RuleVersion。

### `US-006` 回放与审计

Operator 使用历史 Artifact 进行无副作用验证回放；具有额外权限时可以重新处理或重新交付。Auditor 能从 Delivery 追溯至 Item、Run、RuleVersion、CollectionVersion、Source 和操作人。

## 5. 核心用户旅程

1. TenantAdmin 建立成员、角色、AccessProfile 和 Sink。
2. CollectionEditor 选择 TemplateVersion 或创建 Custom CollectionVersion。
3. CollectionEditor 定义字段、身份、质量规则和输出，校验后冻结版本。
4. CollectionEditor 创建或导入 Source，并建立 Collector。
5. 编译服务生成规则草稿和样本证据；CollectionEditor 可以重新生成候选，或在样本验证约束下直接编辑候选规则。
6. RuleReviewer 批准并发布 RuleVersion；Collector 活动版本指针原子切换。
7. Operator 启用 Schedule；平台执行、规范化、持久化和交付。
8. 平台监控运行与数据质量，异常时告警并保存证据。
9. Operator 通过验证回放定位问题，发布新版本或回滚到历史版本。

任何步骤失败时，用户必须看到失败对象、原因分类、可操作的下一步和对应证据；系统不得用成功状态掩盖部分失败。

### 5.1 第一版前端闭环

第一版 Web 原型以单 Tenant、标讯 Collection 与多个 Source 的演示数据跑通：`选择已有需求或定义新需求 -> 批量添加精确列表入口 -> 每个入口建立 Collector -> 按需求查看或跨需求运营 -> 识别 single 或 list_detail 模式 -> 生成候选 GatherSpec -> 审核 -> RuleVersion 与 RuleAttestation 发布 -> 立即运行 -> Item 与谱系查看`。Collector 的运行入口是一个具体列表页或单页，不是站点根目录；同域名下业务范围不同的列表分别建立 Collector，分页由 GatherSpec 的 list stage 处理。复用已有需求时使用其稳定 Collection 身份、采集意图和数据合同；同批 Collector 独立拥有规则、状态、Run、Checkpoint 与证据。`single` 直接从入口提取字段；`list_detail` 在同一 Collector、RuleVersion 和 Run 内先遍历分页，从每个列表项提取列表标题与 detail URL，再抓取详情并提取详情标题、发布时间和正文，Run 记录采集时间。公告类 Source 的一个 Item 对应列表中的一条公告，不对应详情正文里的内部表格行。批量导入必须提供逐项结果和部分失败；发布必须持久化不可变规则、签名证明和 AuditEvent，Run 必须展示固定证明；原型必须具有可操作的状态转换、服务端 Operation 进度、质量门、稳定错误和证据，不得以互不相连的静态页面或客户端伪造阶段替代闭环。

原型是面向 `1024px` 及以上视口的桌面端控制台，使用 `1440x900` 作为主要设计与视觉验收视口、`1024x800` 作为最小支持验收视口；移动端和低于 1024px 的窄屏适配不在当前范围。一级导航包含概览、采集需求、采集来源、运行、数据和设置；设置固定在侧栏底部并与核心业务导航分区。`/` 是任务优先的运营工作台：页面聚合实际运行成功率、已发布规则覆盖、最新实体质量通过率和最近运行趋势，只保留最多三项异常入口；不重复 Run 或 Item 列表，不展示技术 ID、推断式质量分或继续工作入口。待处理由 Collector 生命周期和最近 Run 的真实异常终态共同决定。Collector、Run 与 Item 使用固定列运营列表。Collector 列表以可换行顶部工具栏作为第一操作面，集中提供状态筛选、支持输入搜索需求名称或合同版本的需求筛选器和右侧新建操作，不显示需求标签、布局切换、页面标题或概览指标卡，也不引入文件夹树。列表逐行固定展示 Source 身份、所属需求、状态、活动规则、最近运行和下一动作；状态和需求筛选写入 URL，需求说明和采集策略进入详情。Run 列表以顶部工具栏作为第一操作面，集中提供状态筛选、按 Collector 名称或 Run ID 搜索、开始时间排序提示和刷新操作，不重复显示页面标题或概览指标卡；每行固定展示 Run 身份、终态、接收与拒绝数量、执行范围与停止原因、开始时间与耗时，状态和搜索条件写入 URL。Item 列表同样以顶部工具栏作为第一操作面，左侧提供 Source、Collector 与质量决定筛选，右侧提供标题、正文、Collector 或 entity key 搜索，不重复显示页面标题或概览指标卡；每行固定展示实体身份、质量决定、变化与 Revision、发布时间、最近采集和 entity key，Collector 展示名与 Source host 相同时只显示一次，筛选与搜索写入 URL。Collector 详情按“概览、规则、采集配置”三个任务视图组织；概览集中展示当前状态、Source、活动规则、运行范围、最近运行和有限的最近结果，规则视图只在候选或活动规则存在时显示，采集配置承载 Source 定义、规则编辑、定时运行与增量策略。`ready_review` 默认进入规则审核，其余状态默认进入概览；字段审核与样本数据归入同一审核工作区，已发布规则的业务可读发布信息直接显示在规则页，完整 GatherSpec 只在采集配置的规则编辑场景按需查阅。批量导入顺序只用于导入结果定位，不进入 Collector 名称或主标题；同域 Source 通过路径摘要区分。Item 列表以稳定实体而非重复 Run observation 为扫描单位。品牌标识从任意页面返回主页，侧栏只保留品牌、一级导航和底部设置入口，不常驻显示 API 或 Mock 环境提示；顶部栏在一级列表和首页只显示当前一级页面，新建与详情等二级工作流统一显示图标返回按钮和“一级页面 / 当前页面”层级导航，正文不重复页面级标题或返回链接。独立 Schedule 管理页、完整 Source 治理、完整 RBAC 管理、Kafka Sink 配置、漂移治理和生产级 Artifact Explorer 保留为后续实现范围。界面使用 SSOT 领域术语、`extrio.control-plane.v1` 与 `extrio.gather.v1` 机器合同，避免形成需要后端迁移的临时对象模型。

Collector 新建与详情的返回操作位于顶部栏层级导航左侧，使用带可访问名称与提示的箭头图标按钮；一级“采集来源”可点击返回保留需求筛选的列表上下文，正文不重复显示页面级标题或返回文字链接。字段和 Item 证据默认隐藏，用户点击阻断项、字段证据或样本后以右侧 Sheet 展示；Sheet 必须支持独立滚动、键盘关闭、焦点返回和明确的对象标题。已发布规则的状态、采集流程、输出字段、验证结果与审核结论直接显示在规则页，不设置额外规则详情 Dialog。采集配置中的规则编辑 Dialog 提供“规则编辑”和“JSON”两个 Tab，完整 GatherSpec 只在“JSON”中按需只读查阅；内部版本 ID 与 digest 不作为独立信息项展示。原始 JSON 不允许直接编辑，规则修改必须通过结构化表单进入受控 Override、候选验证和审核流程。

“运行”一级页面使用同一工作区切换“采集运行”和“AI 任务”，不增加新的侧栏入口。采集运行记录确定性 GatherSpec 的生产执行；AI 任务记录规则生成与修复的独立生命周期。每个 AiRun 固定 Collector、Source URL、触发原因、发起人和可选的一次性操作指引，重试追加 AiAttempt，模型调用追加只含 provider、model、purpose、promptVersion、Token、耗时、响应摘要和归一化错误的 ModelInvocation；不得保存原始提示词、模型思维过程、Source 样本或模型响应正文。AiRun 追加结构化阶段记录，覆盖排队、Source 获取、AI 结构分析、详情发现、样本获取、AI 规则编译、确定性验证和结果整理；活动任务详情自动轮询并显示当前阶段、已完成阶段、时间、耗时和非敏感指标。执行成功只表示候选规则生成完成，`ready_review`、`published` 与 `superseded` 独立表达审核结果。Collector 概览只提供最近 AI 任务的摘要入口，完整阶段、尝试和模型证据进入 AI 任务详情。产品不提供通用 Chat；用户通过绑定当前 AiRun 的一次性指引表达关注字段、页面结构或修复线索，每次重新提交都创建新的可审计 AiRun。

Run 详情的返回操作同样位于顶部栏；主标题使用包含协议与域名的 Source 根 URL 并并列终态，完整入口路径、开始时间、耗时和执行模式作为次级上下文，使同域名下的不同入口保持可辨识。页面不显示无信息眉题，也不让 Run ID 占据业务主信息。页面以“结果、执行过程、范围与增量、质量与证据”四个顶部任务视图组织信息，并与 Collector 详情统一使用左对齐紧凑、仅以文字和底部指示线表达选中的导航样式，不在内容中部放置局部 Tabs。结果视图以单行摘要同时展示运行结论、接收与拒绝、数据变化和耗时。执行证据先显示规则证明、固定采集范围、结果集冻结与 Artifact 保留方式的可读结论，ID、digest、attestation 和 SigningKey 仅在默认折叠的技术信息中按需查阅，不常驻右侧栏。

Item 详情的返回操作位于顶部栏，以公告标题和质量终态作为主信息，以 Source 身份、发布时间和 Revision 作为次级上下文。页面统一使用“数据内容、版本与观察、质量决定、来源与谱系”四个顶部任务视图：内容视图优先呈现规范化字段和正文；版本视图组合逐字段差异与历次观察；质量视图解释交付终态、标题一致性、来源边界和拒绝原因；谱系视图提供 Collector、详情来源和最近 Run 的可操作入口。Entity key、SourceRevision、CollectionVersion、RuleVersion、Observation 和 Artifact ID 只在默认收起的技术信息中按需查阅，页面不常驻右侧证据栏。

一级导航包含概览、采集需求、采集来源、运行、数据和设置。`/settings` 在同一工作面按供应商分组展示模型：顶部左侧提供唯一默认模型，右侧提供添加供应商，不展示无异常含义的数量统计；每个供应商组展示 HTTPS API 地址、启停状态、密钥状态和模型数量，模型在所属供应商内添加、编辑、启停、删除或设为默认。用户在供应商对话框直接配置 API Key，编辑时留空保留原密钥。浏览器不持久化密钥，控制面读取响应只返回是否已配置。

探索开始后先验证 Source 的实际可达性。域名解析、拒绝连接、连接关闭、超时或 robots.txt 阻断统一显示简短原因和检查网络、代理、网址的下一步，不向用户暴露 Crawl4AI 或浏览器内核堆栈。

## 6. 功能需求

| ID | 需求 |
| --- | --- |
| `FR-001` | 平台必须支持 TemplateVersion 与 Custom 两种方式创建 CollectionVersion，并在冻结前进行 JSON Schema 和业务语义校验。 |
| `FR-002` | 已冻结 CollectionVersion 必须不可变；字段、身份、质量或输出变化必须创建新版本。 |
| `FR-003` | 平台必须支持单个创建和批量导入精确 Source 入口；一个入口建立一个 Collector，同域名的不同业务列表允许分别建立 Collector，站点根目录不得作为 `exact` 入口，分页 URL 不得拆成多个入口。从“全部需求”进入新建页时默认创建新需求，从具体需求筛选上下文进入时默认复用该需求的 `collectionId`、采集意图和 CollectionVersion，用户仍可切换两种需求模式。CSV 使用 UTF-8，最大 2 MiB、1000 行，必需 `entryUrl` 列并兼容 `sourceUrl`、`url`、`网址`、`入口网址`；`mode` 可省略并默认为 `exact`，当前拒绝其他模式；`name` 与 `scopeHint` 可选。重新选择文件必须替换当前文件条目并保留手动条目；同一 URL 同时来自文件和手动输入时，文件内 `name`、`scopeHint` 等结构化元数据优先。文件级错误不得清空最近一次成功解析的预览。保存前逐项校验 HTTP(S) URL、入口粒度、允许域名、重复项和租户归属，只提交有效项；同批成功 Collector 必须共享稳定 `collectionId`、`collectionName` 与 CollectionVersion，匿名公共 HTTP 默认可用，TenantAdmin 可在界面采集策略中关闭。 |
| `FR-004` | Collector 必须明确引用一个 SourceRevision、一个 CollectionVersion、至多一个 AccessProfileVersion 和一组受控 CollectorOverride。 |
| `FR-005` | 接入编译必须通过默认模型生成受约束 RulePlan，并输出 GatherSpec、编译输入摘要、编译器版本、Agent 元数据、RulePlan Artifact、样本 Artifact 和校验报告；配置了默认模型但模型不可用，或 RulePlan 未通过 Schema、语义、安全和样本验证时，不得生成可审核候选。 |
| `FR-005.1` | 规则生成与修复必须提供可实时轮询、刷新可恢复的结构化阶段记录；阶段记录只保存阶段、状态、时间、耗时、指标与归一化错误。生成入口允许最多 500 字的一次性操作指引，指引作为不可信模型输入并固定在 AiRun 上，不得绕过受约束 selector 方言、网络边界、输出合同、确定性验证或人工发布门。 |
| `FR-006` | 发布前必须通过 Schema、语义、安全边界和样本质量门；只有 RuleReviewer 可以发布或回滚，活动规则必须具有有效 RuleAttestation。 |
| `FR-007` | 平台必须支持 `single` 与 `list_detail` 两种采集模式、HTTP/受限浏览器传输以及 `none`、`page`、`next_link` 分页策略；浏览器规则必须固定 waitUntil 与 postLoadDelayMs，使异步填充的列表在接入验证和生产执行中使用同一 DOM snapshot 时点；同域 iframe 外壳必须解析为可执行的同域列表入口并冻结进 GatherSpec；`list_detail` 必须保留产生详情 URL 的列表记录上下文，不得把详情页内部重复结构擅自改成 Item 粒度。 |
| `FR-008` | 平台必须支持 Schedule 的创建、启用、暂停和归档；当前版本必须禁止同一 Collector 产生重叠 Run。 |
| `FR-009` | Run 必须支持取消、超时、部分成功、重试和固定版本执行；运行历史必须可查询。`list_detail` Run 必须核对详情 URL 发现数与实际抓取数；存在缺口时记录 `detail_fetch_incomplete`，以部分成功或失败终结，不推进 Checkpoint，并向用户显示缺失数量和恢复动作。详情响应疑似与列表记录错配时必须以受限单 URL 重取复核，不得接收错页内容。 |
| `FR-010` | 平台必须按稳定实体键创建 HarvestItem；每次有效观察创建 HarvestObservation；输出合同摘要或 payload 指纹变化时追加 HarvestItemRevision。`list_detail` Item 的 canonical title 来自详情文档，列表标题单独保留；两者归一后不一致的候选必须拒绝，且不得生成 Revision、Observation 或 Delivery。 |
| `FR-011` | 平台必须支持 Webhook Sink（v0.3 交付）与 Kafka Sink（后续版本提供），并为每个 Item 事件和 SinkVersion 建立可重试、可审计的 Delivery；同目标人工重新交付不得创建重复逻辑 Delivery。 |
| `FR-012` | 平台必须通过 `metadata_only`、`sampled`、`replayable` 三种 ArtifactManifest 证据等级提供运行证据；只有完整 `replayable` 证据可用于等价验证回放，生产重新交付必须单独授权。 |
| `FR-013` | 平台必须检测 Source 漂移、连续失败、队列滞后、交付失败和异常数据量，并关联到可操作对象。Operation 持久化入队时间；排队超过交互阈值时界面必须说明 Worker 与 API 数据库一致性检查及自动恢复行为。 |
| `FR-014` | 平台必须提供本地多用户与角色（administrator、engineer、reviewer、viewer；RBAC）、不可变 AuditEvent、凭据引用和敏感信息脱敏。 |
| `FR-015` | 平台必须支持 RuleVersion 回滚；回滚不得改变已经创建或运行中的 Run。 |
| `FR-016` | Operator 必须能够独立于 GatherSpec 配置版本化 CollectionPolicy：首次运行默认采集最近 30 天，后续运行从最近一次成功 Checkpoint 减去 3 天回看窗口开始；Run 必须固定 policy version、窗口边界和 Checkpoint 前值。 |
| `FR-017` | 日期降序列表必须在连续两页均早于窗口边界时提前停止；只有完整成功 Run 可以原子推进 Checkpoint，失败、取消、超时和预算截断不得推进。 |
| `FR-018` | Collector 详情必须展示并允许编辑采集名称、意图和 Source 入口，同时展示活动规则与候选规则摘要。名称编辑不得影响执行；意图或入口变化必须清除当前候选并阻断新 Run，直到新候选经审核发布。候选规则编辑必须以实际执行顺序集中呈现可修改的列表 Item selector、可编辑网页业务字段 selector、分页参数、`detailUrl` 交接和输出字段 selector；系统管理字段不得进入编辑表单；请求配置、字段类型、错误策略、转换、安全边界与 Item 边界不得在表单重复展示，只在只读 JSON 中查阅；规则页直接以人可理解的发布信息说明规则状态、采集模式、字段与验证结果，完整 GatherSpec 只在采集配置的“编辑规则”Dialog 内以“JSON”Tab 按需只读展示，内部版本 ID 与 digest 不作为独立信息项展示；原始 JSON 不得直接编辑。两个阶段的 selector 与分页参数编辑必须形成受控 Override、新 digest 与新的审核决定集，使用最近探索样本通过 Schema、发现和必填字段质量验证；字段语义只能通过新 CollectionVersion 变化，已发布 RuleVersion 不得原地更新。 |
| `FR-019` | TenantAdmin 必须能够分别管理多个规则编译模型供应商和多个模型，并快速切换唯一默认模型。供应商保存 HTTPS API 地址；用户可在写请求中直接提交 API Key，控制面必须立即使用独立主密钥加密且不得持久化或返回明文，模型只属于一个供应商；生产 Run 不得读取该配置或调用模型。 |
| `FR-020` | 每次异步规则生成或修复必须持久化 AiRun、AiAttempt 与 ModelInvocation 历史，并可按列表和详情查询。执行终态与人工审核终态必须分离；发布时把对应最新候选标记为 `published`，旧候选标记为 `superseded`。审计记录不得保存原始提示词、Source 样本或模型响应正文。 |

## 7. 非功能需求

| ID | 需求 |
| --- | --- |
| `NFR-001` | 运行期不得调用 LLM、生成代码或加载用户提供的可执行代码。 |
| `NFR-002` | 所有输出必须可追溯至 Tenant、CollectionVersion、SourceRevision、AccessProfileVersion（如适用）、Collector、RuleVersion、RuleAttestation、Run、HarvestObservation 和 ArtifactManifest。 |
| `NFR-003` | 平台必须按 at-least-once 处理与交付，并通过稳定幂等键使重复尝试可识别。 |
| `NFR-004` | 控制面月度可用性目标为 `99.9%`，计划维护窗口不超过每月 4 小时并提前通知。 |
| `NFR-005` | 在 v0.6 设计目标内，Schedule 到 Run 入队的延迟目标为 `p95 <= 5 分钟`、`p99 <= 15 分钟`；该目标在公开 benchmark 前不构成已验证 SLO。 |
| `NFR-006` | 平台自身导致的已确认 HarvestItem 丢失率必须低于 `0.01%`；每一次未交付必须具有明确状态和证据。 |
| `NFR-007` | 元数据 `RPO <= 15 分钟`、`RTO <= 4 小时`；Artifact `RPO <= 24 小时`、`RTO <= 8 小时`。 |
| `NFR-008` | Source 凭据、租户数据和网络访问必须满足 [`security-compliance.md`](./security-compliance.md)。 |
| `NFR-009` | GatherSpec 同一主版本内必须保持向后兼容；不兼容变化必须使用新的 Schema 主版本。 |
| `NFR-010` | 指标不得使用 Run ID、Item ID 或 URL 等无界高基数字段作为常驻标签。 |
| `NFR-011` | 浏览器 API 必须符合 `extrio.control-plane.v1`：所有用户可见失败具有稳定错误码、可理解说明、关联对象和 request ID；所有写请求具有幂等键，异步探索与 Run 通过可恢复 Operation 暴露进度和终态。 |
| `NFR-012` | 关键操作界面必须支持键盘操作、清晰焦点、非颜色唯一状态表达和 WCAG 2.2 AA 对比度。 |
| `NFR-013` | 公开 Alpha 必须通过本地多用户账户与角色（administrator/engineer/reviewer/viewer，首次设置创建 administrator）、Argon2 密码哈希和服务端可撤销会话保护控制面；外部 OIDC/SSO、MFA step-up 与独立服务身份仍为后续范围。 |

## 8. v0.6 未验证设计目标

以下数值是架构设计目标，不是当前版本已经验证的容量、SLO 或对用户的服务承诺。只有公开 benchmark 和对应部署证据覆盖后，数值才能升级为发布保证：

| 维度 | 目标 |
| --- | --- |
| 活跃 Tenant | 100 |
| 活跃 Collector | 10,000 |
| 每日规范化 Item | 1,000,000 |
| 同时运行的 Run | 200 |
| HTTP 全局并发请求 | 500 |
| 浏览器上下文并发 | 25 |
| 单 Run 最大 Item | 100,000 |
| 单 Run 默认最长时间 | 4 小时 |
| 单响应默认最大解压后体积 | 20 MiB |

租户、Source 和 Collector 必须具有可配置配额；任何超限必须以显式状态结束，不得静默截断。

## 9. 数据质量与成功指标

### 9.1 产品成功指标

| ID | 指标 | v0.6 产品验证目标 |
| --- | --- | --- |
| `KPI-001` | 支持范围内 Source 从创建到首个有效样本的中位时间 | 不超过 30 分钟 |
| `KPI-002` | 支持范围内 Source 不编写代码即可发布的比例 | 不低于 90% |
| `KPI-003` | 已发布规则 30 天内无需重编译的比例 | 不低于 85% |
| `KPI-004` | 必填字段完整度 | 每个 Run 不低于 CollectionVersion 门槛，默认 95% |
| `KPI-005` | 同一 Sink 可识别的重复 Delivery 比例 | 低于 0.1% |
| `KPI-006` | Source 漂移发现时间 | Schedule 间隔不超过 12 小时时，不超过 2 个计划 Run且最长不超过 24 小时；更低频 Schedule 不超过 2 个计划 Run |
| `KPI-007` | 平台故障导致的 Source 恢复时间中位数 | 不超过 4 小时 |

“支持范围内 Source”指：具有合法访问权；不要求绕过验证码、付费墙或访问控制；符合 list/detail；使用 HTTP 或受限浏览器；使用 `page` 或 `next_link`；响应体积和运行时间在设计容量内。

### 9.2 质量门

- 必填字段完整度低于 CollectionVersion 门槛时，Run 不得标记为完整成功。
- 身份字段为空时必须拒绝 Item，不得生成不稳定实体键。
- 字段类型转换失败必须遵循规则中明确的 `onError`，不得使用隐式猜测。
- 空结果只有在历史基线和 Source 语义允许时才能视为成功，否则进入漂移评估。

## 10. 边界与异常场景

- Source 重定向到未授权域名时立即阻断请求并产生安全事件。
- Source 入口只允许 HTTP(S)。匿名公共 HTTP 默认允许，TenantAdmin 可在界面采集策略中关闭；携带 AccessProfileVersion 或任何凭据的 Source 请求必须使用 HTTPS，且凭据不会因 redirect 自动转发到其他 origin。
- Source 返回登录页、验证码页或封禁页时不得继续尝试绕过；Run 进入失败或部分成功。
- CollectionVersion 升级不会自动切换现有 Collector；必须重新编译、验证和发布。
- RuleVersion 发布与 Schedule 触发并发时，Run 使用创建事务中读取到的活动版本。
- 同一实体内容未变化时可以记录已观察时间，但默认不产生新的 Item 事件。
- Source 列表中未出现历史实体不代表删除；只有规则能明确识别撤销或删除时才产生 tombstone。
- Sink 不可用不会回滚已经确认的采集结果；Delivery 独立重试并最终进入 DeadLettered。
- Run 结果在 finalization 质量门完成前不得交付；Failed、Cancelled 和 TimedOut Run 默认不提升生产 ItemEvent 或 Delivery。
- ArtifactManifest 不是完整 `replayable` 模式、chunk 不连续或 Artifact 已过保留期时，系统必须明确说明无法进行证据等价回放，不能退化为实时 Source 请求并声称结果等价。

## 11. 集成需求

- 身份认证：本地多用户与角色（administrator/engineer/reviewer/viewer）属于公开 Alpha 能力，首次设置创建 administrator，密码使用 Argon2 哈希并配合不透明服务端会话；外部 OIDC/SSO、MFA、多租户隔离与独立工作负载身份属于后续演进范围。
- 凭据管理：通过 AccessProfileVersion 引用 Secret Manager，不在规则中保存可用明文。
- LLM：只允许编译服务使用，并记录 provider、model、promptVersion 和 toolchainVersion。
- Kafka：使用预配置 Sink，支持稳定消息键和幂等 producer 配置。
- Webhook：使用预配置 HTTPS Sink，支持签名、幂等头、超时和重试。
- 对象存储：保存 raw、样本和验证报告，使用租户前缀、加密和生命周期策略。
- 可观测性：支持 OpenTelemetry trace、结构化日志、低基数指标和告警路由。

## 12. 产品验收原则

1. 每个 `FR-*` 必须在 [`releases/v0.2-acceptance.md`](./releases/v0.2-acceptance.md) 中至少映射一个可观察验收场景。
2. 每个 `NFR-*` 必须具有自动化报告、压测、安全测试、恢复演练或人工检查证据。
3. 阻断级安全问题、跨租户访问、凭据泄露、静默数据丢失或无法追溯的生产数据均阻止发布。
4. 产品负责人和技术负责人明确批准发布证据后，v0.6 才能进入生产。

### 概览看板时间范围

概览看板把今日采集、本周运行成功率、本月有效数据和当前规则覆盖作为并列经营指标，不使用单一周期切换整页内容。日、周、月作为采集产出趋势的图形聚合口径，分别覆盖最近 14 天、12 周和 12 个月；趋势按接收与拒绝数据堆叠，旁侧运行质量说明同一范围内的成功、部分成功、失败和数据通过率。经营指标通过 `GET /api/v1/overview?timezone=<IANA>` 在服务端全量聚合，不受列表 200 条上限影响。按浏览器时区的自然日、周一和自然月划分半开区间，运行按持久化创建时间归桶；成功率分母仅包含已终结运行，取消/超时计失败，活动运行单列。本月实体先按来源与 entity key 取最新观测，再按该行 UTC 入库时间判断月份；历史 observedAt 展示字符串不用于时区推断。页面提供快照时间和刷新，失败显示无法确认而不是零或健康。需要关注区域使用来源及最近运行列表，只展示最多三项，不作为全量异常统计。

## 13. 约束与假设

- v0.6 采用单区域部署，通过备份和恢复满足灾备目标。
- Source 可用性和响应正确性不计入控制面 SLO，但 Extrio 必须正确归因并展示外部失败。
- 初始生产发布保持人工规则审核；自动发布不属于 v0.6。
- v0.6 不对 Source 缺失实体自动推断删除。
- v0.6 为具有可提取列表发布时间且按时间降序排列的 `next_link` Source 提供受控增量：首次运行使用最近 30 天窗口，后续运行使用成功 Checkpoint 与默认 3 天回看。通用 cursor、无限滚动和任意增量表达式不在当前范围。
- 当前合同不存在阻止规划和实现的高影响开放问题。
