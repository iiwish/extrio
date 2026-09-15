# 数据列表页码分页

状态：完成。数据列表采用服务端页码分页，通用分页组件已接入真实前端。验收证据见 [分页验收](../reviews/items-numbered-pagination/verification.md)。

## IP-01 合同

- 范围：Item 列表、通用 ListPagination、API client、ItemPage/OpenAPI 生成类型、items GET/store 查询、中英文资源、相关测试及四份产品文档。
- API 兼容：既有 cursor/limit 调用保留；新增可选 page，与 cursor 互斥。服务端按同一实体归属、先最新再过滤、稳定排序及筛选条件计算总数，再 LIMIT/OFFSET 获取当前页。不在客户端累计所有页。
- 返回 pagination: page/pageSize/totalPages/total；超界页回落末页；空结果为第 1/1 页、0 行。每页 20/50/100/200，默认 50。查询属于实时视图，跨请求新增/删除可能移动记录，不承诺快照一致性或深 OFFSET 恒定耗时。
- 页码和 pageSize 写入 URL；筛选/页大小变化回到首页，刷新保持页码。加载/失败不把前一页冒充目标页；缺少分页元数据不伪造页数。导出继续使用筛选全集，不限当前页。
- 固定底栏显示范围/总行数、每页行数、页码/总页数与四个带 tooltip 的导航图标，可输入页码跳转；数字信息等宽，桌面1024及以上无控件重叠。
- 验证：后端页码/筛选/边界/游标兼容测试；前端替换而非追加、URL恢复、页大小、跳页、错误与空态测试；build/lint/OpenAPI同步；四桌面尺寸真实只读翻页。不执行采集、发布或数据库迁移。
