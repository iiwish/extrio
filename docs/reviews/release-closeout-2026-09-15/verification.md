# 发布闭环验收

## 范围与授权

用户于 2026-09-15 要求完成容器验收、真实模型小样本、发布提交与远程 CI，并明确不要求 72 小时观测。执行采用单个发布闭环工作包，直接执行；编辑范围为验收脚本、发现的发布缺陷与发布证据，保留本轮既有产品实现。72 小时门槛为用户豁免，不是验证通过。不打正式版本标签、不部署公网服务。

## 本地回归

- 启用独立 PostgreSQL 16 容器，运行 `EXTRIO_TEST_DATABASE_URL=... uv run --project backend pytest -c backend/pyproject.toml backend/tests -q`：682 passed，141.43 秒，无跳过。PATH 包含 PostgreSQL 16 的备份恢复工具。
- 前端 42 文件、262 测试通过，构建、lint 通过，见同日 [源码验收](../public-alpha-repair-2026-09-15/verification.md)。
- 本次源码和此前未跟踪的实现文件一起进入候选范围；运行时数据库、凭据、模型原始结果不进入提交。

## 真实模型小样本

使用主实例已配置的 `glm-5.3-flash`，端点主机 `open.bigmodel.cn`。仅只读获取默认模型配置，在独立临时数据库重新加密凭据；主实例对象未修改。临时数据库、密钥与网页制品在结束后删除。

来源：北京市政府采购网公开列表 `http://www.ccgp-beijing.gov.cn/xxgg/sjxxgg/A002004001index_1.htm`。

| 场景 | 结果 |
| --- | --- |
| 仅标题合同 | 模型反复给出空 `detail.fields`，Schema 拒绝；停止于 `MODEL_NO_PROGRESS`，未发布。不作为成功样本；首次脚本未捕获 Worker 异常，只有本次执行输出，无持久用量证据。 |
| 标题、详情 URL、正文合同 | `succeeded / candidate_ready / ready_review`，未自动发布；1 个任务尝试、6 次真实模型调用，耗时 47,623 ms。 |

成功样本实际用量：输入 29,519 tokens、输出 2,248 tokens、合计 31,767 tokens；价格未配置，成本未知。这不是两次样本的合计成本。

候选发现 14 个详情 URL，验证 3 个详情样本，接收 3、拒绝 0；21 项校验通过、0 警告。摘要：`sha256:e7f6235dfec5f65d3ecdc17b4a5c3635ec7b7bb13a34dcb5dae2b9970c084e1a`。列表标题可能含站点自身的省略号，不宣称恢复了原始完整标题。成功样本含对校验反馈的任务内修正，不是一次模型调用即成功。

本地原始证据位于被忽略的 `backend/data/release-real-model-20260915-full.json`。公开记录不复制网页正文、模型原始响应或凭据。可重跑入口 `scripts/verify-real-model.py --help`，必须显式授权真实调用，不加入自动 CI；最多一个探索任务，受产品的 16 次调用、240 秒任务预算约束。脚本复制主 Worker 的失败收敛行为，失败也落盘结果；不会自动重试任务或发布规则。

该小样本验证了真实供应商调用、合同拒绝及候选审核边界，不代表跨网站兼容率、供应商 SLA 或端到端生产稳定性。

## 发布检查

- 产品提交为 `8f0674f`，包括先前未跟踪的组件、样式和截图。在该提交的独立 Git worktree `/tmp/extrio-commit-check-20260915` 中，锁定安装、前端构建、隔离源码启动和固定规则首次采集全部通过。工作树快照不是这里的验证来源。
- Trivy 本地源码密钥扫描退出码为 0；远程该提交的密钥扫描与前端 CI 已通过。容器和后端 CI 结果以对应 Actions 记录为准。
- GitHub 暴露的可修复依赖告警分别收敛到 `js-yaml 4.3.2` 与 `qs 6.16.0`；前者上游固定旧版，采用精确版本 override，未进行全依赖升级。
- NLTK 未修复告警保留，调用链与功能暴露边界见根目录 `SECURITY.md`，不宣称依赖零漏洞。
- 正式标签与公网部署不在本轮范围。

## CI 环境与 TLS 修复

首次远程后端运行 `34921576976` 暴露 9 个浏览器测试失败和 2 个历史升级 fixture 错误：干净 runner 缺 Chromium，checkout 默认浅克隆缺历史基准。CI 安装 Chromium 及系统依赖，后端 checkout 使用完整历史；新增两个 CI 前置条件回归检查。缺历史配置的断言先失败，补齐后通过。

第二次运行 `34921896562` 为 683 passed、1 failed，剩余问题为 Linux 的 SSLContext 默认最小协议值。兼容重试显式采用 `max(已有下限, TLS 1.2)`，不改变证书、主机名、目标 IP 固定或单次重试约束。参数化测试覆盖系统最低值、TLS 1.2 和更严格的 TLS 1.3；系统最低值用例先复现失败。真实模型样本未使用这条 BAD_ECPOINT 兼容路径，无需重复付费调用。

远程容器运行 [34921577012](https://github.com/iiwish/extrio/actions/runs/34921577012) 和修复 PR 的 [34921896545](https://github.com/iiwish/extrio/actions/runs/34921896545) 均通过鉴权栈启动及前后端镜像扫描。扫描沿用仓库既有 `ignore-unfixed` 策略，不能据此宣称不存在 NLTK 等未修复依赖告警。

后续代码、检查状态与合并记录统一见 [PR #19](https://github.com/iiwish/extrio/pull/19)，不绕过失败门禁合并修复。

TLS 修复后的本地 `test_source_network.py`、`test_source_samples.py`、`test_ci_prerequisites.py` 合计 57 passed，27.55 秒；相关 Ruff 与 `git diff --check` 通过。

本机 ARM64 对 `7684960` 的最终容器验收退出码为 0：使用项目 `extrio-e2e-closeout-final-20260915`、端口 18100/18180 和独立镜像标签，从空卷启动 API/Worker/Web，完成 readiness、首次管理员、未登录拒绝、登录读取、退出后拒绝验证。脚本已删除该项目的容器、卷与网络，未影响 5173/8000 主实例。GitHub Linux 容器记录与本机 ARM64 记录分别成立。
