# 通用列表工作区验收

日期：2026-09-14。范围：LW-01。结论：技术验收通过，等待用户体验复核。

## 实现边界

ListWorkspace 统一工具栏、数量、通知、滚动区域和可选分页尾栏。需求、来源、运行、AI 任务、数据五个列表视图使用同一组件。业务行、查询、筛选、角色权限和写入动作保留各页面所有权，没有新增依赖、端点或第二份原型。

100dvh 与 flex 剩余空间分配负责高度，不绑定路由像素常量。只有包含 ListWorkspace 的 app-column 使用有界高度；其余详情保持文档滚动。表头在列表内吸顶，横向和纵向滚动共用同一容器。筛选重置纵向位置，分页与刷新不重置位置。

## 验证

- RED：共享组件测试在组件尚未创建时出现 import-resolution 失败，未将其记作行为断言失败。
- GREEN：`pnpm test`，40 files / 244 tests passed。包含数量未知/部分加载/陈旧状态、固定插槽与滚动区域边界、筛选重置、分页保持位置、需求刷新失败保留记录；既有过滤、排序、英文内容、权限、分页与导出回归通过。
- `pnpm build`、`pnpm lint`、`git diff --check` 通过。测试环境有两条既有 jsdom 跨文档导航提示。
- 20 个页面/视口组合均满足 document.scrollWidth = viewport.width、document.scrollHeight = viewport.height。列表高度随工具栏换行和窗口变化，无主页面横向溢出。完整数据见 [视口数据](viewport-checks.json)。

## 视觉与交互

| 页面 | 主视口 | 最小桌面 |
| --- | --- | --- |
| 需求 | [1440](collections-1440.png) | [1024](collections-1024.png) |
| 来源 | [1440](collectors-1440.png) | [1024](collectors-1024.png) |
| 运行 | [1440](runs-1440.png) | [1024](runs-1024.png) |
| AI 任务 | [1440](runs-ai-1440.png) | [1024](runs-ai-1024.png) |
| 数据 | [1440](items-1440.png) | [1024](items-1024.png) |

另保存各页 1280x800、1132x1028 截图。需求列表为单行说明摘要、72px 左右行高、浅色行边界、完整名称/合同 title。选择器、搜索、刷新和主动作保留在顶部，低宽度时工具栏有序换行，列表相应缩短。

滚动验证中，来源 scrollTop 到 102px、运行到 1294px、AI 与数据到 2400px 时，工具栏和表头位置保持不变，document.scrollY 为 0。宽运行列表局部 scrollLeft 达 318px，document.scrollX 为 0。键盘 Home 聚焦列表区域并返回顶部。截图：[来源](collectors-scrolled.png)、[运行](runs-scrolled.png)、[AI](runs-ai-scrolled.png)、[数据](items-scrolled.png)、[横向](runs-horizontal.png)。部分交互截图属于同轮微调工具栏间距前的状态，最终首屏布局以各视口截图为准。

数据页使用真实只读请求验证追加分页：50/358 → 100/358，scrollTop 保持 1600px，尾栏按钮始终在滚动区外。不触发采集、发布、导出或写入。需求明细实机检查 list-workspace 数量为 0，app-column overflow 为 visible，app-main display 为 block。

## 残余边界

需求实例仅 6 行，在支持尺寸内无需纵向滚动；长列表能力由共用容器在其他三个业务列表中的真实记录验证。未进行超大数据量虚拟化、200% 缩放或屏幕阅读器专项验收，未做英文浏览器截图；移动端不在范围。技术通过不等于目标用户已接受视觉效果。

设计者自评：25/28，平均 1.79，Pass with concerns。产品适配、任务信号、设计主张、滚动边界、层级、字体、桌面布局、内容真实性、合同一致性、配色和状态处理各 2；视觉表达、细节交互、动效各 1。优势是清晰、统一的固定操作面与列表滚动边界；仍保留各业务行的既有信息结构，未声称全站视觉重构完成。
