# 1.0 发布收尾执行包

## 授权与范围

2026-09-26 用户批准按既定单组织自托管 1.0 范围开始本机开发、构建、测试和隔离 Docker 验收；允许最多三个真实模型探索任务。模型固定为官方 OpenAI 兼容端点 `https://api.deepseek.com` 的 `deepseek-flash`，每个任务沿用产品调用次数和超时预算，不自动重试任务。密钥不得写入仓库、日志或报告。

治理模式为 Direct Execute，风险等级 High。未授权委派，三个任务串行执行。已有修改属于用户工作，保留并在验证中纳入候选，不覆盖、不回退、不擅自提交无关内容。2026-09-27 用户明确授权整理提交、推送候选分支、创建 PR 和运行 CI。合并、正式 tag、镜像发布、生产部署和最终产品签收仍需分别确认；不操作 maco。

权威输入为根目录 AGENTS.md、docs/SSOT.md、docs/product-contract.md、docs/planning/v1.0-scope-matrix.md、docs/planning/v1.0-delivery-plan.md 和用户本次明确确认。单组织、本地角色、SQLite 评估、PostgreSQL 16 部署、中英文四桌面视口为边界。多租户、SSO、移动端以及待审的 P2 深度体验方案不纳入本轮。72 小时观测沿用已记录豁免，不记为通过。

## 任务与依赖

| ID | 状态 | 目标与合同 | 前置 | 验证 |
| --- | --- | --- | --- | --- |
| RC1 | Needs_Review | P22-P26、P29、P32：候选整理，当前 Alpha 升级与恢复回退，隔离容器安装 | 已确认范围 | 764 后端通过；双库 RC 容器安装通过，ARM64 双镜像可修复 HIGH/CRITICAL 为零 |
| RC2 | Needs_Review | P27-P30：真实模型、完整操作旅程、导出与签名 Webhook、桌面双语和错误恢复 | RC1 | 1 个真实任务成功；双库完整旅程、272 组桌面测量、264 前端测试通过 |
| RC3 | Needs_Review | P01、P31-P32：证据和文档定稿、候选身份、发布交接 | RC2 | 四份主合同、范围豁免、类型一致性、文档清单、校验值与发布交接齐全；Git 交接与 CI 已授权，合并发布与签收独立 |

各任务 parallel=false，共享应用、迁移和前端工作树，不并发修改。候选分支为 `codex/v1-closeout-20260926`，目标分支为 `main`，保留原有相关工作，不夹带依赖更新 PR。远程候选身份与检查结果由 PR 的 head SHA 和 Checks 固定。

## 允许修改

- RC1：backend/tests/test_release_upgrade.py、backend/tests/fixtures/release_baseline.py、相关发布/迁移/认证测试、scripts/verify-compose.sh、Docker/Compose 与发布验收配置，以及复现缺陷所直接涉及的 backend/src/extrio 模块。复核闭环包括 PG 登录计数与写入的原子性、API 代理身份单一解析，以及 Web runtime 安全补丁刷新。
- RC2：scripts/verify-real-model.py、scripts/g4-qa-instance.py、scripts/g4-browser-qa.py 及相应测试；已复现核心流程缺陷直接涉及的 backend/src/extrio、web/src 文件及回归测试。不重做页面或新增未批准能力。
- RC3：四份主合同、1.0 范围和交付规划、发布/升级/操作文档、CHANGELOG、包版本元数据及锁文件、docs/releases 清单、本目录证据。版本身份只能标记候选，不冒充已发布稳定版。
- 所有任务：本目录的 packet、verification、review 和脱敏机器结果；截图与运行细节先存入忽略的本地验收目录，仅挑选无敏感信息的必要证据入库。

## 执行前检查与分析

- [x] 目标范围及执行方案经用户明确批准；最终签收独立。
- [x] 工作树变更已检查；现有可靠性修改与本轮目标相关，CSS 拆分保持原样，不覆盖。
- [x] 既有真实模型脚本仅能复制实例配置，需要增加安全的独立密钥输入，不能修改用户实例以适配测试。
- [x] 升级测试只有 2026-09-09 基线，必须保留并新增 v0.7.0-alpha.1 路径。
- [x] 现有 OrbStack pgsql 为 PostgreSQL 18；不采用未验收的版本或修改共享容器。独立 PostgreSQL 16 用于正式双库证据。
- [x] 72 小时范围矩阵文字与批准的豁免有冲突，RC3 同步当前合同；不得据此声称长期 SLO。
- [x] 无需新增架构或数据库产品能力；新发现的范围外 High/Critical 问题先报告，不静默扩大范围。

## TDD 与验证循环

测试矩阵扩展先执行新增用例，确认现有代码在真实 Alpha 基线下的表现；若失败，保存匹配目标行为的失败证据，最小修复后重跑。测试脚本的新输入和隔离行为先写负向测试，确认失败，再实现。不得删测试、放宽产品正确性断言或跳过 PostgreSQL 来取得绿色结果。

核心命令：

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml backend/tests -q
uv run --project backend --locked ruff check backend/src backend/tests scripts/verify-real-model.py scripts/verify-release.py
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
uv run --project backend python scripts/update-docset-manifest.py --check
bash scripts/verify-compose.sh
uv run --project backend python scripts/g4-browser-qa.py --instance <owned-instance> --web <owned-web>
git diff --check
```

数据库 URL 只指向本轮独立 PostgreSQL；所有测试数据、密钥和容器可归属并清理。不得复用主实例存储。真实模型每次调用前记录任务序号，结果失败也保留脱敏用量与错误，不发布真实来源候选。

## 完成与交接

每项报告实际命令、退出码、环境、通过/失败/未运行、候选身份、残余风险。先做合同符合性复核，再做代码风险复核，最后核对浏览器与制品证据。只有所有本地门槛通过才进入 Needs_Review；远程 CI、正式发布授权和用户 Accepted 不由本地测试代替。遇到凭据、外站或付费预算阻塞时继续不依赖该条件的工作，并提前报告。
