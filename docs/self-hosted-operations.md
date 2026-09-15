# 单组织自托管运维

适用范围是 [1.0 单组织合同](planning/v1.0-scope-matrix.md)：同一主机上的 API、Worker、MCP，共用 PostgreSQL 或 SQLite WAL、Artifact 目录、签名密钥和凭据加密 keyring。PostgreSQL 是自托管路径，SQLite 是本地评估路径。本文不宣称多租户、分布式 HA、任意站点兼容、月度 SLA 或灾备 SLO 已通过。

## 安装与配置

从源码安装采用 README 的 uv / Python 3.12 / pnpm 流程。每个进程必须使用相同的绝对配置路径：

```bash
export EXTRIO_INSTANCE_DIR="$HOME/extrio-evaluation"
export EXTRIO_DATABASE_URL=""
export EXTRIO_DATABASE_PATH="$EXTRIO_INSTANCE_DIR/extrio.db"
export EXTRIO_ARTIFACT_PATH="$EXTRIO_INSTANCE_DIR/artifacts"
export EXTRIO_SIGNING_PRIVATE_KEY_PATH="$EXTRIO_INSTANCE_DIR/keys/signing.pem"
export EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH="$EXTRIO_INSTANCE_DIR/keys/credentials.key"
export EXTRIO_SIGNING_KEY_ID=signingkey_local_dev_001
export EXTRIO_AUTH_ENABLED=true
export EXTRIO_API_PORT=8000
export EXTRIO_WEB_PORT=5173
./scripts/dev.sh
```

本机启动器在启动任何进程前检查端口；活动监听冲突直接失败，已关闭连接的 TIME_WAIT 不阻止重启。仅复用本实例 PID 文件指向的仓库进程；启动失败只停止本次新建进程。`./scripts/stop.sh` 使用相同 `EXTRIO_INSTANCE_DIR`，先停止本实例进程树；停止后的端口应不再监听。不要用全局 `pkill` 清理其他实例。

`EXTRIO_DATABASE_URL` 非空时优先于 SQLite 路径；PostgreSQL 示例为 `postgresql://<project-user>:<password>@<host>:5432/<empty-project-db>`。API/Worker/MCP 必须一起切换配置，不能只修改 API。凭据不得进入命令记录、截图或交接文档。测试使用独立的 `EXTRIO_TEST_DATABASE_URL`，不是业务库连接。

Docker 本地评估使用 `docker compose up --build --wait`；独立 PostgreSQL 评估使用 `docker compose -f compose.postgres.yaml up --build --wait`。两种配置是替代关系，不是覆盖叠加。API 默认仅绑定回环，Web 通过代理访问 API。共享持久卷包含数据库（SQLite）、Artifact 和 key；PostgreSQL 数据使用独立卷。普通停止使用 `down`，禁止把 `down -v` 当作停止或升级命令。

这份独立 PostgreSQL Compose 不适用于 maco；maco 必须执行其专用运维约束并使用已注册的共享 PostgreSQL、项目数据库和专用账号。生产部署需要 TLS、`EXTRIO_AUTH_COOKIE_SECURE=true`、非默认数据库口令、受控反向代理与受限 `/metrics` 访问。首次安装下载 Chromium 和系统依赖可能耗时，不能跳过浏览器依赖后宣称安装成功。

## Readiness 与升级

API 与 Worker 可以同时启动。数据库初始化使用独立串行门：SQLite 在首次连接/WAL 设置前取得同机文件锁，PostgreSQL 取得当前数据库的会话级 advisory lock，均覆盖迁移与补齐。锁随连接/文件描述符释放；不要删除正在使用的 `.migration.lock` 文件。

- `/healthz` 只证明 API 存活，不证明可以采集。
- `/readyz` 返回公开的 `ready` 布尔值；需要同库新鲜 Worker、所有新鲜 Worker 的代码/合同/共享配置摘要一致，以及已使用的密钥可用且可信。
- 登录后的 `/api/v1/runtime` 和设置的系统页展示原因、最多 50 个 Worker 标识、最后心跳、部署一致性、排队/执行数量和最老到期等待；不返回主机路径或 key 内容。心跳间隔 5 秒，20 秒失联阈值。
- `uv run --project backend extrio-doctor` 额外检查迁移、Artifact 目录权限、磁盘可用空间、未完成恢复标记及 PG 备份工具。只读、不初始化缺失数据库、不生成密钥；非就绪退出 1。

升级顺序：暂停计划并记录当前规则/任务状态，停止 API、Worker 和 MCP，完成全量备份；在隔离空实例演练恢复与升级；用同一版本启动 API 和 Worker，等待 readiness，再核对登录、历史字段/规则版本、Item 谱系、未终态 Operation 和 Delivery。启动执行带 ID 的数据库迁移。运行中的进程不会通过下一次心跳偷偷采用磁盘上新代码，因此修改代码/合同后应统一重启。不要只重启 API 并掩盖不匹配的旧 Worker。

迁移不提供原地向下撤销。回退采用相匹配的旧制品和升级前完整备份，恢复到空目标；不能把旧程序指向已升级业务库试运行。G4 单独记录发布候选、真实升级矩阵和回滚结论。

升级来源版本的备份能力必须先确认。仅支持数据库备份的版本（如 `86ebcc4`）需在全部进程停止后，使用该版本 CLI 备份数据库，并单独归档 Artifact、签名私钥、完整凭据密钥和必要配置；为整个集合生成并验证校验和，保留匹配的代码/镜像摘要。只保存数据库快照不满足回退条件。恢复时仅向空目标还原该集合，并用匹配来源版本验证登录、凭据、签名和历史结果；不得启动候选版本来生成“升级前”备份。

## 故障处理

| 状态或错误 | 操作 |
| --- | --- |
| `worker_unavailable` | 启动同配置 Worker，检查它实际连接的数据库；API 200 不代表 Worker 存活 |
| `worker_deployment_mismatch` | 停止旧部署的 Worker，统一制品、合同和共享配置；等待旧心跳过期再验证 |
| `credential_key_unavailable` | 停止写入，从匹配备份恢复完整 keyring；禁止生成新 key 覆盖已有密文 |
| `signing_key_unavailable/mismatch/not_trusted` | 核对当前 key ID、私钥权限、公钥注册和状态；按密钥流程处理，不绕过签名 |
| `restore_incomplete` | 保留失败证据，不启动、不直接删除标记；选择另一个空目标，从可信备份重新恢复 |
| `SOURCE_NETWORK_REJECTED` | 根据安全原因码确认入口、robots、状态码、主机或预算；不扩大授权/重试来绕过拒绝 |
| `JOB_CANCELLED/TIMED_OUT` | 核对终态与 Checkpoint；需要新采集时显式创建新 Run，不把旧运行改成成功 |
| `JOB_LEASE_LOST/ATTEMPTS_EXHAUSTED` | 检查实例/数据库和崩溃原因；过期 Worker 无提交权，不能重放其缓存结果 |
| Delivery 死信 | 核对 Sink 地址版本、凭据和接收日志后人工重试；保持 Delivery ID，接收端按它去重 |
| `EXPORT_TOO_LARGE` | 缩小过滤条件或分段读取游标；禁止静默截断后标记完整导出 |

来源适配器支持约 12 个固定本地样本覆盖的匿名 GET、HTML/JSON、single/list_detail、声明分页、同主机 iframe、异步 DOM 和编码/顶层跳转。未知 AccessProfile、静态认证 Header、POST/body、单独 request.query、WebSocket 和浏览器嵌套资源跳转明确失败；生产登录来源、凭据注入、跨站登录、验证码/封禁绕过不在已验证范围。JSON 的确定性规则执行有样本证据，不等于任意 JSON 接口的自动 AI 建模已经验证。

HTTP 与浏览器资源共用 DNS/IP/主机边界。限制采用已发布规则与运行适配器上限中更严格者；单响应解码上限 5 MB、HTTP 重定向上限 5、HTTP 尝试上限 3、请求并发上限 4，低于这些上限的规则预算同样生效。节流允许比声明 burst 更保守，不允许超出 rps。永久网络/授权拒绝不盲目重试。浏览器未捕获请求通过只拒绝的代理失败关闭，不直连外部网络。

三次连续失败暂停计划并记录审计；它是有限失败诊断，不是统计学习的全站漂移检测。重新探索、验证、审核和发布必须显式进行，不能静默修复已发布规则。取消/超时与来源漂移分开处理。异常展示不含原始服务器异常、内部路径或凭据。

## 数据与证据

Item 查询按稳定游标读取，单页最多 200。API 支持 observations/entities 视图及 Collector、Run、decision、entityKey、sourceHost、q 过滤，后续页使用返回的 `nextCursor`，不自行解码或修改。游标无效返回错误，不当作空页。导出最多 100,000 条并受字节上限约束；在完成检查后发送结果，不先返回半份成功文件。CSV 的列名和值防公式注入，JSONL 保留原始数据值。实测规模与环境见 [G3 记录](reviews/g3-2026-09-10/validation.md)，不是生产容量保证。

运行证据接口为 `/api/v1/runs/{runId}/evidence`。本地 `sampled` 保存有 digest 的有限 HTML 证据，`metadata_only` 不保存 raw；失败/取消的 manifest 标记不完整。完整性、缺失、过期、损坏均按真实状态展示。`sampled` 从不启用等价回放；当前本地适配器不提供完整 replayable 引擎，回放按钮保持禁用。

Worker 启动和每小时清理过期 manifest 所列的 raw 文件，保留 manifest 摘要；不删除无关文件或追随符号链接。此清理不是 Run/Item/Audit 元数据归档器。过期归档中的 raw 仍需按组织备份保留政策安全过期。证据包 ZIP 是规则/签名/运行/谱系导出，不是实例灾备包。

## 认证与密钥

本地角色为 administrator、engineer、reviewer、viewer；administrator 管理账号和配置，engineer 管理来源/运行，reviewer 审核发布，viewer 可读和导出。服务端检查权限，UI 隐藏不构成授权。首次管理员和最后一个启用管理员保护在双数据库事务内串行化。密码重置撤销会话，并阻止已验证旧密码但尚未建会话的并发登录；停用账号不能创建新会话。

单组织实例不实施 MFA/四眼策略。规则 attestation 使用实际发布 actor；提交批准和审核字段可以是同一主体，不虚构独立审核人。MCP stdio 信任本机进程，HTTP 使用独立静态 bearer token；MCP 不是某个 Web 用户的 RBAC 会话，持有它等同于获准使用其七个工具，包括创建来源和触发运行，但不包含发布工具。

所有私钥/keyring 文件必须是常规文件且限制为拥有者访问；禁止符号链接和宽权限。已有密文或已注册公钥时，密钥缺失/替换必须失败关闭。运维命令只在停止所有 API/Worker/MCP 后使用：

```bash
uv run --project backend extrio-keys initialize --offline
uv run --project backend extrio-backup /secure-backups/extrio-before-rotation --offline
uv run --project backend extrio-keys rotate-credentials --offline
uv run --project backend extrio-keys create-signing --offline --key-id signingkey_org_002 --output /secure-keys/signing-002.pem
```

`initialize` 用于尚无密钥的空实例，不会修复丢失密钥。凭据轮换先追加 key generation，再在同一数据库事务重加密已存 Sink/模型凭据并审计；旧 generation 保留，以便数据库失败回滚后仍可解密。不要手动裁剪 keyring，最多保留 100 代，接近上限应安排有完整恢复验证的维护。

签名轮换使用新 ID 和新路径。统一更新实例配置后，先由有权限的人重新审核/发布需要继续运行的规则，再退役旧 key：

```bash
uv run --project backend extrio-keys set-signing-status --offline --key-id signingkey_local_dev_001 --status retired
```

退役保留历史公钥和已有签名验证能力，但不能授权新的 Run。泄露时使用 `compromised`，不得降级恢复为 trusted；使用新 key 重新授权。保留历史公钥、审计和证据，不能通过改写历史规则或删除旧记录修复事故。

## 全量备份恢复

备份前暂停调度并停止全部 API、Worker、MCP；确认没有活动同主机锁或新鲜 Worker。崩溃 Worker 的心跳需要过期。全量包包含数据库快照、全部 Artifact 文件、当前签名私钥、完整凭据 keyring、配置身份及 SHA-256 清单。SQLite 使用一致快照，PostgreSQL 使用 `pg_dump` custom archive；容器附带 PostgreSQL 16 客户端。服务端版本不得高于备份客户端支持版本。

```bash
uv run --project backend extrio-backup /secure-backups/extrio-20260910 --offline
# 使用相同 tenant/key ID、正确数据库类型及全新的目标路径/空 PG 数据库
uv run --project backend extrio-restore /secure-backups/extrio-20260910 --offline
```

输出目录必须为空且在 Artifact 目录之外。恢复必须指向空数据库、空 Artifact 和空 key 路径，不能覆盖现有实例。恢复先验证清单与目标，整个过程中保留未完成标记；进程被强制终止后标记阻止启动。异常不覆盖已有目标。不要手动移除标记来“修复”半恢复实例。

校验和证明完整性，不证明归档来源可信；备份含私钥和解密材料，必须放在受控、加密的存储中，不得接受不可信归档。历史签名验证依靠数据库中的旧公钥/attestation，包内只包含当前签名私钥，不收集任意旧私钥目录。`--database-only` 明确不属于灾备，不能恢复丢失的 Artifact 或 key。

恢复后统一启动 API/Worker，检查 readiness/doctor、登录、历史字段版本、两代规则的签名、Item/Run 谱系、审计链、raw 摘要和凭据解密，再恢复计划与交付。RPO 取决于实际备份频率和故障点，RTO 包含下载、恢复、验证和人工操作；短暂本机恢复测试不能证明 15 分钟/4 小时等运营 SLO。

## API 与 MCP 客户端

浏览器 API 使用服务端 cookie 会话。下例省略首次设置，登录文件由运维安全提供，内容为 `username/password` JSON，不应提交到 Git：

```bash
API=http://127.0.0.1:8000/api/v1
curl --fail --cookie-jar /secure/session.cookies -H 'Content-Type: application/json' --data-binary @/secure/login.json "$API/auth/login"
curl --fail --cookie /secure/session.cookies "$API/collectors"
curl --fail --cookie /secure/session.cookies -X POST -H 'Idempotency-Key: client-run-unique-id' "$API/collectors/<collectorId>/runs"
curl --fail --cookie /secure/session.cookies "$API/operations/<operationId>"
curl --fail --cookie /secure/session.cookies "$API/items?collectorId=<collectorId>&limit=200"
curl --fail --cookie /secure/session.cookies -X POST "$API/auth/logout"
```

创建命令返回 202/Operation，不表示完成。网络响应不明时复用同一幂等键与同一请求，不新造键重复执行；业务冲突/权限拒绝不盲目重试。取消为 `POST /operations/{operationId}/cancel`，带幂等键；运行中先表示取消已请求，轮询到终态才算停止。新运行使用新键。限流遵守 `Retry-After`；排队和失败要查询实际 Operation，不以客户端超时认定服务器已取消。

MCP 与 API 使用同一组绝对环境配置；不能只传数据库路径而遗漏 Artifact/key 配置。`extrio-mcp --transport stdio` 面向可信本地客户端；HTTP 必须设置非空 `EXTRIO_MCP_TOKEN`，通过 TLS 代理后使用 `Authorization: Bearer <token>`，不能复用浏览器 cookie 代替它。标准链路为 `list_collectors → get_collector → trigger_run → get_run → query_items → get_item`；query_items 页上限 200，继续使用 nextCursor，完整 lineage 在 get_item。

真实 HTTP/stdio 示例脚本为 `scripts/g3-client-smoke.py`，只允许明确命名的本地 `g3-qa-*` 实例，创建手写固定规则，不调用模型。它不是生产数据初始化器，也不代表真实模型编译或外站验收。

## 持续观测

`scripts/observe-runtime.py` 仅创建新的 `g3-observation-*` 本地目录，运行独立 API、Worker、变更式本地来源和 HMAC 接收器；默认三来源、每五分钟计划、每分钟取样、72 小时到期。记录部署摘要、UTC 起止、进程 ID、样本间隔、运行/队列/Delivery、调度延迟和签名检查，不读取用户实例或调用真实模型。

`state.json` 是当前状态，`samples.jsonl` 和 `receiver.jsonl` 是原始证据。完成状态为 `completed_pending_analysis`，不是验收通过；进程退出、休眠造成的间隔、断网和失败不得用零值补齐。正常停止向 state 中的 supervisorPid 发送 SIGTERM，监督器只关闭自己启动的进程。G4 分析全部 72 小时证据、时间空洞和错误；影响结论的修复需明确是否重启窗口。
