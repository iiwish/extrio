# G3 验证记录

状态：工程回归完成，持续观测启动单独见 [观测交接](observation.md)。技术复核见 [Review](review.md)；用户最终产品签收与 G4 发布验收独立。

## P15–P18：恢复边界

运行以数据库 job attempt + 租约作为提交权威。成功事务包含 Run、Items、Collector 运行字段、Checkpoint、Operation、Webhook outbox 与 job 完成标记。终态提交失败全部回滚；过期 attempt 的结果、进度与错误不能覆盖接管者。普通 job 最多领取三次，过期恢复耗尽后清理持久化资源。运行中取消先持久化请求，再停止异步工作并提交取消；Worker 退出保留可接管租约。运行按冻结规则的时长预算中止，取消/超时不推进 Checkpoint。

Worker 启动时固定代码/合同/关键共享配置摘要，通过同库心跳报告存活。`/healthz` 仅为存活；`/readyz` 要求存在新鲜 Worker 且所有新鲜 Worker 的部署摘要一致；认证后的 `/api/v1/runtime` 给出有限诊断，不返回文件路径或凭据。

Delivery 使用独立随机租约 token；投递前和原子落库前校验所有权。单次领取一个事件避免批次尾部租约过期。历史 attempt 数与当前重试周期独立，手动重投保留 Delivery ID、历史记录和审计，重新获得有限重试预算。接收器版本改变时旧事件进入死信，不静默改投新地址。响应正文不下载；错误记录不包含原始网络异常文本。

### RED

- `test_job_recovery.py` 初始四个反例失败：过期接管后旧 Worker 仍提交；outbox 异常后 Run 已成功；取消端点 404；三次恢复后继续领取。修正测试 fixture 后再次确认 outbox 原子性 RED，非无效样本造成的假失败。
- `test_result_preserves_concurrent_collector_settings` 失败：采集过程中操作员修改的名称被旧快照覆盖。完成事务改为合并任务拥有的结果字段。
- `test_delivery.py` 三个反例失败：旧响应覆盖新租约；旧事件静默改投新接收地址；手动重投被历史重试上限立即打回死信。
- `test_runtime_health.py` 三个测试因诊断/心跳模块缺失失败。

### GREEN 与实进程

- 初步 SQLite job/Worker 回归：31 passed，7.64s。
- 心跳/job/Delivery 聚焦回归：25 passed，9.15s。
- SQLite/PostgreSQL job/心跳与 PG Store 套件：39 passed，23.66s。
- SQLite/PostgreSQL 真实子进程强制终止及八路并发领取：4 passed，8.01s。测试只强制终止自己创建的子进程；崩溃前数据库保留 running，无 Items/outbox；租约到期接管后恰好一个 Item、一个 Delivery、一个成功 Checkpoint；迟到错误/重复队列记录不能重开成功运行。
- PostgreSQL 环境：本机专用 `extrio-g3-pg-test`，`postgres:16-alpine`，仅监听 `127.0.0.1:55446`，每用例新建并删除独立数据库。没有连接 maco 或用户业务库。
- 扩展双数据库全套：386 passed、1 failed，61.39s；唯一失败为平台设置测试的迁移列表未包括 007。更新该断言后该文件 9 passed，0.75s。完整最终回归、前端控制、四桌面 QA、运行手册与本阶段最终 review 尚未完成。

## P11–P14：来源与网络

固定语料位于 `backend/tests/fixtures/sources`，catalog 声明 12 个样本：静态 single、列表 next-link、页码分页、JSON 列表详情、同主机 iframe、异步 DOM、GB18030、同主机跳转、越界跳转、robots 拒绝、403、错误登录页。全部仅在临时回环 HTTP 服务运行，不访问外站或真实模型。

HTTP 继续使用 Crawlee 的公开 HttpClient 扩展接口。连接前解析并检查所有 DNS 结果，拒绝非全局地址（仅显式开发配置允许 loopback），随后连接到已校验 IP 并保留原始 Host/TLS SNI。每个重定向重新检查主机/地址，HTTPS 不降级。无环境代理、Cookie 或认证信息注入；解析后的字节累计受页面和全程预算约束，gzip/deflate 使用有输出上限的标准解压器。robots 使用同一个受限连接入口。参考：[Crawlee HTTP clients](https://crawlee.dev/python/docs/guides/http-clients)、[HTTPX TLS extensions](https://www.python-httpx.org/advanced/extensions/)。

Chromium 由 Crawl4AI 管理；页面、iframe 和 XHR 等请求在上下文路由中通过同一个受限 HTTP 入口获得响应。浏览器底层配置只拒绝、不转发的本机代理，未被路由捕获的请求不能直连来源；WebSocket 拒绝。真实浏览器保留异步 DOM 等待，来源结果仍由字段/列表规则验证，短小 iframe 的结构启发式失败不代替真实 HTTP 状态和提取结果。参考：[Crawl4AI hooks](https://docs.crawl4ai.com/advanced/hooks-auth/)。

未知/过期 AccessProfile 引用、静态认证 Header、POST 均明确拒绝，不能被忽略后当成匿名成功。当前运行适配器不提供登录、凭据注入、验证码或访问限制绕过。首个列表页无记录是结构失败；页面获取不到不能形成成功的空 single。网络/结构异常连续三次失败也会暂停调度，暂停在锁内读取最新配置并留下审计；取消、超时不冒充来源漂移。

### RED 与 GREEN

- 14 个网络边界反例初始因模块缺失 RED，实现后 14 passed。
- 固定语料首轮 11 passed、2 failed（9.48s）：Crawl4AI 将真实短小 iframe/异步页按字数判为 anti-bot。限定处理其结构启发式后，12 个语料和跨主机 XHR 负例 13 passed，9.67s。未关闭 robots、主机限制或真实访问拒绝检查。
- gzip 解码和来源异常触发调度暂停两个反例 RED；修复后 2 passed，1.59s。
- SQLite/PostgreSQL Worker/job、来源网络/语料、运行和修复聚焦回归 97 passed，31.72s。
- 三个未支持授权/方法反例先确认仍然发送请求并成功；修复后 3 passed，2.04s，拒绝发生在任何网络请求之前。
- 有限 HTTP 重试发现恢复成功仍被旧错误覆盖，已加入回归并修复；最终全套继续记录。

### 最终网络反例

规则声明的更低重定向、单响应大小、尝试次数、并发和 rps 限制实际生效。构造器参数与节流测试先 RED；真实样本验证 maxRedirects=0、16 字节响应上限、maxAttempts=1 和永久 403 不重试。浏览器顶层跳转先由受限入口跟随，再加载最终地址，避免 Playwright 对重定向请求不再次路由造成兼容性漏口；不支持的嵌套资源跳转明确失败。

robots 对每个跳转目标在请求前检查，限制目标从不被访问。HTTP 和浏览器的相对字段 URL 都基于最终地址；两个测试通过 monkeypatch 负向控制把 make_item 地址改回入口后均按预期失败，移除负向控制后通过。网络/来源/运行聚焦 49 passed、18.77s，后续两个相对字段测试 2 passed、2.66s。全部纳入最终 497 项回归。

## P20：实测规模

数据形状：100,000 observations、20,000 entities、每实体五个 revision，正文约 1,000 字节。新增 008 实体排序索引；窗口排名只排序 ID，再读取有效 payload。Worker 只读取本批 entity 的最近已接受 revision。测试先反证缺索引和全量历史扫描；CSV/JSONL 从同一 spooled snapshot 验证条数/字节后输出，反例覆盖两次查询之间变更导致遗漏。

| 指标 | SQLite | PostgreSQL 16 |
| --- | ---: | ---: |
| observations 首屏中位数 | 1.90 ms | 14.66 ms |
| entities 首屏中位数 | 621.23 ms | 921.61 ms |
| entities 首屏最大值 | 663.59 ms | 1780.73 ms |
| 完整游标遍历 20,000 entities | 13.738 s | 23.211 s |
| 读取导出 100,000 行 | 0.902 s | 1.744 s |

原始结果：[SQLite](scale-sqlite.json)、[PostgreSQL](scale-postgresql.json)。SQLite 优化前 entities 中位数约 3.208s、完整遍历 95.177s，见 [负载对照](scale-sqlite-before.json)。两种数据库测试有重叠运行，数据为本机样本，不是独占资源 SLO；PG 普通客户端 cursor 仍可能缓冲结果，不声明恒定内存导出。

端到端本地抓取基线使用 `scripts/benchmark.py --collectors 3 --pages 2`，SQLite、macOS 26.5.2 arm64、Python 3.12.13，六次实际成功，42 页（18 列表、24 详情）、24 accepted、0 rejected、12 new、12 unchanged。遵守冻结速率后 wall 22.09s、p50 3.57s、p95 3.58s，约 114 pages/min、65 items/min。未遵守速率的早期结果不作为容量结论。外站、模型、并发用户和生产硬件尚无容量结论。

## P21：证据与保留

`test_local_evidence.py` 覆盖 sampled 摘要、缺失/损坏、过期、metadata_only 与 raw 清理；清理反例先 RED。每个 job attempt 有独立目录，DB 中保存 manifest digest；失败/取消只产生不完整 manifest。保留清理只删除清单列出的过期 raw，保持 manifest 和无关文件，不跟随 symlink。

质量页使用实际 evidence 接口，删除固定 100% 网络检查及所有终态均完整的暗示。sampled 始终不能等价回放，缺失/不完整/过期均不得启用按钮。真实 API/MCP Run `run_x_2bb772c186c242` 成功，7 个 sampled 文件、3940 校验字节；`canReplay=false`，不是完整 replayable 证据。

## P22–P23：权限、会话与密钥

- 双数据库八路首次管理员创建、并发禁用最后管理员反例先 RED；事务串行化后仅一个初始化者、至少一个启用管理员。
- 密码重置撤销全部会话；旧密码验证与 session 创建之间插入密码重置，SQLite/PG 均先出现错误 200。事务内检查预期密码摘要与 enabled 后，两个反例及认证/用户/恢复 26 项通过（5.62s）。
- 未登录读取导出/证据/取消返回 401；viewer 可读导出但取消返回 403；过期会话无效。CSV 公式前缀及列名七个反例先 RED，修复后通过，JSONL 不修改原值。
- Worker 未知异常只存稳定类别，不把异常原文中的路径、userinfo 或 token 返回给用户。签名审核主体从实际发布 actor 取值，双数据库断言先 RED 后通过；不宣称双人审核。
- `test_key_operations.py` 验证 keyring 追加、重新加密、历史解密、丢失 key 不生成替代品、私钥权限、注册身份不匹配、退役后历史签名仍可验证和不可逆 compromised 状态。`extrio-keys` 受同主机离线排他锁保护。
- 轮换先保留旧 key generation，再提交密文/审计事务；失败回滚不丢解密材料。备份包含完整 keyring 和当前签名私钥，历史公钥与签名留在数据库。

### 测试隔离风险

既有 conftest 仅清除 DB URL，部分 TestClient lifespan 使用默认本地开发库并执行待迁移。只读核对发现该库已有 007/008 迁移记录；未回滚或删除其数据，不能声称此前每次套件都完全没有接触默认库。已新增 `test_test_isolation.py` 反例，并在导入应用前强制设置临时 DB/Artifact/两类 key 路径，全套结束后清理自己的临时目录。后续 484 项及最终 497 项全套使用隔离配置；PG 用例仍只使用本包 55446 端口的专用实例。

## P24：一致备份恢复

`test_full_backup.py` 在 SQLite/PG 空目标恢复数据库、Artifact、签名私钥和 keyring，核对两代不可变已签规则、固定字段版本、Run/Item 谱系、凭据、审计链与 raw digest。真实 SQLite CLI 子进程执行 backup/restore；另外在 raw 复制后 `os._exit(99)`，未完成标记持续阻止实例启动。PG 使用真实 pg_dump/pg_restore，客户端 16；SQL restore 单事务，拒绝非空目标。

负例涵盖不可信路径、symlink、文件损坏、已有目标、活动实例、部分写入失败；只清理本次创建目标。阶段性完整备份测试 9 passed、4.37s，相关 Store/CLI 及最终全套通过。同主机共享卷锁不约束未知旧进程或外部 SQL 客户端，停写是显式运维前提。没有生产 RPO/RTO 证明。

## P25–P26：安装与交接

Docker SQLite 和 PostgreSQL 两次最终安装分别使用 `extrio-e2e-g3-sqlite-final`、`extrio-e2e-g3-pg-final` 独立项目。真实 build、API/Worker/Web（PG 另含 DB）healthy；readyz、首次设置、带 cookie 读取、Web 页面、logout 后 401 全部通过。脚本自动删除自己的新容器和卷，不采用现有实例。镜像包含 PG16 备份客户端及 Chromium。

安装反例发现 Artifact 未初始化导致 Worker health 失败，增加启动目录初始化并验证；doctor 只读检查仍不创建缺失实例。本机脚本端口冲突先 RED 后通过，TIME_WAIT 重启反例通过。实际只重启 Worker 暴露 macOS Bash 3 的空数组 nounset 错误；新增有效 RED，修正空端口列表分支，四个启动器/观测测试 4 passed、8.35s，实际 Worker 恢复就绪。

真实客户端脚本运行 HTTP cookie 登录与 MCP stdio 的七工具发现，list/get collector、trigger/get run、2+2 唯一 Item 游标、get_item lineage、证据以及 logout 后 401 通过。脚本使用本包手写固定规则，不调用模型。最终 Run `run_x_2bb772c186c242`。本机 `extrio-doctor` 返回 ready=true、1 Worker、0 queued/processing、无待迁移、Artifact writable、备份工具可用。

API/OpenAPI 与生成类型、四份主产品文档和 [运维手册](../../self-hosted-operations.md) 对齐真实限制、恢复命令、权限、幂等键和密钥流程。高级多租户/全回放/分布式运行文字由 1.0 适用边界约束，不冒充当前实现。

## 桌面 QA

本机独立 QA API 8028、Web 5188，真实登录、真实 Worker，不使用 MSW。截图为中英文代表性状态，而非完整跨语言全站矩阵：

- [中文系统 1440x900](runtime-zh-1440x900.png)、[中文最小桌面 1024x800](runtime-zh-1024x800.png)。
- [英文系统 1280x800](runtime-en-1280x800.png)、[最终英文证据 1132x1028](evidence-final-en-1132x1028.png)。
- [真实 Worker 停止](worker-unavailable-en-1024x800.png) 后 UI 显示 unavailable、0 workers，API readyz=503；[重启恢复](worker-recovered-en-1024x800.png) 为 1 Worker、deployment matches、ready。
- [排队运行取消](cancelled-en-1024x800.png)：按钮实际提交取消，Run `run_x_0dc2a701595045` 为 cancelled，刷新保持终态，无 Items/交付且 Checkpoint 不变。
- [真实 404 失败](failure-en-1280x800.png)：Run `run_fdce6ad83e72409a` 显示 source response failed、http_status_404，[质量页](incomplete-evidence-en-1280x800.png)为不完整证据、回放禁用。

截图人工检查无水平溢出、文字遮挡或布局跳变。G4 仍需全链路及完整中英文四桌面矩阵。

## 最终回归

- `EXTRIO_TEST_DATABASE_URL=...127.0.0.1:55446/... uv run pytest -q`（backend，PG16 工具在 PATH）：498 passed，97.21s，包含最终启动器修复；前一轮为 497 passed，93.87s。
- `pnpm --dir web test --maxWorkers=1`：最终 173 passed，37.49s，36 个测试文件；前一轮同为 173 passed，63.76s。
- `pnpm --dir web build`、`pnpm --dir web lint`、`pnpm --dir web api:generate`：通过。
- docset manifest 更新及 `--check`、`git diff --check`、三个 shell 脚本 `bash -n`：通过。
- 观测 harness 的短时实际 API/Worker/HMAC 接收验证通过，结束后自己的 API 端口关闭；真实 72 小时窗口已启动，20:30 首周期完成后 6 Run 成功、6 Delivery 到达、3 次计划派发、0 无效签名。完整结果由 G4 分析，不用短测试代替。
