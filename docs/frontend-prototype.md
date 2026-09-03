# Extrio 第一版前端原型合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v1.33.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Confirmed` |
| 权威来源 | [`SSOT.md`](./SSOT.md)、[`product-contract.md`](./product-contract.md) |
| 用户批准 | `2026-08-30`，批准先完成最小前端闭环并采用 Vite + pnpm + React + shadcn/ui |
| 最后更新 | `2026-09-02` |
| 交付责任 | 产品负责人、前端负责人 |

## 2. 产品简述

Extrio Web 控制台面向数据接入与运营人员，把一个采集需求和多个授权 Source 从批量接入推进到可审核规则、确定性运行和可追溯 Item。第一版通过 FastAPI、Crawl4AI 与 Crawlee 跑通真实本地纵向闭环，所有对象、状态、ID 和 API 边界与 SSOT 保持一致；MSW 保留为前端隔离开发和合同测试环境。

目标用户需要在同一工作上下文中完成三类判断：Source 是否可访问、候选规则是否可信、Run 产出的 Item 是否满足数据合同。界面重点是状态、证据和下一步动作，不是展示平台功能数量。

## 3. 参考吸收

- `iiwish/caiji`：吸收 Source 工作台、对象上下文连续性、浅色运营界面和明确主动作；不复用其页面级巨型组件、集中 PrototypeContext 或旧领域术语。
- `iiwish/bidly`：吸收样本审核门禁、Action Ladder、紧凑表格和先异常后指标的信息组织；不复用暗色皮肤、静态页面堆叠或 Rule Pack 模型。
- Extrio 使用自己的对象体系：Website 映射为 Source，Rule Pack 映射为 RuleVersion，Execution 映射为 Run，Article/Original 映射为 HarvestItemRevision。

## 4. 最小闭环

```text
选择已有需求或定义新需求，并批量添加采集入口 URL
  -> 为每个 Source 建立独立 Collector
  -> 识别 single 或 list_detail
  -> single：从入口直接提取业务字段
  -> list_detail：遍历列表分页、发现 detail URL、抓取详情并提取字段
  -> LLM 编译 extrio.rule-plan.v1，平台验证并生成 extrio.gather.v1 候选规则与证据
  -> 审核字段、样本、质量与网络边界
  -> 批准并发布 RuleVersion
  -> 立即运行
  -> 查看 accepted/rejected Item 与完整 lineage
```

闭环使用一个演示 Tenant、标讯 CollectionVersion、多个 Source 和一个 RuleReviewer 身份。一个需求通过稳定 `collectionId` 与 `collectionName` 共享 CollectionVersion，每个 URL 创建独立 Collector 并返回逐项创建或拒绝结果。Collector 列表通过所属需求列和可搜索需求筛选器支持跨需求运营与需求内查看；文件夹不承担领域归属。用户操作通过符合 `extrio.control-plane.v1` 的 FastAPI 触发持久化状态转换；探索与 Run 返回 `202 Accepted` Operation，独立 Worker 使用 Crawl4AI 或 Crawlee 执行，页面轮询服务端事实并可在刷新后恢复，不使用静态截图或客户端伪造进度。

Source 输入只接受 HTTP(S)。HTTPS 直接进入正常校验；匿名公共 HTTP 在本地 TenantAdmin 策略允许时显示“风险已标记”并可继续导入。配置 AccessProfile 或凭据的 Source 必须使用 HTTPS。前端提示不得把 HTTP 风险接受描述为主机、DNS、重定向或凭据边界的豁免。

## 5. 信息架构

### 5.1 一级导航

| 路由 | 名称 | 页面任务 |
| --- | --- | --- |
| `/` | 概览 | 判断运行健康、规则覆盖、数据质量与异常趋势 |
| `/collectors` | 采集器 | 创建和继续一个 Collector 闭环 |
| `/runs` | 运行 | 在统一工作区比较采集 Run 与 AI 规则任务 |
| `/ai-runs/:aiRunId` | AI 任务详情 | 查看候选结果、执行尝试、模型用量和审计证据 |
| `/items` | 数据 | 查看规范化 Item、Revision 和谱系 |
| `/settings` | 设置 | 配置规则编译模型的供应商、模型与加密凭据 |

概览、采集器、运行、数据和设置构成第一版一级导航。品牌标识与“概览”导航都返回 `/`，未知路由也回到概览，确保用户始终能回到工作区起点。侧栏上部放置核心业务导航，设置固定在底部；侧栏不常驻显示 API 或 Mock 环境提示；顶部栏只显示当前一级页面标题，不重复工作区名称或层级分隔。Schedule、Sink、漂移中心和完整治理后台不进入第一版一级导航。

`/` 是运营工作台而不是营销首页。页面回答“整体是否健康、趋势如何、哪里需要介入”：使用实际运行成功率、已发布规则覆盖和最新实体质量通过率作为核心指标，用最近运行的数据量与终态组成趋势图，并只保留最多三项异常入口。Run 和 Item 明细仍进入对应一级页面，概览不重复列表、技术 ID、推断式质量分或继续工作入口。健康且最近运行成功的已发布 Collector 不进入待处理队列。`/collectors`、`/runs` 与 `/items` 直接以单行顶部工具栏和固定列运营列表进入操作，不显示重复的页面标题、说明或概览指标卡。三个对象列表都使用固定列支持高密度横向比较。筛选必须真实生效并写入 URL，不展示仅用于占位的搜索、筛选或设置控件。

三个列表分别回答不同问题：Collector 固定列列表回答 Source 是否可运行、属于哪个需求、当前规则和最近运行是什么、下一步做什么，并从真实最近 Run 计算健康；Collector 顶部工具栏在一行内从左到右放置状态筛选、可搜索需求筛选和新建操作，新建按钮位于最右侧，不显示需求标签或布局切换。需求筛选器打开后自动聚焦输入框，按需求名称或合同版本实时过滤选项，选择后更新 URL 并关闭弹层。每行固定对齐 Source 身份、所属需求、状态、活动规则、最近运行和下一步，点击整行进入详情；完整需求说明与采集策略进入详情。运行页先以统一线型导航切换“采集运行”和“AI 任务”，不增加侧栏入口；采集 Run 工具栏保留状态筛选、名称或 Run ID 搜索、排序提示和刷新，固定列对齐执行终态、接收与拒绝、范围与停止原因、开始时间与耗时；AI 任务工具栏按进行中、待审核和需处理筛选，固定列对齐 Collector、任务类型、执行状态、候选结果、模型消耗、开始时间与耗时。AI 任务详情以 Source 根 URL 为主标题，以“结果、执行过程、模型调用、证据”组织内容，原始提示词与响应正文不进入界面。Item 顶部工具栏把 Source、Collector 与质量决定筛选放在左侧，把标题、正文、Collector 或 entity key 搜索放在右侧；固定列列表逐行对齐实体身份、质量决定、变化与 Revision、发布时间、最近采集和 entity key。数据行对 Collector 展示名与 Source host 做语义去重，相同时只显示 host，不同时才并列提供上下文；Source 筛选项只显示 host。Item 列表按 `collectorId + entityKey` 聚合为最新实体，重复 Run observation 进入详情的观察历史，不在实体列表重复占位。

`/settings` 直接进入无重复页面标题的紧凑配置工作面，不设置“供应商配置 / 模型设置”平级 Tabs。顶部工具栏只在左侧展示带星标的唯一默认模型选择，在右侧提供添加供应商，不展示供应商数或可用模型数；正文按供应商分组，组标题展示配置名称、HTTPS API 地址、密钥配置状态、启停状态和模型数量，模型作为该组的子行展示并在当前供应商上下文中添加。供应商和模型的低频编辑、启停与删除操作收纳进各自行末菜单。供应商对话框提供遮罩式 API Key 输入和显隐按钮，新建时必填，编辑时留空保留原值。密钥只随保存请求提交，不进入浏览器存储；API 读取只返回 `credentialConfigured`，不回显密钥。删除供应商会同时删除其模型与加密凭据，停用或删除默认项后自动选择下一个可用模型。设置页在供应商配置上方提供“界面语言”单行控件，可在中文与 English 之间即时切换控制台语言，选择写入本机并在下次访问保持；界面文案通过 i18next 命名空间组织，中文为默认与兜底语言。

Collector 探索失败时，工作区错误条只显示 Source 主机、归一化失败原因和可执行检查动作。第三方抓取器堆栈、源码位置和浏览器调用日志不进入页面正文。

### 5.2 Collector 工作台

Collector 详情以对象状态驱动主任务，顶部栏在当前页面标题左侧提供仅图标返回按钮，正文不重复放置返回文字链接。对象区显示稳定 Source 名称、可返回需求筛选列表的需求归属、当前阶段和唯一主动作；批量导入的“入口 N”顺序不进入主标题，完整入口网址只在概览中出现一次。正文使用“概览、规则、采集配置”三个一级任务视图：`ready_review` 默认进入规则审核，其余状态默认进入概览；没有候选或活动规则时不显示规则 Tab。概览集中展示当前状态、入口网址、活动规则、运行范围、最近运行和最多五条最近结果，并以单个紧凑入口关联最近 AI 任务；规则审核先显示发布阻断和审核摘要，再以字段审核/样本数据二级切换完成决定，已发布规则则展示确定性采集流程与验证指标。已发布规则的状态、采集流程、输出字段、验证结果和审核结论直接显示在规则页，不设置额外规则详情 Dialog。采集配置以摘要展示 Source 定义、规则编辑、定时运行、增量策略、Webhook 推送配置和投递记录；定时运行提供启停、常用频率、自定义五段 Cron、下次运行与禁止重叠说明，规则编辑 Dialog 提供“规则编辑”和“JSON”两个 Tab，完整 GatherSpec 只在“JSON”中按需只读展示；内部版本 ID 与 digest 不作为独立信息项展示，原始 JSON 不允许直接编辑。Webhook 配置提供地址、遮罩式密钥输入、启停、发送测试与版本展示；投递记录逐行展示状态（待投递/投递中/已送达/失败/死信）、最近尝试与错误摘要，死信与失败记录提供重新投递。字段与 Item 证据默认隐藏，用户选择对应对象后通过右侧 Sheet 显示并独立滚动，关闭后返回原触发点。

名称修改只更新对象识别信息。需求描述或 Source 入口变化时，界面明确说明当前候选失效、历史 RuleVersion 保持可追溯但新 Run 被阻断，并提供“保存并重新生成”主路径。直接规则编辑只操作候选草稿，覆盖列表 Item selector、网页业务字段 selector、分页类型/参数/上限和详情输出字段 selector；`source`、`crawlTime`、`observedAt` 等系统管理字段不进入编辑表单；`detailUrl` 同时作为 Stage 01 输出和 Stage 02 请求输入，不提供含义重复的第二个输入框。字段类型、必填性、错误策略、转换、identity、Item 边界和采集时间来源由 CollectionVersion 固定，只在只读 JSON 中按需查阅，不在编辑表单逐字段重复展示。保存后审核决定清空，服务端使用最近探索样本完成 Schema、详情发现和必填字段验证，再返回新的候选 digest。活动 RuleVersion 不提供编辑入口。

Source 探索和生产运行支持两个确定性计划。`single` 使用必填 list stage 将入口页视为一个采集单元并直接提取字段，不创建 detail stage。`list_detail` 的 Stage 01 执行 `page`、`next_link` 或无分页策略并规范化 detail URL，Stage 02 在同一 Run、RuleVersion、预算和 allowedHosts 边界内抓取详情并进行质量终结。分页是 list stage 内部策略；两阶段不建模为两个独立 Run，也不要求用户手动接力。

公告类 `list_detail` 的数据视图以列表公告为 Item：Stage 01 展示列表标题与详情 URL，Stage 02 展示详情标题、发布时间和公告正文，Run 的 `observedAt` 作为采集时间。Item 列表、Run 结果与 Item 详情不得使用详情正文内部的采购项目、采购单位或预算代替公告级字段。

Collector 工作台必须把“什么时候运行”“怎么翻页”和“采集到哪里”分开展示。定时运行使用独立 Schedule 配置，支持启停、常用频率与自定义五段 Cron，固定 `Asia/Shanghai` 和 `overlapPolicy=forbid`；采集流程确认 next_link 选择器、允许主机和规则硬上限；采集范围面板配置首次窗口、增量回看、连续旧页停止和操作限额，并显示当前 policy version 与 Checkpoint。Collector 与 Run 详情统一使用全宽等分线型任务导航，激活态只使用文字色和底部指示线，不以按钮底色制造额外层级。Run 详情把返回入口放在顶部栏，以 Source 根 URL 和终态作为主信息，将完整入口路径、开始时间、耗时和执行模式收为次级上下文，既避免长 URL 抢占标题层级，也能区分同域名的不同入口；页面不显示“运行记录”眉题。结果、执行过程、范围与增量、质量与证据作为顶部一级任务视图，结果摘要压缩为单行结论与指标带。initial/incremental 模式、窗口下界、窗口外数量、new/updated/unchanged、停止原因和 Checkpoint 前后值进入对应任务视图。

### 5.3 详情层级

- 列表到详情只有一层；精确证据使用 Sheet，不再打开新的嵌套详情页。
- 返回列表必须恢复搜索、筛选和滚动上下文。
- Run 到 Item、Item 到 lineage 使用明确可返回链接。
- Collector 详情主内容按任务视图组织，证据使用按需 Sheet；Run 详情在“质量与证据”视图先展示人可读的可信结论，再以默认收起的技术信息承载 ID、digest 与证明版本，不常驻右侧 evidence rail；Item 详情同样以顶部任务视图组织内容、版本与观察、质量决定、来源与谱系，完整 lineage ID 只在默认收起的技术信息中展示，不常驻右侧证据栏。Collector、Run 与 Item 列表使用带列头的单一表面和行分隔，连续连接线只用于采集阶段与 lineage 等真实关系，不承担普通信息分隔。

## 6. 技术合同

- 包管理：`pnpm`。
- 构建：Vite + React + TypeScript。
- 组件：shadcn/ui 源码组件、Radix primitives、Lucide icons。
- 样式：Tailwind CSS + CSS variables；不引入第二套组件库。
- 路由：React Router。
- 服务端状态：TanStack Query。
- API：浏览器只访问 `/api/v1`；OpenAPI 机器权威为 [`contracts/openapi.yaml`](./contracts/openapi.yaml)，TypeScript 类型由 `pnpm api:generate` 生成。
- 异步命令：探索和 Run 返回 Operation；前端按 `pollAfterMs` 轮询，处理 `succeeded`、`failed`、`cancelled`、`timed_out`，成功后重新读取领域资源。
- API 环境：Vite 隔离开发默认启用 MSW，设置 `VITE_ENABLE_MOCKS=false` 后连接 FastAPI；MSW 与 OpenAPI 使用相同路径、状态码、请求头和响应结构。控制面不可用时前端返回可操作的环境提示，不使用无上下文的通用失败文案。
- Schema：候选规则包含服务端返回的完整 GatherSpec；界面原样显示并由 Draft 2020-12 测试校验。浏览器只提交 OpenAPI 定义的 `CandidateRuleEditInput`，由服务端应用 Override、重算 digest、验证最近样本并返回完整 GatherSpec，浏览器不自行发布或补全机器合同。
- 原型数据：真实中文标讯字段和完整 lineage；不得出现 lorem ipsum、example dashboard 或无业务含义的 KPI。

目录边界：

```text
web/src/
  app/          应用入口、router、providers、shell
  api/          typed client、MSW handlers、fixtures
  components/   跨 feature 组件
  components/ui shadcn/ui 组件
  features/     collectors、review、runs、items、settings、evidence
  lib/          纯函数、格式化、状态语义
```

禁止把全部业务状态放进 AppShell 或单一 Context；页面只通过 typed API hooks 和局部 UI state 协作。

## 7. 设计合同

### 7.1 方向

- Surface：面向专业运营人员的桌面端 operational product surface。
- Design thesis：像检查一条可证明的生产流水线一样完成采集接入，每个决定旁边都有证据。
- Signature move：任务视图先聚焦当前决定，用户选择阻断项、字段、样本、规则、Run 或 Item 时，右侧证据 Sheet 定位到对应固定事实。
- 首页 signature move：把今日、本周、本月经营口径并列放进同一指标带，并让日、周、月只控制采集产出趋势的聚合颗粒度。
- 第一视口必须直接呈现当前 Collector、阶段、阻断项与主动作，不使用营销 hero。

### 7.2 视觉系统

| Token | 值 | 用途 |
| --- | --- | --- |
| `--background` | `#F5F7F8` | 应用底色 |
| `--surface` | `#FFFFFF` | 主工作区 |
| `--surface-subtle` | `#EEF2F3` | 工具栏、选中前背景 |
| `--text` | `#172126` | 主文字 |
| `--text-muted` | `#65737B` | 元数据 |
| `--border` | `#D9E0E3` | 分隔与表格线 |
| `--accent` | `#2557D6` | 主要动作和选中状态 |
| `--teal` | `#087F73` | 探索和证据状态 |
| `--success` | `#16805A` | 通过、已发布 |
| `--warning` | `#B56A09` | 待审核、部分成功 |
| `--danger` | `#C23B3B` | 阻断和失败 |

- 字体使用系统中文 UI 字体栈；正文 `14px/1.6`，紧凑元数据 `12px/1.5`，页标题 `22px/1.35`，letter-spacing 固定为 `0`。
- 间距基数 4px；页面 24–32px，卡片 16–20px，工具栏 8–12px；对象卡片之间保留 12px 间距。
- 卡片圆角不超过 8px；白色表面、克制阴影和多色状态图标建立层级。卡片内部通过字体、留白和浅色状态带组织，不再嵌套新的卡片或依赖连续横线分隔。
- `--border` 只用于卡片外边界、输入控件和真正的表格；阶段连接、lineage 和 diff 可使用具有语义的细线。
- 无渐变、无装饰光球、无大面积深蓝或紫色；状态颜色同时配图标与文本。
- 动画只用于阶段完成、证据 Sheet/rail 切换和异步状态，持续 140–220ms；尊重 reduced motion。

### 7.3 桌面视口

- 支持范围为 `1280px` 及以上桌面视口；移动端和窄屏适配不进入设计、实现或验收。
- `1440x900` 是主要设计与视觉 QA 视口，`1280x800` 是最小支持 QA 视口。
- Collector、Run 与 Item 列表在 `1280px` 及以上使用稳定固定列布局；字段审核等高密度比较任务保留表格。Collector 主工作台使用稳定的一级任务导航与全宽内容区，证据 Sheet 在打开时覆盖右侧而不改变主区布局。
- 既有窄屏样式可以在不增加复杂度时保留，但不得作为产品能力、验收结论或后续投入依据。

## 8. 交互与状态

必须实现：

- 从全部需求列表进入时默认定义新需求，从具体需求筛选上下文进入时默认选中并复用该需求的采集意图；用户可切换模式后批量添加多个采集入口 URL，支持逐行校验、HTTP/HTTPS 传输标记、去重、提交 loading、逐项创建/拒绝结果和部分成功；每个成功 URL 建立独立 Collector，同批 Collector 返回并共享稳定需求身份，匿名 HTTP 必须显示风险状态。
- Collector 列表首行工具栏集中状态筛选、可按名称或合同版本输入搜索的需求筛选器和右侧新建操作，不显示需求标签或布局切换；筛选写入 URL。固定列列表逐行展示 Source 身份、所属需求、状态、活动规则、最近运行和下一步，详情可返回所属需求筛选结果。
- Run 列表首行工具栏集中状态筛选、按 Collector 名称或 Run ID 搜索、开始时间排序提示与刷新；状态和搜索写入 URL。列表固定对齐身份、终态、接收数、拒绝数、执行范围与停止原因、开始时间与耗时，整行可进入 Run 详情。
- `list_detail` Run 的范围列使用“已抓取/已发现”展示详情页完整度；详情抓取不完整时明确显示部分成功、`detail_fetch_incomplete`、缺失数量和恢复建议，不把已冻结的 accepted Item 误报为完整成功。
- Operation 阶段使用 `queued`、`fetching_list`、`discovering_details`、`fetching_details`、`validating`、`finalizing`、`completed`；状态使用 `queued`、`running` 与四种终态，阶段与指标完全来自 API。
- 候选规则审核根据 `mode` 展示 `single` 单阶段或 `list_detail` 两阶段采集流程；分页策略、停止条件、detail URL 样本和 allowedHosts 证据仅在适用时出现。
- 字段审核使用 `approved`、`risk_accepted`、`excluded`、`pending` 四种明确决定；任何 `pending` 字段阻断发布，发布确认必须逐项汇总决定。
- 样本 accepted/rejected 标记和证据定位；字段、样本、已发布规则、Run 与 Item 分别通过按需 Sheet 显示对应证据，不复用过期选择状态，页面初始状态不显示证据 Sheet。
- 发布确认、权限说明、发布 loading、成功和失败。
- 已发布状态展示 canonical rule digest；新 Run 的“质量与证据”视图直接展示 RuleAttestation、固定策略和结果集冻结状态，attestation ID、digest、SigningKey 与 trust revision 收纳进默认折叠的技术信息，失败不得伪装为已验证。
- Run 的 queued、running、finalizing、succeeded、partially_succeeded、failed、cancelled、timed_out。
- rejected 候选不生成 HarvestItemRevision 或 HarvestObservation；界面显示“未生成”并保留 Run、SourceRevision 与 Artifact 证据，不伪造 Revision 0。
- `partially_succeeded` Run 的第一视口必须解释原因、影响范围和下一动作，并允许直接进入拒绝 Item 或返回 Collector 规则工作台。
- Item 顶部工具栏左侧提供 Source、Collector 与质量决定筛选，右侧提供关键词搜索，并将状态写入 URL；固定列列表按 `collectorId + entityKey` 展示最新实体，逐行显示公告标题、质量决定、变化、Revision、观察次数、发布时间、最近采集时间和 entity key。Item 详情顶部显示公告标题、终态、Source、发布时间和 Revision，并通过“数据内容、版本与观察、质量决定、来源与谱系”四个线型任务视图分别承载正文、差异和历史、质量结论、可操作来源入口与完整 lineage；技术 ID 默认收起。
- 导航、按钮、Tab、Sheet、Dialog 的 hover、focus、active、disabled 和 keyboard path。
- 设置页支持多个供应商、每个供应商的多个模型、供应商和模型启停、级联删除与唯一默认模型快速切换；密钥未解析状态使用文字和图标共同表达，API 与浏览器均不出现密钥明文。

## 9. 非目标

- 本地闭环由 Crawl4AI 按固定导航条件和异步内容沉降时长固化入口、列表和详情样本，当前默认模型在接入期编译受约束 RulePlan，服务端验证 selector、分页、字段、身份与样本命中后生成候选 GatherSpec 并记录模型谱系；已发布规则的生产 Run 使用同一浏览器 snapshot 时点和确定性运行时，不读取模型设置或调用 LLM。开发持久化使用 SQLite 与本地 sampled Artifact。
- 实现首次本地管理员设置、最少 8 个字符的密码输入约束、登录与退出；多 Tenant 切换、MFA、四眼审批和审计导出不在公开 Alpha 范围。
- 不实现独立 Schedule 管理页、Kafka Sink、漂移恢复和 Artifact 下载；Collector 详情内提供可执行的定时计划配置、Webhook Sink 配置、投递记录与重新投递（v0.3 交付），Item 列表工具栏提供携带当前筛选的 CSV/JSONL 数据导出。
- 不把 mock 状态或演示签名描述为生产证据。

### 概览看板时间范围

概览看板的指标带同时显示今日采集、本周运行成功率、本月有效数据和当前规则覆盖。日、周、月分段控制只位于“采集产出趋势”图内，默认按日显示最近 14 天，按周显示最近 12 周，按月显示最近 12 个月；柱形以接收和拒绝数据堆叠。右侧运行质量面板与趋势范围联动，展示成功率、成功/部分成功/失败分布和数据通过率；需要关注面板只保留最多三项人工动作。聚合接口最多读取 200 条 Run 与 Item 观测。

## 10. 验收

1. 用户从全部需求列表进入时默认新建需求，从具体需求筛选上下文进入时默认复用该需求并只补充采集入口 URL；两种模式可切换，系统逐项返回创建或拒绝结果，同批成功 Collector 共享稳定需求身份，任一合法 Source 可继续完成探索、审核、发布和立即运行。
2. `single` 原型明确展示直接采集与质量终结；`list_detail` 原型明确展示列表分页、detail URL 发现、详情抓取和质量终结。Run 完成后至少展示 3 个 accepted Item、1 个 rejected 候选、质量统计和一条可展开的完整 lineage。
3. 任一阶段的当前状态、阻断原因、下一步动作和证据在三秒内可识别。
4. `/`、`/collectors`、`/runs`、`/items`、`/settings` 可直接访问，品牌标识可从任意页面返回 `/`；主页待处理、运行和数据 Tabs 可通过鼠标与键盘切换。Collector、Run 与 Item 使用固定列运营列表；Collector 列表的状态和需求、Run 的状态和搜索、Item 的 Source、Collector、质量决定和搜索写入 URL，三个详情使用主卡与证据卡组，详情 URL 在刷新后恢复服务端状态。设置页可分别保存多个供应商与模型、切换唯一默认模型，并明确显示每个供应商的密钥解析状态。
5. Collector、Run、RuleVersion、RuleAttestation 与 Item lineage 使用同一冻结版本；新 Run 的完整性证据必须来自 API 固定事实，演示 Source、候选字段、Item 内容和 Source URL 必须属于同一场景。
6. 桌面 `1440x900` 与 `1280x800` 无文字溢出、布局重叠或不可达主操作；低于 `1280px` 的视口不属于验收范围。
7. Collector 详情的采集器定义与规则工作区在两种支持视口均可扫描和操作；需求归属与数据合同只读，名称修改保留活动规则状态，来源采集说明或入口修改使候选失效并提供保存后重新生成路径；直接规则编辑产生新候选 digest、清空旧审核决定并显示最近样本验证结果，已发布 RuleVersion 始终只读。
8. `pnpm api:generate`、`pnpm build`、TypeScript、lint、OpenAPI/异步合同测试和 GatherSpec Schema 测试通过。
9. 前端不包含 secret、真实签名私钥、内部对象存储 URL 或把客户端 tenantId 当作权限依据的逻辑。
