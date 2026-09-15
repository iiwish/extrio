# H001 修复验证

日期：2026-09-06。范围：当前工作树的增量修复，不撤销既有修改，不提交 Git，不重算或回写历史业务结果。

## 缺陷与处置

| 问题 | 修复 | 验证 |
| --- | --- | --- |
| P1 假值混淆导致 Revision / 更新交付遗漏 | 使用已有 JSON canonical 表达比较，保留类型；变化摘要保留 0、false、null 和容器 | 9 组类型变更、数值/键序等价、实际 Delivery 入队回归 |
| P2 观测前 200 条截断造成实体遗漏 | 服务端先取最新实体再筛选，UI 游标分页，真实 total 与全局 facets | SQLite/PG 超过 200 条、同 key 不同来源、最新拒绝不被旧接收替代 |
| P2 列表搜索与导出不一致 | API/客户端共用 view、q、sourceHost、collectorId、decision 等筛选 | 搜索字面 `%`/`_`、第二页、导出完整结果和顺序、旧 entityKey 精确语义 |
| P2 PostgreSQL 测试依赖无排序结果 | schema_migrations 查询显式 ORDER BY id | 原有测试保留，独立 PG16 专项测试 17 项通过 |
| 本机无同库 Worker 且关闭登录 | 使用 scripts/dev.sh 启动原生 API/Worker，启用认证，复用已运行的 Vite | Worker 日志记录真实本机 DB，API 拒绝匿名数据请求，页面要求首次管理员设置 |
| QA 发现最小桌面视口导出被挤出 | 搜索区弹性收缩、结果数量不拆行 | 四种桌面视口截图与 DOM 几何检查 |
| 停止脚本可能误杀 PID 复用后的无关进程 | PID 正整数检查及仓库命令归属校验；开发端口使用 strictPort | 真实无关 sleep 进程和非法 PID 回归，bash 语法检查 |

## RED / GREEN

- Worker / Item query 新增测试在实现前：12 failed、16 passed；失败覆盖假值分类、交付和缺失实体 total。
- Items UI 新增测试在实现前：3 failed、3 passed；失败覆盖导出参数、继续加载和读取失败反馈。
- stop.sh 回归在实现前：无关 sleep 进程被 SIGTERM，测试失败；修复后进程保留，过期 PID 文件清除。
- 核心后端定向测试：`pytest backend/tests/test_worker.py backend/tests/test_item_query.py backend/tests/test_api_output.py -q`，36 passed。
- PostgreSQL 专项：`EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_test@127.0.0.1:55448/postgres uv run --project backend pytest backend/tests/test_store_pg.py -q -ra`，17 passed。使用独立临时 PG16 容器，不使用用户业务库。
- 后端最终全量：`EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_test@127.0.0.1:55448/postgres uv run --project backend pytest -q -ra`，257 passed、无 skip，含 17 项 PG 专项和 4 项脚本 PID 安全回归。
- 前端全量：`pnpm --dir web test --maxWorkers=1`，29 files / 117 passed。第一次默认并发运行有 2 个既有 Collection 测试超时/未在等待窗口内结束；未删除、跳过或放宽断言，单 Worker 全量重跑通过。测试调度对机器负载的敏感性仍需 CI 持续观察。
- 最终构建：`pnpm --dir web build` 通过，包含最新工具栏 CSS；前端 lint、Ruff、OpenAPI 生成、文档 manifest 与 diff whitespace 检查通过。
- 最新 CSS 后的 Items/合同/fixture 定向前端回归：4 files / 15 passed。

## 真实本机只读复核

复核入口为 `http://127.0.0.1:5173`，代理原生 API `127.0.0.1:8000`，数据为 `backend/data/extrio.db`。浏览器通过 CUA 操作真实页面，不使用 MSW。为完成现有开发环境的只读检查，先以其原有 auth-disabled 设置重启新版 API；检查结束后再启用登录。没有新建管理员、改密码、启用定时采集或对外调用模型/采集站点。

- 数据库 431 条观测，对应 158 个最新实体；API `view=entities&limit=200` 返回 158 条、total=158、cursor=null。
- 浏览器初始 50 条，继续加载至 100、150、158；最终 DOM 有 158 条 Item 链接，计数为 158，加载更多消失。
- `q=中国医学科学院`：列表 4 条，JSONL 导出 4 条，ID 与顺序完全一致。
- 叠加 `sourceHost=www.zycg.gov.cn&decision=accepted`：浏览器 3 条，并触发真实 JSONL 导出；同一数据库 Store 查询与导出均为 3 条、ID 完全一致，参数合同由 UI 与后端测试共同核验。
- 四种视口的截图已在本次任务工具记录中显示并检查。最终宽度/页面 scrollWidth 分别为 1440/1440、1280/1280、1132/1132、1024/1024；工具栏动作区右边界均在父容器内。宽数据表保留自身水平滚动，不要求最小视口同时显示全部列。临时 viewport override 已 reset。
- 启用认证后 `/api/v1/auth/state` 返回 authEnabled=true、setupRequired=true、authenticated=false；`/api/v1/items` 未登录返回 401；`/healthz` 返回 status=ok。
- 浏览器显示“创建管理员 / 完成此实例的首次设置”。账号和密码由用户填写，测试不会替用户接管实例。
- Worker 启动日志：`Worker started; database=/Users/iiwish/self/extrio/backend/data/extrio.db`；原生 API 与 Worker 使用同一仓库配置和 Artifact/密钥路径。
- 修复后复查：39 completed / 11 failed jobs、0 个启用的定时任务、0 个用户、431 条观测，均与启动 Worker 前一致。

## 剩余边界

- 本次不执行历史 Revision/Delivery 回填。历史漏判需要单独的无副作用核对与受控补偿方案，不能直接重发业务事件。
- 不把启动 Worker 等同于重新证明真实站点或模型闭环；本次没有调用外站或消耗供应商额度。
- API 的实体分页不是跨请求快照；持续写入时 UI 对已加载实体去重，刷新取得最新状态。大规模索引、快照导出与首页全量聚合属于 1.0 规模验证范围。
- 字段版本发布、来源迁移、模板和独立 AI 字段建议仍未实现。完整 1.0 范围及任务估算见 `docs/planning/v1.0-delivery-plan.md`。
- 当前运行入口是原生开发栈。机器上既有 Docker 业务栈未被修改，其 volume 不与原生数据库混用；本次临时 PostgreSQL 验证容器在验证结束后清理。
- 工程验证通过不代表已获产品 Accepted，最终签收由用户决定。
