# ADR-004：身份认证与访问控制

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| ADR 版本 | `v1.1.0` |
| 状态 | `Proposed_Production_Target` |
| 对应产品版本 | `v0.2` |
| 决策日期 | `2026-08-30` |
| 决策责任 | 技术负责人、安全负责人、产品负责人 |
| 关联要求 | `FR-014`、`NFR-008`、`NFR-013`、`INV-004`、`INV-007` |

## 2. 决策

Extrio 的多用户、多租户生产形态采用外部 IdP + OIDC/OAuth 2.0 授权码和 PKCE 认证人类用户，采用短期服务端会话访问 Web 控制面；服务间通信采用独立工作负载身份和 mTLS。`v0.2` 公开 Alpha 的单实例管理员认证由 [ADR-005](./ADR-005-local-authentication.md) 定义，不宣称已经具备本 ADR 的多租户授权、MFA 或工作负载身份边界。

租户授权由 Extrio 控制面基于 Membership、角色、对象租户归属和高风险操作策略执行。身份认证成功不等于具有任一 Tenant 权限。

TenantAdmin 管理租户、成员和策略，但不隐式继承 RuleReviewer 或 Operator。发布/回滚必须同时具有 RuleReviewer，生产 reprocess/redelivery 必须具有对应审批角色；服务端逐动作授权，客户端隐藏按钮不构成安全边界。

## 3. 人类会话

- OIDC 必须校验 issuer、audience、nonce、state、PKCE、签名、时间和授权响应绑定。
- 回调只接受预注册精确 redirect URI；禁止 wildcard redirect。
- 浏览器使用 `Secure`、`HttpOnly`、`SameSite=Lax` 的随机不透明 session cookie；session material 只在服务端保存摘要和状态。
- 状态变更请求必须使用同源检查与 CSRF token；CORS 使用显式 allowlist 且不与 wildcard credentials 组合。
- 默认空闲超时 30 分钟、绝对时长 12 小时；IdP 账号禁用或 Membership 撤销后最长 5 分钟内阻断新请求。
- 发布、回滚、凭据查看/变更、生产回放、重新交付、成员提权和删除要求最近 10 分钟内完成 MFA step-up 或等价强认证。

## 4. API 与服务身份

- v0.2 的个人 API token 由 TenantAdmin 显式创建，使用至少 256 bit 随机值，只显示一次；数据库只保存带服务端 pepper 的哈希、前缀、scope、tenantId、actor、过期时间和 lastUsedAt。
- API token 必须具备最小 scope、最长 90 天有效期、可独立吊销，不能绕过四眼审批或 MFA 限制的高风险命令。
- 服务采用短期工作负载凭证和 mTLS，身份绑定环境、服务、audience 与用途；禁止共享长期静态服务密钥。
- 编译服务、Worker、Delivery worker、调度器和发布服务使用不同身份；只有发布服务可请求 RuleAttestation 签名。

## 5. 授权与租户边界

- API 在读取对象前先确定 tenantId，再校验 Membership、角色、对象归属和动作策略。
- 客户端提交的 tenantId 只作为请求目标，不作为可信权限上下文；可信 tenantId 来自授权解析结果。
- 数据层启用 tenant scoped query guard；高风险表使用 PostgreSQL RLS 或等价防线，后台任务也必须携带 tenant context。
- 列表、搜索、错误、指标、对象存储签名 URL 和审计查询不得泄露其他 Tenant 的对象存在性。
- 权限拒绝使用稳定错误码并产生安全遥测；高风险拒绝与角色变更写入 AuditEvent。

## 6. 备选方案

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 本地密码体系 | 仅公开 Alpha | ADR-005 以受限的单管理员边界支持自托管评估，生产多用户形态仍采用外部 IdP |
| 浏览器持有长效 JWT | 不采用 | 吊销、泄露窗口和 XSS 风险更高 |
| 人类与服务共享 API token | 不采用 | 无法清晰区分 actor、用途和最小权限 |
| 仅应用层 tenant filter | 不采用 | 单点遗漏会造成高影响跨租户泄露 |

## 7. 后果与验收

- 部署必须配置受支持 IdP、issuer/audience allowlist、会话密钥轮换和 break-glass 流程。
- 自动化测试必须覆盖 login CSRF、OIDC mix-up、过期/吊销会话、跨租户 IDOR、角色撤销、step-up、token scope 与服务 audience。
- 安全测试必须证明客户端伪造 tenantId、对象 ID、forwarded header 或 trace context 不能提升权限。
- 身份提供商不可用时，现有未过期会话可按策略继续；不得降级到本地密码或跳过高风险 step-up。
