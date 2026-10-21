# 修复验证执行记录

日期：2026-10-06，Asia/Shanghai。工作目录 `/Users/iiwish/self/extrio`。产品源码与最终镜像身份见 [report.md](report.md)，无新增提交。本记录不授予发布权限。

## 隔离

专属本地 PG16 容器 `extrio-release-fixes-pg16-20261006` 与最终复验的 `extrio-release-fixes-pg16-final-20261006`，分别仅绑定 `127.0.0.1:55436`；不读取项目生产数据库 URL。`EXTRIO_TEST_DATABASE_URL` 下文省略测试口令。G4 各自创建临时数据库/SQLite、0700 目录与 0600 随机 QA 凭据；API 为 8056/8057，生产预览 5206/5207。模型为本地 HTTPS 合成协议 fixture，不调用付费模型。Docker 使用唯一 `extrio-e2e-releasefixes-*` 项目、18056/18057 API 与 18086/18087 Web 端口。

原始输出目录 `backend/data/v1-release-fixes-20261006/`，下表日志名相对该目录。

## 命令与结果

| 执行 | 退出结果 | 输出 |
| --- | --- | --- |
| 新增测试后 `uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_collector_input.py backend/tests/test_benchmark.py -q` | 1，25 failed / 1 passed / 16 PG skipped；尚未启动 PG，双库缺陷已有失败探针 | `tdd-red-backend.log` |
| `pnpm --dir web exec vitest run src/features/home/home-page.test.tsx`（修复前） | 1，1 failed / 3 passed | `tdd-red-web.log` |
| 同上，加入加载/读取失败回归、保护实现前 | 1，2 failed / 3 passed | `aria-state-red.log` |
| `uv lock --project backend --upgrade-package pyjwt --upgrade-package urllib3 --upgrade-package multidict` | 0，仅三包升级 | 真实工具输出、uv.lock diff |
| 移除 CLI 后 `pnpm --dir web install --registry=https://registry.npmjs.org` | 0 | `pnpm-install.log` |
| `pnpm --dir web update source-map-js fast-uri brace-expansion undici --no-save --registry=https://registry.npmjs.org` | 0，定向升级；不新增直接依赖 | `pnpm-security-update.log` |
| `EXTRIO_TEST_DATABASE_URL=… uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_collector_input.py backend/tests/test_benchmark.py -q` | 0，42 passed | `tdd-green-backend.log`、格式整理后的 `tdd-green-final.log` |
| 同上全量 `backend/tests -q --junitxml=…/backend-junit.xml` | 0，843 passed，0 skipped | `backend-test.log`、JUnit |
| `pnpm --dir web test`，最终状态保护后 | 0，265 passed / 42 files，29.02s | `web-test-final.log`，检入 `evidence/frontend-test.log` |
| `pnpm --dir web lint`、`pnpm --dir web build`，最终状态保护后 | 均 0 | 真实工具输出、`web-build-final.log` |
| `uv run --project backend ruff check backend/src backend/tests` | 0 | `ruff-final.log` |
| `uv run --project backend ruff check --config backend/pyproject.toml scripts/benchmark.py` | 0 | `ruff-script-final.log` |
| `pnpm --dir web api:generate`、`git diff --exit-code -- web/src/api/generated/schema.d.ts` | 均 0，无类型差异 | `api-generate.log` |
| `uv build --project backend --out-dir …/dist` | 0，sdist/wheel | `package-build.log`、`dist/` |
| `uv run --project backend python scripts/update-docset-manifest.py --check`（最终文档后） | 0 | 最终实际输出 |
| `uv sync --project backend --locked --python 3.12`、`pnpm --dir web install --frozen-lockfile` | 均 0 | 真实工具输出、`frozen-install.log` |
| `benchmark.py --collectors 3 --pages 2` | 0，6 Run / 42 页 / 24 accepted / 新增未变各 12 | `pipeline-benchmark-final.log` |
| `g4-qa-instance.py --output …/g4-qa-sqlite-final --api-port 8056 --web-port 5206 --duration 3600`，另 PG 实例加 `--postgresql` 与显式测试 URL | 正常启动，正常终止 0 | `instance-*-final.log`、实例 app/worker log |
| `EXTRIO_API_PROXY_TARGET=http://127.0.0.1:8056 pnpm --dir web preview --host 127.0.0.1 --port 5206 --strictPort`，另 PG 对应 8057/5207 | 正常服务；清理 SIGTERM 后 143 | `preview-*.log` |
| `g4-browser-qa.py --instance …/g4-qa-sqlite-final --web http://127.0.0.1:5206`，另 PG 对应最终实例/5207 | 各 0，136 页面组合 | `browser-*-final.log`、browser-journey JSON |
| 原 QA `live-api-probes.py --instance …/g4-qa-*-final`，主旅程完成后 | 各 0，58/58、notRun=0 | `probes-*-final.log`、live-api-probes JSON |
| 原 QA `browser-audit.py --instance …/g4-qa-*-final --web http://127.0.0.1:520* --axe …/audit-tools/node_modules/axe-core/axe.min.js` | 各 0，45 扫描 / 0 违规 | `browser-audit-*-final.log`、browser-audit JSON |
| 唯一自有项目 `bash scripts/verify-compose.sh`，SQLite/PG16，显式自有镜像/测试端口、auth=true、cookie_secure=false；PG 指定 `EXTRIO_E2E_COMPOSE_FILE=/Users/iiwish/self/extrio/compose.postgres.yaml` | 两库 0，最终前端构建与卸载 pip 后的后端冷安装通过 | `compose-sqlite-aria.log`、`compose-postgres-aria-final.log` |
| 最终镜像 `docker run --rm --network none … --entrypoint /opt/extrio/bin/python … /tmp/benchmark.py --collectors 1 --pages 2` | 0，14 页 / 8 accepted / 新增未变各 4 | `image-pipeline-aria-final.log` |
| 最终镜像相同隔离运行 `/tmp/container-browser-smoke.py`，两脚本只读挂载 | 0，基础 pip 不存在，RestrictedBrowser/Chromium 200、真实 DOM | `image-browser-aria-final.log` |
| `uvx pip-audit --path backend/.venv/lib/python3.12/site-packages --format json --output …/python-audit.json` | 1，唯一 NLTK 无补丁告警；非通过 | `python-audit.json` |
| `pnpm --dir web audit --registry=https://registry.npmjs.org --json` | 0，全部等级为 0 | `web-audit.json` |
| Trivy fs，当前工作文件快照，vuln/secret、包含 dev dependencies | 0，1 个 NLTK、0 Web、0 secrets | `fs-scan-aria-final.json` |
| Trivy image，最终镜像，原 HIGH/CRITICAL + ignore-unfixed + exit-code 1 门禁 | 后端/Web 均 0 | `*-image-aria-gate.json`、对应 log |
| Trivy image，最终后端，不筛选等级/未修复状态 | 0 是发现扫描，无失败阈值；514 条未修复包记录、0 可修复告警 | `backend-image-aria-full.json` |
| 最终文档 `pytest …/test_docset_authority.py …/test_release_package.py -q` | 0，6 passed，3.75s | `docset-package-final.log` |
| `git diff --check` | 0 | 最终实际输出 |

Trivy 命令使用固定扫描器摘要、唯一自有容器名/label、同一个专属 cache，串行执行避免缓存锁。源码快照来自 `git ls-files --cached --others --exclude-standard`，包含当前工作文件，不使用旧 HEAD 冒充修复；不包含 `.env`、node_modules、虚拟环境、运行数据库或忽略的私有 QA 目录。

全量 843 项后，最终 Dockerfile 运行环境处置与候选交接文档分别通过最终镜像双库冷安装、容器 Worker/Chromium、安全扫描和 6 项文档/制品专项复验；基准格式整理后另跑 10 项回归。最终 ARIA 状态保护后重新运行前端全量、lint/build、272 桌面组合、116 API 探针、90 axe 扫描及镜像复验。未将重复执行累计成更大的全量计数。

## 中间尝试

- pip 25.0.1 的完整镜像发现扫描有 5 MEDIUM / 1 LOW 可修复告警。升级 26.2.0 后扫描仍检出 vendor msgpack/setuptools/urllib3，并以门禁退出 1；保留 `backend-image-before-pip.json`、`backend-image-full-final.json` 与 `trivy-backend-gate-final.log`。该镜像不是最后验证对象。最终移除运行期不需要的基础 pip 后，重新构建、双库冷安装、容器 Worker/Chromium、完整扫描与原门禁。
- 一次全库 Ruff 显式 `--config` 调用改变了自动 first-party 路径识别，产生导入分组告警；采用仓库 CI 的按路径配置发现命令通过，未修改/弱化规则。基准的一个原有长输出行已正常换行。
- 新容器 smoke 脚本第一次 lint 检出异步函数阻塞调用与导入顺序，已修正并重跑 lint 与容器实测，不把首次结果当最终通过。
- pnpm 的既有 TypeScript 6 / openapi-typescript 7 peer 范围警告保留，`peers check` 为 1；基线锁文件已是 TypeScript 6.0.3。本任务没有升级 TypeScript，类型生成与生产构建均实测通过。
- 前端套件两个 jsdom navigation 警告不导致测试失败，保持原有报告边界。
- 最终 PG 实例第一次启动先于 PostgreSQL 就绪而失败；`pg_isready` 成功后使用新目录正常启动，失败目录保留。最初在主旅程尚未完成时运行 API 探针有 notRun=1，退出 0 不当作完整验收，旅程完成后原探针两库各 58/58、notRun=0。一次 Compose 调用误用不生效的 `EXTRIO_COMPOSE_FILE` 变量，实际只额外测试了 SQLite；最终使用正确的 `EXTRIO_E2E_COMPOSE_FILE` 并确认 PostgreSQL 容器/迁移/就绪与清理，不将误选配置计为 PG 覆盖。

## 清理与未执行

G4 supervisor 9575/9589 及最终的 14734/15171 正常终止，API/Worker 子进程关闭，专属数据库由 supervisor 清理；停止各 PG16 前查询无 `extrio_%` 数据库。两个容器 stop/rm -v 删除各自专属匿名卷；最终匿名卷 `c74a4bcf9d6233296d2845aa0d73498e103f0645d75bbd04ef31b1298448a9ad` 确认不存在。最终两个 preview 15070/15088 已终止。所有自有 Compose 项目由 trap down -v 删除容器、网络和卷；测试模型/页面/Webhook 端口随 supervisor 关闭。QA 凭据及浏览器会话文件删除，专属源码副本/Trivy cache 与本地测试镜像标签清理。9 个固定测试端口无监听，其他项目三个容器保持原状，没有全局 prune。

未执行新 commit/PR/远程 CI、amd64、新正式签名/provenance、tag/release、生产部署、真实付费模型或长期性能/读屏器验收。现行门禁成功和全部应用回归通过不替代稳定版风险接受。
