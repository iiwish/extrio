# RC3 受控预发布执行包

任务：`RC3-RELEASE-20261023`。状态：执行中；不是稳定版签收。

## 授权与范围

用户于 2026-10-23 明确授权下一候选预发布：同步版本与发行文档，按现有门禁验证双架构制品，全部通过后发布预发布版并核验发布摘要安装。只处理本任务新建的发行准备/发行回执 PR；其他既有 PR 不处理。

基线为已合并 #50、#51 的 main `2d4fa91f4df68e66ecafd097ea20a9d82e6b4f34`。目标为尚未占用的 `v1.0.0-rc.3`；Python/Web 版本分别为 `1.0.0rc3` / `1.0.0-rc.3`。API 合同和 schema 014 不变。

禁止正式 `v1.0.0`、部署或升级既有实例、启用来源调度、真实采集、付费模型、写现有业务库、处理其他 PR、修改保护规则、管理员绕过、风险豁免、移动既有标签或用重跑掩盖失败。72 小时观测沿用已有豁免，不计通过。

## 文件与执行分工

- 版本/文档 worker：仅修改 `backend/pyproject.toml`、`backend/src/extrio/__init__.py`、`backend/uv.lock` 的本项目版本、`web/package.json`、`backend/tests/test_release_package.py`、`backend/tests/test_docset_authority.py`、`scripts/update-docset-manifest.py`、`docs/releases/v0.2-docset-manifest.json`、`README.md`、`README.zh-CN.md`、`ROADMAP.md`、`docs/SSOT.md`、`docs/product-contract.md`、`docs/frontend-prototype.md`、`docs/releases/v0.2-acceptance.md`、`docs/releases/v0.7-upgrade.md`、`docs/releases/v1.0.0.md`、新建 `docs/releases/v1.0-rc.3.md`。不升级依赖或修改运行行为，不改既有冻结发行/审查记录。
- 制品 worker：只在 `/private/tmp/extrio-rc3-release-20261023` 创建本轮隔离验证器和回执；可只读参考 RC2 验证器、工具与校验和，不修改旧证据。绑定本轮标签、实际 main SHA、工作流、平台和工具摘要，不能复用 RC2 成功结论。
- 主执行者：维护本执行包与本目录核验记录，审查完整 diff、执行本地验证与 GitHub 正常 PR/CI/合并、创建唯一新预发布标签、跟进发行、执行并核对发布摘要验证和清理。任何实际发布/合并均由主执行者串行操作。

两个 worker 允许并行，文件互不冲突；不得再委派。候选准备、发布与实际回执分别记录，不将待执行内容写成已通过。

## 验证与门禁

1. 先更新发行版本/文档回归期望并确认旧版本失败，再完成最小元数据/文档修改；不添加产品行为。本地版本、wheel、文档合同、manifest、Ruff、前端测试/lint/build 通过。依赖和 API/schema 无变更。
2. 发行准备 PR 精确 head 的全部现有检查成功、无冲突或未处理阻断后，遵守保护规则正常合并。实际 main SHA 必须独立通过 push/手动 CI 与 Container verification；双架构 noble 原生制品还须绑定该实际 SHA 独立验证，并检查完整等级清单、能力探针及双库升级恢复结果。
3. 所有 HIGH/CRITICAL（含未修复项）阻断，MEDIUM/LOW 保留完整清单并评估。不忽略告警或借用 RC2 扫描，不更换默认镜像配方/发行工作流来规避门禁。任一失败保持可见，停止标签晋升和发布，不自动重试。
4. 精确提交、完整制品证据和安全评估通过后，只创建不存在的 `v1.0.0-rc.3` 标签。现有发行工作流验证 main 祖先及精确提交 CI，构建 amd64/arm64，四组高危扫描、签名/provenance 及晋升前重验全部通过后，才创建预发布 Release。不得创建稳定版或 `latest` 镜像。
5. 发布后独立验证 backend/web 版本标签和源 SHA 标签匹配的不可变索引及平台摘要，cosign 精确工作流/标签身份，provenance 源 SHA/ref 和托管 runner；对实际发布的两镜像两架构做包含未修复项的完整扫描。不使用本地重建镜像代替发布制品。
6. 用已验证发布摘要分别执行 SQLite/PG16 `scripts/verify-compose.sh --image-only`，仅独占临时 Compose 项目、loopback 端口和合成账号。核对清理后的容器/卷/网络无残留；已有容器与实例不重启、不连接业务库。安装不是部署。
7. 将非敏感 `release-verification.json`、完整 `vulnerability-inventory.json` 附加到本轮 Release，并重新下载核对哈希。发行说明明确采购网历史/真实增量、106 条质量待处理、六来源支持边界、目录工具不等于原生全站适配、稳定版仍 `Needs_Review`。
8. 真实发布与摘要安装成功后再同步 canonical 已发布状态、实际 SHA/工作流/摘要入口，保持 RC1/RC2 历史冻结；必要的文档回执 PR 仍走正常保护规则与主干 CI。不因源码或预发布成功宣布产品最终 `Accepted`。

## 完成条件

预发布 Release 存在且明确 `prerelease=true`；标签/版本/main 源提交一致，双架构安全与能力证据、签名/provenance、实际发布摘要双库安装和清理均通过，回执可独立复核；最新发行文档准确，其他 PR、既有实例、业务数据与调度未操作。失败时报告真实失败和已执行边界，不宣告完成。
