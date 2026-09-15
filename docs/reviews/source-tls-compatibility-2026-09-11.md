# 来源 TLS 握手兼容修复

状态：Needs_Review。执行模式：局部直接修复；用户请求检查并修复候选规则生成失败。

## 范围

目标来源：`collector_ggzyfw_beijing_gov_cn_f4d99adb`。代码范围为 `backend/src/extrio/source_network.py`、`source_clients.py` 与对应网络/来源样本测试；同步运行合同。不改变来源定义、网络授权、规则发布或采集需求。保留工作区既有修改，不委派。

## 根因与修复

失败任务 `op_x_7319858b7bc148` 在 `fetching_list` 阶段返回 `SOURCE_NETWORK_REJECTED / source_connection_failed`，模型调用为零。独立复现捕获 OpenSSL 3.5.7 的 `SSL: BAD_ECPOINT`；同站点采用 P-256 或 X25519、保留默认 CA 与主机名校验时握手成功。

默认连接策略保持不变。仅 HTTPS 的 ConnectError 异常链包含精确的 SSL `BAD_ECPOINT` 原因时，采用 P-256 重试一次。兼容连接使用 HTTPX 默认受信 CA，保留 CERT_REQUIRED、主机名校验、最低 TLS 1.2、DNS 校验与 IP 固定、原始 Host/SNI、禁止环境代理、跳转检查、robots 和相同时间/字节预算。证书错误、其他连接错误不触发兼容重试；兼容连接失败不再递归重试。

一次 SourceNetwork 生命周期内仅对已成功完成兼容连接的同一主机/端口复用 SSL context，避免页面大量子资源反复进行已知失败的默认握手。缓存不跨任务、不跨主机共享；每次请求仍重新校验并固定目标地址。复用、跨主机与新任务默认策略有测试覆盖。

[OpenSSL 官方文档](https://docs.openssl.org/3.5/man3/SSL_CONF_cmd/)说明 3.5 默认 TLS 组与 keyshare 存在变更。该文档是兼容性调查背景；本次故障原因与修复效果以本机和目标站点的复现为依据，不断言站点设备型号或具体服务端实现缺陷。

实际生成重试 `op_c7f894c40a8944cf` 通过握手后暴露第二个阻断：页面脚本请求 `yhxw.tj.beijing.gov.cn` 的统计脚本及 `wza.beijing.gov.cn` 的无障碍脚本。它们不在来源允许主机中，网络层正确拒绝，但浏览器适配器将辅助资源失败误判成正文失败。适配器对站外 script/stylesheet/image/font/media 保持 abort 并记录类型与主机诊断；入口、iframe、XHR/fetch、同域连接失败等仍进入失败列表。没有扩大 allowedHosts，也没有增加代理、凭据或访问控制绕过。

## 验证

- TDD：新增成功重试及重试上限测试在修复前失败（2 failed / 21 passed），修复后通过。
- 最终网络套件 25 passed，包括证书校验保留、普通错误不重试、兼容连接失败上限与时间预算。
- 辅助资源反例先 RED（1 failed / 2 passed），修复后 3 passed，覆盖有效页面保留、跨域 XHR 及 iframe 仍拒绝，并核对被阻断 URL 未抵达本地服务器。
- 真实 URL 经 SourceNetwork 和 robots 检查返回 HTTP 200、28039 字节。
- 本地 API/Worker 在无活动任务时停止，SQLite 备份保存在权限 0600 的 `/tmp/extrio-before-tls-fix-20260911-0548.db`，随后启动最新代码；前端 5173 保持原进程。未自动发布规则。

- 扩展回归：网络、固定来源样本、运行、修复、任务恢复、探索、Worker、模型网关共 127 passed（70.83 秒）；追加主机/任务缓存隔离断言后网络套件仍为 25 passed。
- 实际最终生成：`op_x_2a964ab4428345` 为 `succeeded/completed`，AI 任务 `ai_run_x_98d28c554ddb4d539ded3621a2420d`；来源为 `ready_review`，存在 3 条预览样本，活动发布规则为空。浏览器实际进入规则审核页面，不再出现生成失败提示。
- 当前候选有一项真实审核阻断：可选正文 `content` 在样本中缺失。没有伪造正文、自动确认字段或绕过发布门，用户仍须审查该候选或继续修复字段选择器。
- API 与 Worker 一并加载最终代码，`/readyz` 返回 `ready: true`。代码变更后仅重启 Worker 会触发部署摘要不一致；最终启动已保持两者一致。未修改前端代码，也未重启原前端进程。
- 文档 manifest 校验与 `git diff --check` 通过。没有创建提交或宣称用户已验收。
