# G4 集成验证

日期：2026-09-11。状态：本地工程 Needs_Review；P28、P31 和产品签收 Pending。所有写入均针对本包独立实例，未部署、提交或调用真实模型。

## 集成旅程

P27/P29：SQLite 与 PostgreSQL 均通过真实鉴权 UI 完成登录、新需求、字段保存和发布、来源接入、候选审核和人工发布、Webhook 配置、运行、投递、结果与 CSV/JSONL 导出。API、Worker、数据库、HTTP 来源、HTTPS 模型协议和签名接收器均为真实进程；模型内容是明确标记的合成 fixture，不能计入 P28。

| 数据库 | 最终 Run | 结果 | 本地证据 |
| --- | --- | --- | --- |
| SQLite | `run_x_4fbac1512ec048` | succeeded；当前运行完成签名投递 | `backend/data/g4-qa-20260911d/browser-journey.json` |
| PostgreSQL | `run_d13ff994464540f0` | succeeded；1 次签名投递 | `backend/data/g4-qa-pg-20260911b/browser-journey.json` |

接收器核对 HMAC、Content-Digest 与 Idempotency-Key，未发现无效签名。SQLite 证据目录含三轮独立来源的三次成功投递，不能将其计为本轮重试或真实模型样本。Run 持久状态和 CollectionVersion 绑定经 API 交叉核对；下载文件实际解析，不只检查按钮出现。

重跑入口为 `scripts/g4-qa-instance.py` 和 `scripts/g4-browser-qa.py`。前者拒绝复用已有根目录、创建自有测试库并在退出时清理；测试登录材料与浏览器会话保存在本地私有文件，不能纳入候选制品或提交。独立 QA 服务最长四小时退出，不属于长期部署。SQLite 验收入口为 `http://127.0.0.1:5198`，PG 为 `http://127.0.0.1:5199`；账号材料在对应实例目录的 `login.json`，仅本机文件拥有者可读。

## 升级与回退

`backend/tests/test_release_upgrade.py` 从 Git 基准 `86ebcc4b570f8b5b5acf3f1c6ba0f70ac7ed42f7` 导出真实旧代码，在独立 SQLite/PG 库创建 000–003 迁移历史、两版签名规则、来源、运行、数据、登录会话、加密 Sink 凭据和 Artifact。当前代码初始化两次后逐项核对历史与审计，并证明发布新字段版本不会偷偷重绑旧来源。

回退使用旧 CLI 的数据库备份，加单独归档的 Artifact/密钥，恢复到空目标并用匹配旧代码读取；前后元数据完全一致，归档文件逐项核对 SHA-256。没有执行数据库原地降级。另以两个同步启动的真实子进程验证空 SQLite/PG 库的迁移与回填互斥。

## 桌面体验

P30：每个数据库五个页面（需求、来源、运行、数据、设置）× 中英文 × 四个桌面视口，共 80 次页面测量及 80 张截图；另有各库审核与读取错误截图。视口为 1440×900、1280×800、1132×1028、1024×800。页面错误数为零，document 横向尺寸均未超出视口。审核弹窗 Escape 关闭后焦点回到发布按钮；真实设置页切换语言；一次受控读取 503 显示错误，恢复请求并刷新后持久数据保持。

设计约束：沿用单一真实前端和密集桌面控制台，不改变导航或视觉体系，不引入移动端范围。人工抽看主视口审核、最小视口英文需求/运行、中文数据与设置，确认标题、状态、操作与表格无明显重叠。几何检查不是完整 WCAG 审计，不声称已做屏幕阅读器认证。

截图与结果位于上述两个目录下 `screenshots/`。`review-zh-1440.png` 显示真实提取样本、1 个验证样本与 1/1 字段覆盖；`collection-en-1024.png` 显示已发布字段而非未应用草稿。

## 回归与构建

- 前端全量：36 文件、177 测试通过；lint、API 类型生成和生产构建通过。
- 后端最终全量：`backend/.venv/bin/pytest backend/tests -q`，504 passed，616.79 秒，无跳过；设置了独立 `EXTRIO_TEST_DATABASE_URL` 和含 PostgreSQL 16 CLI、uv 的 PATH。
- 新增升级、打包、fixture 与 QA 脚本执行局部 Ruff 检查；现有文件中不相关的历史 lint 项不纳入本包清理。
- `uv build --project backend` 产出 sdist 和 wheel。打包测试从 sdist 构建 wheel，检查合同、迁移、LICENSE/NOTICE，解包后在仓库资源之外导入并初始化 Store。
- Docker 双数据库安装、镜像标识、最终全量结果及制品摘要见 [候选清单](release-candidate.md)。

## 未完成门槛

当前本地服务入口统一为 `http://127.0.0.1:5173`，使用原主实例数据与账号，配套 8000 API 和单个 Worker。5178/5188/5198/5199 验收实例及 Docker 测试服务已按用户要求停止。上述截图/结果继续作为历史验收证据，旧 QA URL 不再在线。PG 临时验收库停止前归档至 `backend/data/g4-qa-pg-20260911b/stopped-instance.dump`；其他实例文件保留。72 小时观测在 2026-09-11 10:56 主动停止，完整持续观测仍 Pending。

P28 仍待本次外站/模型调用确认，未复用 G2 单次授权；合成模型无真实供应商成功率、用量或成本结论。P31 真实 72 小时窗口最早于 2026-09-13 20:26（Asia/Shanghai）结束，当前 G3 冻结进程的稳态证据不能证明 G4 候选所有新字节经过 72 小时验证。2026-09-11 10:28 本地读取样本显示已运行约 14 小时、507 Run 和 507 Delivery 成功、504 次调度派发、签名错误 0、队列积压 0、1 个匹配 Worker，最大派发延迟 6.253 秒；此处仅为中途快照。详见 [观测范围](../g3-2026-09-10/observation.md)。正式发布与产品 Accepted 均未通过。
