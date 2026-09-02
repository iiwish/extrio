# Extrio 安全与合规合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v0.7.0` |
| 对应产品版本 | `v0.2` |
| 状态 | `Ready_For_User_Review` |
| 权威来源 | [`SSOT.md`](./SSOT.md) 中的 `INV-004`、`INV-005`、`INV-007`、`INV-008` |
| 最后更新 | `2026-09-02` |
| 审批责任 | 技术负责人、安全负责人或承担安全职责的指定人员 |

## 2. 安全目标

Extrio 必须保护：

1. Tenant 之间的数据与执行隔离。
2. Source 和 Sink 凭据的机密性与最小授权。
3. 控制面、编译服务和 Worker 不被恶意网页或规则越权控制。
4. Source 访问符合法律、合同和租户授权。
5. 数据、规则、操作和交付具有完整审计与可验证谱系。
6. Artifact、日志和输出不会成为凭据、PII 或恶意内容的泄露渠道。

## 3. 信任边界

| 区域 | 信任级别 | 约束 |
| --- | --- | --- |
| 用户浏览器与外部 API Client | 不受信任 | 所有输入鉴权、授权、限量和 Schema 校验 |
| Python FastAPI 控制面 | 高信任 | 唯一领域写入入口；不得执行生产爬取或直接处理不必要的 secret 明文 |
| Python 编译服务 | 受限信任 | 可访问样本和 LLM；不得写生产领域状态或发布规则 |
| Python Worker | 受限、可丢弃 | 可访问固定 job 和短期凭据；不得访问 LLM 或控制面管理能力 |
| React Web 控制台 | 不受信任客户端 | 只访问版本化 API；不得持有服务凭据、签名私钥或把 tenantId 当作授权依据 |
| Redis | 不承载秘密 | 只保存任务引用、lease 和短期协调数据 |
| PostgreSQL | 权威元数据 | 行级租户边界、加密、备份和严格服务账号权限 |
| 对象存储 | 不受信任内容存储 | Tenant 前缀隔离、加密、生命周期、下载授权和内容类型防护 |
| Source 与网页内容 | 恶意外部输入 | 网络边界、大小限制、解析隔离、prompt injection 防护 |
| Kafka/Webhook Sink | 外部依赖 | 最小出站权限、签名、超时、幂等和响应脱敏 |

## 4. 身份与授权

公开 Alpha 的认证和会话以 [`architecture/ADR-005-local-authentication.md`](./architecture/ADR-005-local-authentication.md) 为准，使用单实例管理员、Argon2 密码哈希和服务端可撤销会话。多用户 OIDC、API token、独立服务身份与 Tenant 授权的生产目标以 [`architecture/ADR-004-identity-access.md`](./architecture/ADR-004-identity-access.md) 为准。

### 4.1 租户角色

| 操作 | TenantAdmin | CollectionEditor | RuleReviewer | Operator | DataConsumer | Auditor |
| --- | --- | --- | --- | --- | --- | --- |
| 管理成员与角色 | 允许 | 禁止 | 禁止 | 禁止 | 禁止 | 只读 |
| 管理 AccessProfile/Sink | 允许 | 仅引用 | 只读 | 只读 | 禁止 | 元数据只读 |
| 编辑 Collection/Source/Collector 草稿 | 允许 | 允许 | 只读 | 只读 | 禁止 | 只读 |
| 编译和样本测试 | 允许 | 允许 | 允许 | 允许 | 禁止 | 只读 |
| 发布、拒绝和回滚 RuleVersion | 需同时拥有 RuleReviewer | 禁止 | 允许 | 禁止 | 禁止 | 只读 |
| 管理 Schedule、取消 Run | 允许 | 禁止 | 允许 | 允许 | 禁止 | 只读 |
| validate_only 回放 | 允许 | 禁止 | 允许 | 允许 | 禁止 | 只读 |
| reprocess/redeliver | 需同时拥有对应审批角色 | 禁止 | 允许 | 发起但需审批 | 禁止 | 只读 |
| 请求租户数据删除 | 允许 | 禁止 | 禁止 | 禁止 | 禁止 | 只读 |

- API 必须基于认证主体、Tenant、资源和动作同时鉴权；前端隐藏按钮不构成授权。
- TenantAdmin 不隐式继承 RuleReviewer 或 Operator 权限；多角色用户必须分别满足每个动作的角色和 step-up 条件。
- 服务身份必须使用独立工作负载凭据，不得复用人类账号。
- 生产高风险操作必须执行 step-up authentication，并要求最近 10 分钟内完成 MFA 或等价强认证。
- 受保护 Collection 的发布、reprocess、redeliver 和批量删除采用四眼审批。

## 5. Tenant 隔离

- 所有数据库表、对象存储 key、队列 job、cache key、trace 和审计事件必须携带 tenantId。
- 数据库查询必须通过强制 Tenant scope；后台任务不得使用“缺省 Tenant”。
- 所有跨对象引用在写入时校验 Tenant 一致性，数据库应使用复合外键或等效约束。
- 对象存储使用不可猜测对象 ID 和 Tenant 前缀；下载只通过短期、单对象、只读授权。
- Redis key 必须命名空间化，job envelope 必须签名并校验 tenantId 与 runId 归属。
- 跨租户访问尝试必须拒绝、审计并触发安全告警，不得仅返回空结果掩盖服务端缺陷。

## 6. 凭据与 AccessProfile

### 6.1 支持类型

v0.2 支持 `none`、`basic`、`bearer`、`cookie`、`apikey` 和 `hmac`。AccessProfile 是稳定身份；每个 Active AccessProfileVersion 固定认证类型、精确 scheme/host/port/path scope、`header`/`cookie`/`proxy` 注入位置、Secret Manager 引用、代理引用和非敏感策略。注入位置不得为 URL path 或 query，任何版本对象均不得保存可用 secret 明文。

### 6.2 运行时注入

1. 控制面向 Worker 签发绑定 `tenantId + runId + accessProfileVersionId + audience` 的短期 job token。
2. Worker 使用 token 从凭据代理获取仅完成当前任务所需的 material。
3. material 只存在于 Worker 进程内存，在请求发送前注入，并在任务结束、取消或租约失效时销毁。
4. job token 和 material 不得写入 Redis、GatherSpec、Artifact、日志、错误消息、trace attribute 或 crash dump。
5. Worker 不得列举 Tenant 的其他 Secret，也不得获得 Secret Manager 管理权限。
6. 携带 AccessProfileVersion 的请求必须使用 HTTPS；每次 redirect 先移除凭据并重新验证 exact origin/path scope，禁止 HTTPS 降级和自动跨 origin 转发。

### 6.3 轮换与失效

- Secret 必须支持无规则变更轮换。
- AccessProfile 的认证类型、注入位置、origin/path scope、代理地域或权限范围变化必须创建新 AccessProfileVersion，并触发受影响 RuleVersion 重新验证。
- 禁用 AccessProfile 或撤销 AccessProfileVersion 必须阻止新 Run；运行中 Run 在下一次凭据读取或续租时停止。
- 每次生产凭据解析记录不含明文的 AuditEvent：actor/service、profileId、runId、结果和时间。

## 7. 出站网络与 SSRF 防护

- 所有 Source URL 和每次 redirect 必须使用结构化 URL 解析，不得通过字符串前缀判断域名。
- 只允许 `http`、`https`；存在 AccessProfileVersion 时必须使用 `https`，无认证的 HTTP 需要 TenantAdmin 显式批准并记录风险。
- 主机必须精确匹配 SourceRevision `allowedHosts`；不得使用 `*` 或不受控后缀匹配。
- DNS 解析前后都必须检查 IP，阻断 loopback、link-local、private、multicast、reserved、Unix socket 和云 metadata 地址，包括 IPv4/IPv6 与混合编码。
- 每次重定向先移除 Authorization、Cookie、Proxy-Authorization 和所有凭据 material，再重新解析 URL、校验 DNS/主机、阻断 HTTPS 降级并重新解析 AccessProfileVersion scope；默认最多 5 次。
- 禁止 Source URL 携带 userinfo、secret 或可用 token；AccessProfile 不得向 URL path/query 注入凭据。URL query 进入日志或 UI 前必须按键和值脱敏。
- Worker 网络策略只允许 Source 目标、凭据代理、控制面结果接口、对象存储和必要 DNS；不得访问 LLM、数据库管理端口或内部管理网络。
- Sink egress 与 Source egress 使用独立身份和 allowlist，防止采集内容改变交付目的地。

## 8. 编译服务与 Agent 安全

- 网页正文、Header、robots、脚本和嵌入数据全部是不受信任内容，不得作为系统指令执行。
- 发给 LLM 的样本必须与系统指令分离并标记为数据；页面中的“忽略规则”“泄露凭据”或工具调用文本一律视为内容。
- 编译 Agent 只能调用 allowlist 工具，且工具使用只读样本或受限 Source 请求；不得读取平台 Secret、其他 Tenant 数据或发布规则。
- 需要认证的 Source 请求由隔离的 sample-fetch Worker 使用 job-scoped 凭据执行；编译服务和 LLM 只接收去除认证 Header、Cookie、敏感 query 与内部网络信息的响应。
- Agent 输出必须先经过 JSON Schema、语义、安全与样本校验，不能直接成为 Published RuleVersion。
- promptVersion、toolchainVersion、provider、model、输入 Artifact digest 和输出 digest 必须进入编译谱系。
- 编译服务不得把 Source cookie、Authorization Header、PII raw 或内部 URL 发送给不符合 Tenant 数据处理要求的 LLM provider。

## 9. Worker 与浏览器隔离

- 每个 Worker 使用非 root、只读基础镜像、最小 Linux capability、内存/CPU/PID/磁盘限额和不可写系统目录。
- 浏览器上下文按 Run 隔离；默认禁用下载、扩展、剪贴板、摄像头、麦克风、地理位置、通知和持久化 profile。
- 运行结束必须销毁 cookie jar、local storage、cache 和临时文件。
- 页面 JavaScript 可以在受限浏览器中执行，但不能调用平台 API、访问内部网络或扩展 allowedHosts。
- 响应解压后体积默认不超过 20 MiB；必须防护压缩炸弹、无限流、超大 DOM、深层 JSON 和解析超时。
- v0.2 不执行下载文件中的宏、脚本或二进制，不提供通用文件扫描和内容执行能力。

## 10. 内容、Artifact 与输出安全

ArtifactManifest 的字段、digest、回放与 Header allowlist 以 [`contracts/artifact-manifest.md`](./contracts/artifact-manifest.md) 为准。

- `metadata_only` 不得持有响应正文，`sampled` 只能保存策略允许的有限证据，`replayable` 必须通过连续 chunk 引用每个响应的完整 raw/decoded bytes；只有后者可以授权证据等价回放。
- `rawRetentionDays=0` 的成功运行不得生成伪 `replayable` manifest；失败采样必须符合独立 capture policy、分类和保留期。
- Manifest、chunk 和对象引用必须逐级验证 tenantId、digest、object version、计数和序号，缺失或跨租户引用立即拒绝。
- `contentHtml` 按不受信任文本存储。管理界面展示前必须使用成熟 sanitizer，并在隔离上下文中渲染；默认优先纯文本预览。
- Artifact 必须记录 dataClassification；对外 Schema 使用 `internal`、`confidential` 或 `restricted`，公开 Source 内容默认仍按 `internal` 处理，除非 Tenant 明确允许公开导出。
- 包含凭据、session token 或被判定为不应留存的敏感 Header 时，采样必须在写入对象存储前脱敏或拒绝。
- 对象存储启用服务端加密；`Restricted` Artifact 应使用 Tenant 或环境隔离密钥。
- Content-Type、文件名和 Source Header 不可信；下载响应必须设置安全 Content-Disposition 和 `nosniff`。
- Kafka/Webhook 输出只能包含 CollectionVersion 允许字段和必要谱系；不得附带 raw Header、cookie、secretRef 或内部对象存储 URL。

## 11. 数据分类、保留与删除

| 数据 | 默认保留 | 最大常规保留 | 删除规则 |
| --- | --- | --- | --- |
| 成功 raw 样本 | 30 天 | 90 天 | 生命周期自动删除；延长需 TenantAdmin 批准 |
| 失败与验证 Artifact | 30 天 | 90 天 | 与事件关闭和合规要求共同决定 |
| HarvestItemRevision | Collection 存续期 | 由租户合同限制 | Collection 删除流程中清除，AuditEvent 保留摘要 |
| Run/Delivery 元数据 | 365 天 | 由租户合同限制 | 到期聚合或删除，不影响法定保留 |
| AuditEvent | 365 天 | 合规策略允许更长 | 只追加；禁止普通用户删除 |
| 采集任务临时凭据 material | 不持久化 | 不适用 | 任务结束立即销毁 |
| 模型供应商 API Key | 供应商配置存续期 | 不适用 | 删除供应商时同步删除加密凭据 |

- CollectionVersion 必须声明是否允许采集 PII、PII 类别、处理目的和必要性。
- `Restricted` 数据不得使用不符合 Tenant 地域和处理协议的 LLM、对象存储或 Sink。
- Tenant 删除要求 TenantAdmin 发起、step-up authentication、影响预览和延迟执行窗口；执行后 30 天内清除在线副本，35 天内从轮换备份中自然过期或完成受控清除。
- 法定保留或争议保全优先于普通删除，但必须限制访问并记录原因与截止时间。

## 12. 合法访问与反滥用边界

- 创建 Source 时必须记录租户对数据与访问方式具有授权，并选择适用依据：公开允许、合同许可、数据所有者授权或组织自有系统。
- 系统必须支持遵循 robots.txt 和站点条款的租户策略；不得将 robots 许可等同于完整法律授权。
- Extrio 不提供验证码破解、付费墙绕过、账号接管、credential stuffing、指纹伪造规避封禁或未经授权代理轮换。
- “站点指纹与反爬策略模板”仅允许表达合规 User-Agent、限流、缓存、正常浏览器兼容和封禁识别，不得绕过访问控制。
- 接到 Source 所有者的合法停止请求、滥用举报或授权失效通知时，必须能够按 Source、Tenant 和域名快速暂停。

## 13. 日志、审计与检测

- 结构化日志必须包含 requestId、tenantId、collectionId、collectorId、ruleVersionId、runId 或 deliveryId 中适用字段。
- 日志不得记录请求/响应正文、Authorization、Cookie、Set-Cookie、API Key、凭据密文、secretRef 完整路径、Webhook 签名或 URL 敏感 query。
- AuditEvent 至少覆盖：角色变化、AccessProfile/Sink 变化、发布、回滚、Schedule 变化、生产回放、重新交付、导出、保留策略和删除。
- AuditEvent 使用数据库不可变约束与周期性摘要链验证；导出审计记录必须包含完整性证明。
- 立即告警事件包括：签名失败、跨租户引用、越界 egress、异常凭据访问、批量拒绝、审计写入失败和生产规则绕过审批。

## 14. 加密、密钥与供应链

- 外部和服务间通信使用 TLS；生产不得关闭证书验证。
- PostgreSQL、Redis 持久化、对象存储和备份必须加密。
- RuleAttestation 私钥、JobEnvelope 私钥、Webhook 密钥和数据库凭据由受控密钥系统管理，按环境与用途分离并支持轮换；不同签名域不得共用 key。
- 模型供应商 API Key 必须使用独立主密钥加密落库；本地开发主密钥文件权限为 `0600`，生产由受控密钥系统注入和轮换。读取设置只返回配置状态，不返回明文或密文。
- RuleVersion digest 使用独立、追加式 RuleAttestation 证明；Worker 只持有验证公钥和信任注册表，不持有发布私钥。
- SigningKey 进入 `Retired` 后不得签发新证明；进入 `Compromised` 时按 `compromiseEffectiveAt` 使受影响证明失效，无法确定起点时使该 key 的全部证明失效。
- 密钥事故处置通过新 Trusted key 追加证明，不修改 GatherSpec；活动 Collector 在获得有效证明前暂停新 Run。
- 构建产物必须锁定依赖、生成 SBOM、执行漏洞扫描并使用可验证制品摘要部署。
- 高危或已知被利用漏洞在生产发布前必须修复；无法修复必须有负责人、补偿控制、到期日和明确风险批准。

## 15. 事件响应

1. 检测后立即保存不含 secret 的证据并确定 Tenant、Source、规则和 Worker 范围。
2. 可以按 AccessProfile、Source、Collector、Sink、Tenant 或 Worker pool 执行隔离和暂停。
3. 凭据疑似泄露时立即撤销与轮换，不等待根因分析完成。
4. 安全修复不得篡改历史 AuditEvent；通过新事件记录处置。
5. 恢复前验证 ruleDigest、RuleAttestation、SigningKey trust revision、租户边界、凭据权限和受影响数据完整性。
6. 按适用合同和法规完成通知、根因、影响和改进记录。

## 16. 安全发布门

以下任一问题存在时禁止生产发布：

- 可复现的跨租户读取、写入或执行。
- 凭据进入规则、URL、队列、日志、Artifact、ArtifactManifest 或输出。
- SSRF 可访问内部、metadata、loopback 或未授权主机。
- 未经 RuleReviewer 即可发布或回滚规则。
- Worker 可以访问 LLM、Secret 列表、控制面管理 API 或其他 Tenant 数据。
- 回放可在无额外授权时写生产 Sink。
- 未经 sanitization 即在管理界面执行 Source HTML。
- AuditEvent 可以被普通服务身份修改或删除。

安全证据必须包括 Tenant 隔离测试、OIDC/CSRF/step-up 测试、SSRF 与 redirect 凭据测试、secret 扫描、RBAC 测试、浏览器隔离测试、RuleAttestation/密钥事故测试、回放副作用测试和依赖扫描报告。
