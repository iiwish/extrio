# 1.0 稳定版收尾执行包

## 授权与边界

任务 STABLE1，High 风险，Governed Delivery。2026-09-27 用户确认稳定版收尾，允许修改、测试、提交、推送和创建 PR。稳定版发布须在验收结果与安全结论后再次确认；禁止合并新 PR、创建 v1.0.0 tag、运行 release 发布、发布镜像或部署生产。RC 的 NLTK 风险接受仅适用于 RC，不延伸至稳定版。

基线 main / 已发布 v1.0.0-rc.1 为 c2fc06f420c31aaf5bbbea53332ef4af2b48804e；工作树干净。工作分支 codex/v1-stable-closeout-20260927。范围沿用 docs/SSOT.md、docs/product-contract.md 与 docs/planning/v1.0-scope-matrix.md；不新增平台能力、不重做 UI、不扩大来源/真实模型调用预算。72 小时观测沿用既有豁免，不计为通过。

## 执行分析

- RC 已发布，main CI 与双架构扫描、签名和溯源通过；旧规划/交接中的未发布文字需要校准。
- NLTK 3.10.3 的 GHSA-8mgp-746c-j5xp 无修复版本，静态未见调用不是完整不可达证明；补动态负向验证并明确残余风险，不关闭告警或放宽扫描。
- 稳定版需要元数据、RC 到稳定版双库升级/恢复证据，以及对已发布镜像按摘要安装的真实验证，不能由本地 rebuild 冒充已发布镜像验收。
- 所有数据库、容器、目录和端口可归属。用户 PostgreSQL 18 与其他项目服务不改动。临时 PostgreSQL 16 专用于验收。

## 单任务并行工作流

三个执行尝试 parallel=true，文件写入不交叉。宿主协作策略启用并行代理；不得继续委派、回退其他人的修改、提交或操作远程 Git。主代理负责集成、完整验证和 PR。

| 尝试 | 所有权与允许修改 | 成果与验证 |
| --- | --- | --- |
| STABLE1-Security | backend/tests/test_nltk_boundary.py；必要的专用验证脚本；本目录 security.md | 核实公告与调用边界，实际受限浏览器/运行路径动态探针、负向路径输入验证；只添加边界测试，不 monkeypatch 生产运行或私自卸载依赖；提出风险结论 |
| STABLE1-Release | backend/pyproject.toml、backend/src/extrio/__init__.py、backend/uv.lock、web/package.json；backend/tests/test_release_upgrade.py、fixtures/release_baseline.py、test_release_package.py；scripts/verify-compose.sh 及专用测试；本目录 release-validation.md | 1.0.0 未发布元数据、实际 RC 基线升级/恢复测试；支持不重建的 digest-pinned Compose 验证并测试参数拒绝/默认兼容 |
| STABLE1-Docs | docs/SSOT.md、product-contract.md、frontend-prototype.md、planning/v1.0-*、releases/v0.2-acceptance.md、releases/v1.0-rc.1.md、releases/v1.0.0.md、releases/v0.7-upgrade.md、CHANGELOG.md、backend/tests/test_docset_authority.py、scripts/update-docset-manifest.py | 最新发布状态与未发布稳定版边界，收敛验收矩阵，不改历史审计记录；manifest 最终由主代理生成 |

## 测试与复核

行为/脚本变化先加反例并观察 RED，再最小修复及 GREEN；新增验收覆盖可直接证明既有行为，不伪造缺陷。安全探针必须证明检测装置能识别一次受影响 API 调用，再证明实际应用路径不触发；不把单条路径外推成全应用安全证明。

完整验证：后端 SQLite + 独立 PG16 全量、前端测试/lint/build、Ruff、OpenAPI 类型一致性、manifest --check、sdist/wheel、RC/Alpha/历史升级恢复，以及隔离双库 Docker 安装。前端无行为修改时沿用 RC 四桌面旅程并做候选代表性浏览器复验；有行为修改则重跑相关四桌面中英文验收。

主代理审核各尝试范围、测试与结论；另安排交叉复核关键发布/安全改动。保存脱敏报告、确切命令与通过/失败/未运行结果，日志只在忽略的 backend/data/v1-stable-20260927。已发布 RC 摘要从正式 release-verification.json 核对，不使用 latest。

## 完成条件

准备 v1.0.0 的未发布候选 PR，CI 全绿，所有新增行为有测试，发布状态文档不声称 Accepted。P0/P1 无未处置项；已知依赖风险单独呈交用户稳定版决策。没有补造长期 SLA、全站模型兼容或生产验收。遇到新阻断、不可兼容变更或需要扩大模型/发布权限时先报告；不绕过门槛。
