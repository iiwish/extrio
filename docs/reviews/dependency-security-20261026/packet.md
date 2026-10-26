# 定向依赖安全修复执行包

任务：`DEP-SEC-20261026`。风险：High（安全依赖）；状态：执行中，不是发行或部署授权。

## 授权与目标

用户于 2026-10-26 在获知 PR #53 的 4 条 HIGH 阻断及“单独修复依赖并重新验证制品”下一步后明确要求“请继续”。本轮只修复、回归、独立复核与 PR 制品验证；不合并、不创建新候选/稳定版标签或 Release、不部署、不处理其他既有 PR。

基线是 `codex/v1-rc3-receipt-20261023` 的 `b579ef542b1788f47b485021c4999d2dd519dfb4`。既有 13 文件发行回执提交保留；以独立修复提交追加到本任务 PR #53，不改写首轮失败提交或通过重跑旧提交掩盖失败。RC3 标签、镜像与三份已公开 JSON 字节不变。

目标：pypdf 6.21.1 定向更新至 6.21.2；filelock 3.32.4 定向更新至 4.2.1。只更新对应包、项目安全约束与测试，不升级其他依赖，不改变 API/schema、解析资源上限、访问控制或发行扫描门槛。

## 要求与兼容边界

- `SEC-01`：直接依赖 pypdf 为 `>=6.21.2,<7`；filelock 保持传递依赖，通过 uv `constraint-dependencies` 为 `>=4.2.1,<5` 设置持久安全下限；锁定当前最小修复版。
- `SEC-02`：使用结构化 TOML/PEP 440 校验安全下限、锁与实际已安装版本；旧配置和旧运行环境必须实际 RED，修复后 GREEN。
- `SEC-03`：tldextract 5.3.2 的依赖仅要求 filelock>=3.0.8，使用 FileLock 而非 ReadWriteLock。验证离线缓存冷/热路径以及临时目录中跨进程互斥、超时与释放后重获；不触及任何既有锁或数据目录。
- `SEC-04`：既有文本/扫描 PDF、间接字体资源、正文质量与子进程解析回归保持；大小、页数、CPU、内存和超时限制不是修复替代品，不通过放宽限制使测试成功。
- `SEC-05`：完整后端、wheel/文档/发行门禁、Ruff、锁一致性和本任务精确 head 现有 CI 均独立执行；原生两架构实际镜像完整清单及 JUnit 证据须绑定新提交。HIGH/CRITICAL（含未修复项）仍全部阻断，不忽略、豁免或降低评级。
- `SEC-06`：文档区分 RC3 的 10 月 23 日历史快照、10 月 26 日重建 CI 告警和本轮尚未发布的修复结果。来源厂商与扫描器评级差异保留，不声明零风险或实际发布摘要今日复扫成功。

默认镜像、CI 和源码安装使用 uv frozen/locked；filelock 的 uv 约束不进入 wheel Requires-Dist，本轮不承诺普通 pip 单独解析 wheel 获得相同传递依赖下限。OCI 是主部署制品，wheel 是次级开发制品。

## 分工与文件

三个实现面可并行且文件互不冲突；worker 不得再委派。

1. 依赖 worker：仅 `backend/pyproject.toml`、`backend/uv.lock`、新增 `backend/tests/test_dependency_security.py`。用 apply_patch 做手工编辑，uv 只定向解析上述两个包。新环境位于本轮独占 `/private/tmp/extrio-dependency-security-20261026`，不更新用户 `backend/.venv` 或旧核验 venv。记录 RED/GREEN 和解析差异，不提交或远程写。
2. 兼容 worker：仅新增 `backend/tests/test_dependency_compatibility.py`，可读本执行包和上游 metadata/公告。既有版本的兼容基线可先通过，安全下限 RED 由依赖 worker负责；新版本在独占环境完整通过。所有文件锁、缓存与子进程只使用 pytest 临时路径。不提交或远程写。
3. 主执行者：维护本目录证据、`docs/releases/v1.0-rc.3.md` 和 `docs/releases/v1.0.0.md` 的当前安全告警及未发布修复边界，补充 `backend/tests/test_docset_authority.py` 的历史快照边界回归，按既有脚本生成 manifest。将两个新依赖测试文件追加到 `scripts/verify-slim-image.sh` 的原生测试清单，并在 `backend/tests/test_backend_image_contract.py` 补清单回归，不改扫描规则。审查依赖结构化差异与完整 diff，运行本地全量、提交/推送本任务修复、只读跟进 CI、下载独立验证新制品证据。安全复核 worker 在实现后只读审查，不编辑实现文件。

## 验证与停止条件

安全下限测试 RED → 定向解析 → 新独占环境 GREEN → PDF/来源/兼容回归 → 全后端（浏览器与临时 PG16 就绪才执行）→ wheel/manifest/Ruff → 独立审查 → 本任务 PR 新 head CI → 双架构原生制品清单/真实 JUnit 复核。本地全量若在隔离环境准备阶段被阻断，保留准备失败并明确 `Not_Run`，由该新提交现有 CI 的隔离 PG16 全量完成同一门禁，不将未执行或被跳过项计作通过。

依赖差异须限定为两包及项目元数据；需要第三方依赖变更或源码行为变化时先停止并报告原因。依赖解析失败、测试失败、制品新增 HIGH/CRITICAL 或证据不完整均保留原结果，不自动重跑或放宽门禁。旧实例、业务库、真实来源、调度、付费模型、RC3 标签及公开回执禁止操作。

完成状态为 `Needs_Review`：新 head 工程和限定制品证据通过、风险与剩余门槛明确，PR 可供用户复核；不是用户签收、合并、预发布或生产部署。
