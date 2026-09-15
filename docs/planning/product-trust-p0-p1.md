# 产品体验成熟化 P0 / P1

状态：技术验收通过。P0 与 PT-01、PT-02、PT-03 均已完成；验证结果见 [交付验证](../reviews/product-trust-p0-p1/verification.md)，本轮验收见 [验收报告](../reviews/product-trust-acceptance-2026-09-14/review.md)。用户明确授权验收并在通过后继续 P2；外部用户可用性验证独立进行。本计划不包含 P2-P5。直接执行，不委派，不部署，不操作真实来源的发布、运行、迁移或调度。

## P0：范围与基线

核心用户是对持续数据需求负责的数据运营人员。代表任务是：从首页定位当前待办；判断需求字段是否落实到来源、来源是否自动更新；检查一次运行的结果与缺口并进入正确诊断。

2026-09-14 代码复核基线（本轮开始时已跟踪文件干净，已有 UX 审查目录未跟踪）：

| 发现 | 当前证据 | 处理 |
| --- | --- | --- |
| 首页与来源待处理集合不同 | home-page.tsx 纳入首次待运行，collectors-page.tsx 未纳入；各自维护分类 | PT-01 共用分类，覆盖归档、进行中、缺失记录与最新异常 |
| 需求发布状态不能回答对齐 | collection-page.tsx 默认字段页，版本对齐只在来源分区 | PT-02 顶部展示目标版本、未对齐及未知数量；不改默认分区 |
| 来源仅手动状态不突出 | CollectorOverview 不展示 schedule，SchedulePanel 已有真实配置 | PT-02 上提只读调度事实并链接原配置；不启用调度 |
| 成功暗示完整范围 | runs 中文筛选为“完整成功”，详情已有页数上限提醒 | PT-03 修正标签，保留停止原因与未确认范围说明 |
| 拒绝入口指向单条、网络异常引向规则 | RunPage 部分成功按钮取 rejected[0]，失败通用链接到规则 | PT-03 明确本次拒绝集合与未抓取数量，分别进入结果/执行诊断 |

已有能力：来源生命周期、人工迁移、持久运行、服务端实体分页及导出、历史归属、运行诊断、调度配置。不得重复实现。需求内业务数据工作区、业务字段查询、新鲜度目标、失败子集重试均不在本次范围。首次可信结果时间、独立完成率、恢复时长尚无外部用户基线，不编造数值；后续采用测试独立采集。

## 执行契约与依赖

所有任务共用本文件作为自包含 packet。需求依据为用户确认的分阶段方案、docs/product-contract.md、AGENTS.md 和 docs/reviews/product-ux-2026-09-14/audit.md。现有合同与版本、权限、幂等、历史归属约束优先，执行路径不可改变。

| ID | 范围与验收 | 依赖 | 允许文件 |
| --- | --- | --- | --- |
| PT-01 | 首页与来源列表同一输入得到同一待处理集合；仅最新运行影响判断；归档不进入待办；运行进行中不当成首次待运行 | P0 | web/src/features/home/*、features/collectors/collectors-page*、features/collectors/collector-attention*、相关 i18n |
| PT-02 | 目标版本与来源绑定分开，未知不等于对齐；归档来源不计活动对齐；仅手动/计划开启与下次运行在概览可见；只读入口不写数据 | PT-01 | web/src/features/collections/collection-page*、collection-alignment*、features/collectors/collector-page.tsx、collector-context.ui.test.tsx、相关 i18n 与 index.css |
| PT-03 | 成功不宣称全量完成；拒绝入口可访问本次拒绝集合，未获取与拒绝独立；访问/网络错误不默认要求修改规则 | PT-02 | web/src/features/runs/run-page*、runs-page.test.tsx、相关 i18n 与 index.css |

文档允许范围：本文件、docs/SSOT.md、docs/product-contract.md、docs/frontend-prototype.md、docs/releases/v0.2-acceptance.md、docs/reviews/product-trust-p0-p1/。不增加依赖，不修改 API/Worker/数据库。一次推进一个任务，不并行。

## Checklist 与分析

- [x] 用户要求覆盖 P0/P1，而非仅讨论；当前方案的执行已获明确授权。
- [x] 各项都有现有数据来源；未知、归档、只读和执行中须保持真实。
- [x] 新数据工作区与新增恢复能力排除；无自动运行/发布/迁移。
- [x] 验收能由单元/界面测试和实机只读走查复现。
- [x] 分析无阻断：不需要新 API；对齐仅使用需求详情的冻结绑定信息，不从字段覆盖率推断。

## 验证流程

每项先添加失败回归并运行 RED，再实现 GREEN，保留真实命令结果。完成后运行 web 中 pnpm test、pnpm build、pnpm lint、git diff --check；检查中英文键一致性。主流程在现有真实实例只读验证，四个桌面视口 1440x900、1280x800、1132x1028、1024x800；不存在的异常边界用隔离测试覆盖，不修改真实记录制造证据。截图与验证摘要写入 docs/reviews/product-trust-p0-p1/。

完成门：需求符合性、代码风险和浏览器 QA 均有证据；任何未验证项明确记录。工程完成与用户产品签收分开，不将测试通过标为用户已验收。
