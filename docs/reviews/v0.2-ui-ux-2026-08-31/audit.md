# Extrio v0.2 核心对象页面 UI/UX 审计

## 审计范围

- 视口：`1280x800`
- 页面：Collector、Run、Item 三个列表及三个详情页
- 数据：本地真实 API，包含北京政府采购意向首次与增量 Run

## 核心判断

1. Collector 列表把状态、下一动作和运行质量平铺为表格列，而且质量摘要来自静态文案，不能支持可靠决策。
2. Run 列表只强调 ID、页数和耗时，停止原因、增量模式、变更数量和恢复动作没有形成结果焦点。
3. Item 列表按 Run observation 重复展示同一实体；用户难以判断实际拥有多少规范化数据。
4. 三个详情页混用无边界区块、连续分隔线和单一卡片，主结果、配置与证据处于相近视觉权重。
5. evidence rail 逐行分隔，长标识符与关键业务结论争夺注意力；用户必须阅读整列才能理解对象是否可信。

## 设计决策

- 三个列表统一为双列对象卡片；卡片回答对象是什么、当前结果如何、下一步是什么。
- 顶部概览使用四张紧凑指标卡；筛选独立为一个工具卡，不与数据对象混排。
- Collector 卡片以真实最近 Run 计算健康和下一动作，不使用静态 accepted/rejected 文案。
- Run 卡片先展示接收、拒绝、变更和耗时，再展示执行模式、页面与停止原因。
- Item 列表按 `collectorId + entityKey` 聚合为最新实体，观察历史留在详情页。
- 详情页采用“对象标题 -> 结果或配置主卡 -> 内容卡 -> 证据卡组”的稳定层级；流程连接线只用于真实阶段和 lineage。

## 截图

### 改版前

- [Collector 列表](./before/01-collectors-list.png)
- [Collector 详情](./before/02-collector-detail.png)
- [Run 列表](./before/03-runs-list.png)
- [Run 详情](./before/04-run-detail.png)
- [Item 列表](./before/05-items-list.png)
- [Item 详情](./before/06-item-detail.png)

### 改版后

- [Collector 列表](./after/01-collectors-list.png)
- [Collector 详情](./after/02-collector-detail.png)
- [Run 列表](./after/03-runs-list.png)
- [Run 详情](./after/04-run-detail.png)
- [Item 列表](./after/05-items-list.png)
- [Item 详情](./after/06-item-detail.png)

## 证据边界

截图可以证明信息层级、卡片密度、文本容纳和页面溢出；键盘路径、焦点顺序、对比度计算和异步状态仍由自动化测试与人工交互 QA 验证。
