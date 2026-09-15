# 来源 URL 工作区

状态：实现与技术验证完成，待用户体验复核。用户明确要求来源以 URL 配置为重点，并授权在现有原型实现，不再生图。本任务直接执行，不委派；只覆盖来源页，不代表全部 P3 工作流获准实现。

## SU-01 执行契约

- 目标：普通来源详情默认采集配置，完整 URL 与编辑入口占主位；待审核默认审核，显式 section 深链接优先。
- 信息顺序：URL、采集说明与需求归属、更新计划和采集范围；规则技术配置及 Webhook 投递按需展开。运行结果与规则证据保持独立分区。
- 复用 DefinitionDialog、原 API、角色/归档/进行中锁定、revision 与幂等键。URL 变更不自动保存、发布、运行或启用调度。
- 允许文件：web/src/features/collectors/collector-page.tsx、collector-page.test.ts、collector-context.ui.test.tsx、collector-output.test.tsx；web/src/index.css；中英文 collector-detail.json；本文件、docs/design/product-maturity-p2/design.md、四份产品文档和 docs/reviews/source-url-workspace/。
- 前置：P0/P1 技术验收；用户确认 URL 优先的来源页方向并要求直接实现。既有工作树改动全部保留。
- 排除：新采集端点、认证配置、数据查询、候选证据关联、子集重试、部署和真实写入验证。

## 检查与验证

视觉合同：Standard 级既有产品页面优化；运营人员首先识别完整采集 URL。URL 工具使用白底、8px 圆角、#e4e9ed 单层边界、24px 内距；页面区域不套卡，更新与范围采用无分隔线的两列摘要，1150px 以下纵向排列。URL 15px 等宽、1.7 行高并允许任意位置换行，次级标签 12px，字距 0。复制提供成功/失败 live 状态，折叠项支持原生键盘交互与可见焦点。沿用品牌和 Lucide 图标，不添加图片、装饰动效或新技术栈。

- [x] 当前来源 URL、intent、Collection、schedule、policy 均有真实数据。
- [x] 首屏不重建表单或绕开保存合同；未知执行结果不改为成功。
- [x] 显式 section=overview/rule/config 深链接保留；待审核用户不被迫返回配置。
- [x] 修改 URL 的存储、规则失效和调度语义均不改；浏览器只读走查。
- [x] RED：默认分区、URL 首位、复制反馈、配置/规则分离测试，3 个预期失败。
- [x] GREEN：39 个测试文件、240 个测试通过；pnpm build/lint、中文英文 405 个键对齐。
- [x] QA：四种桌面视口无横向溢出；真实编辑草稿的风险提示与取消、规则和投递展开、运行结果与返回链接检查。长 URL 保真、只读/归档、失败重试与 pending 锁定由组件测试覆盖；未进行真实保存、运行或调度变更。

交付门：没有发现新增阻断；命令、截图与验证边界见 [验收记录](../reviews/source-url-workspace/verification.md)。运行锁定沿用既有逻辑，本轮没有新增真实运行验证。
