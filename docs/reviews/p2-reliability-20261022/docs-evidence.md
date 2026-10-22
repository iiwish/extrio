# D001 发行状态文档同步证据

任务：`P2-RELIABILITY-20261022/D001`。执行者：文档 worker。日期：2026-10-22（Asia/Tokyo）。基线：`cd60804a60aaa7bbbcbd4a07ec7a3738b0699c75`，工作分支：`codex/p2-reliability-20261022`。状态：本批次定向验证通过，等待主执行者整体验证与用户复核；不是稳定版签收。

## 只读远程核验

通过 GitHub connector 的 GET API，独立核对：

- `branches/main` 返回上述 main SHA。
- [PR #49](https://github.com/iiwish/extrio/pull/49)为 `merged=true / closed`，merge SHA 为上述 main SHA。
- `git/ref/tags/v1.0.0-rc.2` 为 annotated tag，tag object `b9b058870b43c96074f4a29d316338e14d52ab12` 指向同一 main SHA。
- [RC2 Release](https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.2)为 `draft=false / prerelease=true`，`published_at=2026-10-21T08:14:03Z`，即 2026-10-21 17:14:03 JST。
- [main CI](https://github.com/iiwish/extrio/actions/runs/39564528241)、[Container verification](https://github.com/iiwish/extrio/actions/runs/39564528254)、[Default native image verification](https://github.com/iiwish/extrio/actions/runs/39564627060)、[Release containers](https://github.com/iiwish/extrio/actions/runs/39565800203)均 `completed / success`，`head_sha` 均为上述 main SHA。
- Release 的两项资产存在：`release-verification.json` 的元数据摘要为 `sha256:3cd362eb6a98639078557bf4779ec0a034d528b7a745ed95bde2415861e2bd92`，`vulnerability-inventory.json` 为 `sha256:ccb4f6b2966f117bfd0437aa056b860022eca493c46732fb4bd6cb8aa5d6442b`。

本批次没有下载/重建/扫描镜像，没有重新验算签名或 provenance，没有安装已发布摘要。文档中的 1108/278、两架构各 258 项和 0 CRITICAL / 0 HIGH / 30 MEDIUM / 16 LOW 是 2026-10-21 RC2 冻结发行记录，不是本轮重新执行的结论，不推断今天新漏洞库的状态。

## 修改范围

- `docs/SSOT.md`、`docs/product-contract.md`、`docs/frontend-prototype.md`、`docs/releases/v0.2-acceptance.md`：统一已发布 RC2、精确 SHA、未发布稳定版 `Needs_Review`、本轮修复未发布及既有实例未升级。范围、权限和用户签收要求不变；实际编辑日期同步为 2026-10-22，不变更合同版本。
- `docs/releases/v1.0.0.md`：当前验收矩阵以 RC2 为发行基线，历史 NLTK/旧镜像风险保留其历史适用范围；两个 P2、业务验收和新候选制品评估仍为明确门槛。
- `docs/releases/v1.0-rc.2.md`：记录已发布事实和精确工作流入口，区分 RC2 制品与未发布修复，并保持来源覆盖、质量积压、调度和部署限制。
- `README.md`、`README.zh-CN.md`、`ROADMAP.md`：统一 RC2 入口与稳定版验收顺序，不承诺全站兼容、生产容量或 SLA。中文源码安装命令使用已锁定的 Playwright shell，不调用已移除的 `crawl4ai-setup`。
- `backend/tests/test_docset_authority.py`：加强四主合同/发行交接语义一致性，保留 P01–P32 与稳定版发布授权门禁检查；增加 README/ROADMAP 状态和当前安装入口检查。
- `docs/releases/v0.2-docset-manifest.json`：使用现有生成器更新实际权威文件指纹，不重写历史审计或发行制品回执。

## RED / GREEN

先只修改语义合同测试，执行：

```sh
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_docset_authority.py -q
```

RED：退出 1，`3 failed / 2 passed`。失败分别命中四主合同无已发布 RC2 状态、稳定版交接缺当前发布 SHA、交接仍混用旧安全基线。不是环境、网络或无关业务断言失败。

文档更新后，同一命令 GREEN：退出 0，`5 passed`（0.02 秒）。

```sh
/tmp/extrio-health-20261022/backend-venv/bin/ruff check backend/tests/test_docset_authority.py
/tmp/extrio-health-20261022/backend-venv/bin/python scripts/update-docset-manifest.py
/tmp/extrio-health-20261022/backend-venv/bin/python scripts/update-docset-manifest.py --check
git diff --check
```

均退出 0；Ruff 输出 `All checks passed!`，manifest 检查输出 `documentation manifest is current`，diff 无空白错误。业务 worker 后续若修改权威 API 合同，主执行者须在最终源码冻结后再次运行 manifest 生成器和检查。

## 最终源码状态同步

主执行者完成两个 P2 的源码修复、独立复核及整体验证后，稳定版矩阵与 ROADMAP 明确标记“源码修复与工程验证通过，待用户复核”，链接 [最终复验](verification.md)。主执行者报告的本轮结果为后端 SQLite/PG16 单次全量 1125 项通过、零跳过，前端 286 项/43 文件通过，类型、lint、构建及真实桌面旅程通过；独立代码复核未发现新增 P0/P1/P2。完整命令和证据由最终复验记录负责，本段不声称文档 worker 独立重跑了全部工程验证。

本轮源码修复仍未发布，RC2 已发布制品的缺陷范围不被改写；既有实例未升级，稳定版 `Needs_Review`、业务/制品安全/发布与生产授权门槛保持有效。最终 API 合同和上述当前状态纳入同一 manifest 重新生成与定向文档检查；原 RED/GREEN 回执保留原执行结果。

最终同步后的同一 docset 测试命令退出 0，`5 passed`（0.05 秒）；manifest 重新生成及 `--check` 均退出 0，`git diff --check` 退出 0。

## 边界与残余风险

没有编辑 A001/A002 业务源码或其测试，没有提交、推送、合并、打标签、发布或部署，没有连接业务数据库。没有扩大支持站点或关闭采购网/质量积压验收项。文档合同与 hash 检查不能证明全部文档语义永不漂移，后续发行须继续核对精确提交和适用证据。
