# Extrio 项目完成度与运行检查

检查时间：2026-09-06，Asia/Shanghai。检查对象：`6a62925` 加当前全部未提交与未跟踪实现，不是仅检查 HEAD 或某个 PR 的增量。

## 结论

Extrio 已有真实前后端实现，是可自托管的 v0.6 Public Alpha，不是纯界面原型。核心模块已有自动化覆盖，但不能认定“前后端全部完成、功能全部正常”或“生产验收通过”。当前存在已复现的数据浏览、导出和增量分类缺陷，以及实际运行环境和验收覆盖缺口。

## 已确认问题

### P1：增量分类漏掉空值与零值、布尔值之间的变化

- 位置：`backend/src/extrio/worker.py:63-78`。
- `_revision_values` 返回真实字段值后，比较逻辑用 `value or ""` 归一化，把 `None`、`0`、`False`、空字符串以及空容器混为一类。
- 独立调用真实 `classify_items`：前一条 `extractedData={budget: null, active: null}`，后一条 `{budget: 0, active: false}`，两个字段都列入 fingerprintFields；实际输出 `unchangedItems=1`、`changeType=unchanged`、`revision=1`、空 changeSummary。
- 影响：真实字段变化不增加 Revision，并被 `DELIVERABLE_CHANGE_TYPES` 排除，不进入更新 Webhook 交付。
- 修复方向：按类型保留原值比较，只对确实等价的缺失值执行显式归一化；补充 null/0/false/空数组/空对象的分类和交付回归测试。现有分类测试未覆盖这类假值边界。

### P2：数据页静默丢弃第二页以后的实体

- 位置：`web/src/api/client.ts:297`、`web/src/features/items/items-page.tsx:25-41`。
- `api.items()` 只读取 `/items?limit=200` 并丢弃 nextCursor；ItemsPage 在这一个观测页面中合并实体、搜索和生成筛选选项，没有翻页或继续加载入口。
- 当前真实 API 共 431 条观测、158 个不同的 `collectorId + entityKey`；前 200 条只覆盖 112 个实体。浏览器显示 112 条，因此 46 个实体无法通过正常数据列表检索。
- 影响：旧数据并未删除，但用户无法从列表发现它们；来源筛选选项也可能缺失。概览的 200 条聚合限制是另一个已声明口径，不能作为数据检索页静默截断的理由。
- 修复方向：提供实体级服务端分页与筛选，或正确遍历分页并明确加载边界。现有组件测试使用少量 fixtures，未覆盖第二页实体。

### P2：“导出当前筛选的数据”与屏幕筛选语义不同

- 位置：`web/src/features/items/items-page.tsx:35-58`、`backend/src/extrio/store.py:1551-1566`。
- 屏幕关键词匹配标题、正文、来源名和 entity key；导出却把同一关键词作为精确 entityKey 传入，且不提交站点域名 source 筛选。
- 浏览器搜索“中国医学科学院”显示 4 条；请求页面实际采用的导出参数 `format=jsonl&entityKey=中国医学科学院` 返回 HTTP 200，但为 0 条记录。
- 影响：用户得到空导出，或在只按站点域名过滤时导出范围过大。当前前端测试没有证明导出内容与可见筛选一致。
- 修复方向：共享查询合同，使关键词、来源、质量决定和实体/观测口径一致；在 API 和 UI 两层断言实际导出记录。

### P2：PostgreSQL 验收测试并非全绿

- 位置：`backend/tests/test_store_pg.py:104-105`。
- 默认后端测试跳过全部 16 项 PostgreSQL 测试。额外启动独立 PostgreSQL 16 测试容器后，结果为 15 passed / 1 failed。
- 失败为 `test_migration_002_applies_to_v05_database_without_the_row`：没有 ORDER BY 的 schema_migrations 查询返回 `000,001,003,002`，断言要求 `000,001,002,003`。
- 这是已定位的测试顺序依赖，不是已证明的数据库迁移失败。修复测试后仍需重新跑 PostgreSQL 验收，不应把此前跳过等同于通过。

## 当前运行环境

- `http://127.0.0.1:5173` 提供当前 Vite 前端，代理 `127.0.0.1:8000` 本机 Python API；健康检查返回 ok。
- `/api/v1/auth/state` 返回 `authEnabled=false`，当前访问者为 Local Administrator。因此本次实际页面不能证明登录和角色隔离工作正常；相关行为由开启鉴权的隔离测试覆盖。
- 检查时没有本机 extrio-worker 进程。Docker 中虽有 extrio-worker，但其数据目录来自独立命名卷 `extrio_extrio-data`，不是本机 `backend/data`，不能把它算作当前 Vite/API 的执行进程。
- 本机数据库有 39 个 completed job、11 个 failed job，没有排队任务；7 个定时计划均关闭。为避免修改业务数据或触发外部请求，本次没有启动本机 Worker、启用调度或对现有来源提交采集/AI 修复命令。当前环境的后台执行链路不应认定为正在正常运行。
- 现有 24 次运行的历史状态为 13 成功、9 部分成功、2 失败。最近保存的中央政府采购网运行发现 19 个详情、抓取 11 个，2 条接收、9 条拒绝。它是历史运行事实，不是本次对第三方站点重新验收的结果，也不能将每次拒绝视为系统缺陷。
- 默认模型与密钥配置状态可读取；未读取密钥明文，未发起付费模型调用。真实供应商连通性、余额、当前站点兼容性不在本次已验证结论中。

## 功能完成边界

| 能力 | 当前判断 |
| --- | --- |
| 独立需求 CRUD、归档恢复、字段草稿 | 前后端已实现；隔离测试通过，实际页面可读取和进入编辑后取消 |
| 来源创建、CSV/TXT 导入、需求关联 | 已实现，API/组件测试覆盖；本次未向用户数据库导入记录 |
| AI 规则生成、人工审核发布、证明验证、AI 修复 | 已有实现和测试；不是本次真实供应商端到端验收 |
| 确定性采集、增量、质量门、调度 | 已实现并有真实本地 HTTP Runtime 测试；增量分类有上述缺陷，本机执行进程缺失 |
| 数据浏览、版本谱系、CSV/JSONL 导出 | 已实现；浏览和导出存在上述已复现缺陷 |
| Webhook、重投、签名证据包、MCP | 后端及适用的 UI 已实现，有专项自动化；未向外部收件端实际交付 |
| 用户与角色、模型及凭据设置 | 已实现；隔离鉴权测试通过，当前本机实例关闭鉴权 |
| 需求字段模板、真实 AI 字段建议、字段版本发布、来源迁移 | SSOT 明确列为后续实现；保存草稿不改变新旧来源的实际采集合同 |
| 外部 OIDC/MFA、多租户、Redis/S3/KMS 生产组合、HA/SLO/容量验证 | 不应作为当前 Alpha 已完成的生产能力；参见 ROADMAP、README 和生产目标合同 |

## 本次验证

| 检查 | 结果 |
| --- | --- |
| `uv run --project backend pytest backend/tests -q` | 223 passed / 16 skipped，81.66s；跳过项为 PostgreSQL |
| 独立 PostgreSQL 16：`pytest backend/tests/test_store_pg.py -q -ra` | 15 passed / 1 failed，40.55s；临时容器已停止并移除 |
| `pnpm --dir web test` | 29 files / 115 tests passed；jsdom 有两条 document navigation 未实现提示 |
| `pnpm --dir web build` | TypeScript 与 Vite 构建通过 |
| `pnpm --dir web lint`、后端 Ruff | 通过 |
| `python scripts/update-docset-manifest.py --check`、`git diff --check` | 通过 |
| OpenAPI 重新生成到临时文件并与 `schema.d.ts` 比较 | 完全一致，未改写生成文件 |
| 独立 Compose 构建与 `scripts/verify-compose.sh` | 通过；验证未登录 401、首次管理员设置、认证访问、Web 可用、退出后 401；不等同于完整 AI/采集闭环 |
| 浏览器连接真实 API | 概览、需求列表/详情、字段编辑后取消、数据检索/详情、运行列表/详情、来源概览/规则/配置、系统/模型设置、新建来源页可打开；所检页面未捕获 console error/warn |
| 桌面视口抽查 | 1440x900 需求详情、1280x800 运行详情、1132x1028 系统设置、1024x800 新建来源；不是全部页面与状态的完整视觉验收 |

1132px 系统设置页观察到 document.scrollWidth=1144 的 12px 溢出，截图中关键控件仍可见。该项仅记录为待复查的轻微布局现象，不与核心数据正确性缺陷混淆。

Compose 验证使用独立项目 `extrio-audit-20260906`、API 18400、Web 18480 和独立 audit 镜像标签，没有重启既有实例或覆盖 local/e2e 镜像。脚本退出后已移除该项目的三个临时容器、网络和数据卷。PostgreSQL 验证使用独立临时端口 55448，不连接其他项目的数据库。Docker 构建缓存和 audit 镜像仍保留。

浏览器视口切换后的一次点击偏移误关闭了“允许匿名 HTTP 来源”。已通过真实 API 恢复为检查前的 true 并复核，设置更新时间因此发生变化。未对用户的需求、来源、规则、运行、数据或凭据进行修改。没有修复业务源码或改写既有未提交工作。

## 建议顺序

1. 修复增量分类、数据分页和导出语义，并添加能复现当前问题的回归测试。
2. 统一要使用的本机或 Compose 环境，确认 API/Worker 共享数据库与 Artifact，恢复安全的鉴权配置。
3. 修复 PostgreSQL 测试断言，补足生产数据库上的新增需求/字段生命周期验收。
4. 在独立验收数据上执行新的来源接入、模型生成、人工审核发布、首次与增量运行、交付和重启恢复闭环，再决定 Alpha 验收结论。
5. 单独排期实现字段草稿发布等剩余产品能力，不以现有 CRUD 完成替代这些能力。
