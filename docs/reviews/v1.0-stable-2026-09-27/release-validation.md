# STABLE1 发布验证

## 范围与结论

执行日期：2026-09-27。此报告覆盖未发布 `1.0.0` 候选的版本元数据、历史数据库升级/离线恢复、sdist/wheel 与 Compose 验证脚本。未执行提交、推送、合并、tag、镜像发布或生产部署；稳定版发布仍须用户单独授权。

后端 `pyproject.toml`、`extrio.__version__`、`uv.lock` 的本项目条目及前端 `package.json` 均为 `1.0.0`。锁文件仅修改本项目版本，不包含依赖升级。版本一致性及 wheel 元数据由自动测试约束。

## 已发布 RC 升级与恢复

实际 RC 基线为 `c2fc06f420c31aaf5bbbea53332ef4af2b48804e`，通过 `git archive` 提取代码和契约；RC 数据创建、离线完整备份、恢复及恢复后的读取均在子进程中使用归档代码，不冒用当前候选的 Store 实现。

SQLite 和独立 PostgreSQL 16 均验证以下断言：

- RC 与候选同为 schema `013_runtime_backfills`。候选执行两次显式迁移后，以关闭自动迁移的模式启动读取；迁移 ID 和应用时间戳完全不变，不引入虚构 migration。
- 来源及固定集合版本绑定、规则、签名凭据、运行与条目历史、用户密码哈希与会话、采集 checkpoint、投递 sink、失败重试记录和审计事件保持一致；验证签名、密码、凭据解密及审计链。
- 候选写入额外来源并修改证据文件后，从 RC 备份恢复到空目标。归档 RC 在关闭自动迁移时读取的完整快照与备份前一致，额外来源不存在，证据和两类密钥逐字节一致，备份所有文件的 SHA-256 保持不变。
- 保留 2026-09-09 历史基线 `86ebcc4b570f8b5b5acf3f1c6ba0f70ac7ed42f7` 和已发布 Alpha `1e02dbbddd273bda7a7023b8824d0bb58f3db5d6` 的双库升级/恢复覆盖。

测试 PostgreSQL 使用主代理提供的专属容器 `extrio-e2e-stable-pg-20260927`，本地端口 `55497`，服务端为 PostgreSQL 16；客户端 `pg_dump 16.15`。每个测试创建独立、随机命名的来源/恢复数据库并在结束时删除。测试未连接用户 PostgreSQL 18，也未更改其他项目服务。

## Compose 镜像模式

`bash scripts/verify-compose.sh --image-only` 要求显式提供 `EXTRIO_BACKEND_IMAGE` 和 `EXTRIO_WEB_IMAGE`，格式为 `repository@sha256:<64 位小写十六进制>`。缺失、浮动标签、无效摘要、未知参数均在任何 Docker 操作前失败。该模式只接受仓库内 `compose.yaml` 与 `compose.postgres.yaml`，避免自定义文件绕过已验证的应用镜像引用。

启动命令固定使用 `up --no-build --pull always`；失败时只诊断和清理，不回退构建。无参数模式保留现有 `up --build`。已有项目/卷拒绝与专属临时项目清理约束不变。

16 项脚本单测使用 Docker/curl 替身验证命令和拒绝路径，不冒充真实镜像安装。真实已发布镜像的双库安装验证由主代理集成执行，独立于此单测结论；脚本本身不验证签名或来源，也不把任意合法摘要认定为正式发布镜像。

正式 RC 摘要来源为 `backend/data/v1-closeout-20260926/release-verification.json`：

| 应用 | 镜像索引摘要 |
| --- | --- |
| backend | `ghcr.io/iiwish/extrio-backend@sha256:0f841772c0dc5c45f7575203fb0fc599162fd16a40d64e5686869ce083bcb6af` |
| web | `ghcr.io/iiwish/extrio-web@sha256:c693d8f48f491655820bfbbf6fc583ef8b9ca425a7814d7531521c024bca2981` |

## 命令与结果

以下 Python 命令的工作目录为 `backend/`，Shell/git 命令的工作目录为仓库根目录。数据库 URL 经脱敏；`$EXTRIO_TEST_DATABASE_URL` 由主代理设置为上述隔离实例。

| 命令 | 结果 |
| --- | --- |
| `uv run --no-sync pytest tests/test_verify_compose.py -q`，实现前 | RED：13 failed / 2 passed；直接观察旧脚本忽略参数并构建、未拒绝非摘要引用 |
| `uv run --no-sync pytest tests/test_verify_compose.py::test_image_only_rejects_unreviewed_compose_files_before_docker -q`，实现前 | RED：1 failed；旧脚本接受未审查的 Compose 文件 |
| `uv run --no-sync pytest tests/test_verify_compose.py -q`，实现后 | GREEN：16 passed，6.83 秒 |
| `uv run --no-sync pytest tests/test_release_upgrade.py tests/test_release_package.py -q`，未设置 PG URL | 6 passed / 4 skipped，17.95 秒；跳过项为明确要求隔离 URL 的 PostgreSQL 变体 |
| `EXTRIO_TEST_DATABASE_URL="$EXTRIO_TEST_DATABASE_URL" uv run --no-sync pytest tests/test_release_upgrade.py tests/test_release_package.py tests/test_verify_compose.py -q` | 26 passed / 0 skipped，61.37 秒；包含 SQLite、PostgreSQL、三条历史基线及 sdist/wheel |
| `uv run --no-sync ruff check tests/test_release_upgrade.py tests/fixtures/release_baseline.py tests/test_release_package.py tests/test_verify_compose.py` | 通过 |
| `bash -n scripts/verify-compose.sh` | 通过 |
| `git diff --check` | 通过 |

RC 历史测试是新增验收覆盖，直接证明既有行为，不声称修复已复现的迁移缺陷。此执行尝试不替代候选全量套件、真实 Compose 安装、发布工作流及独立安全风险结论。
