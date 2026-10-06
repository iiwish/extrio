# 1.0 发布测试执行记录

日期：2026-10-06，Asia/Shanghai。源码树：`1755478777d3f62d7d135204cf11e817d99b1084`。
发布结论和逐项问题见 [report.md](/Users/iiwish/self/extrio/docs/reviews/v1-release-qa-2026-10-06/report.md)。

## 环境与隔离

从干净工作树开始。所有测试在 `/Users/iiwish/self/extrio` 执行；原始输出保存于 `backend/data/v1-release-qa-20261006/`，该目录受 Git 忽略。数据库 URL 指向本次专属本地 PostgreSQL 16 容器的 `127.0.0.1:55436`，不是仓库 `.env` 或其他项目的数据库。报告中的 `EXTRIO_TEST_DATABASE_URL` 已省略测试口令。

两个 G4 目录为 `g4-qa-sqlite` / `g4-qa-postgres`，API 使用 8056 / 8057，生产构建预览使用 5206 / 5207。QA 账号随机密码在 0600 文件中，实例目录为 0700；没有导入真实账号、真实来源或真实模型凭据。

## 命令与结果

| 实际命令 / 操作 | 退出结果 | 原始输出 |
| --- | --- | --- |
| `uv sync --project backend --locked --python 3.12` | 0 | 校验 148 包，锁文件不变 |
| `pnpm --dir web install --frozen-lockfile` | 0 | 已与锁文件一致 |
| `EXTRIO_TEST_DATABASE_URL=… uv run --project backend pytest -c backend/pyproject.toml backend/tests -q --junitxml=backend/data/v1-release-qa-20261006/backend-junit.xml` | 0，801 passed | `backend-test.log`、`backend-junit.xml` |
| `pnpm --dir web test` | 0，264 passed | `web-test.log` |
| `uv run --project backend ruff check backend/src backend/tests` | 0 | `ruff.log` |
| `pnpm --dir web lint` | 0 | `web-lint.log` |
| `pnpm --dir web build` | 0 | `web-build.log` |
| `pnpm --dir web api:generate` + `git diff --exit-code -- web/src/api/generated/schema.d.ts` | 两者 0 | `api-generate.log` |
| `uv run --project backend python scripts/update-docset-manifest.py --check` | 0 | `docset.log` |
| `uv build --project backend --out-dir backend/data/v1-release-qa-20261006/dist` | 0 | `package-build.log`、`dist/` |
| `scripts/g4-qa-instance.py` 两库实例 + Vite `preview --strictPort` | 正常启动；验收后 supervisor 0 退出 | `g4-qa-*/app.log`、`worker.log` |
| `uv run --project backend python scripts/g4-browser-qa.py --instance …/g4-qa-sqlite --web http://127.0.0.1:5206` | 0，136 页面组合 | `browser-sqlite.log`、`g4-qa-sqlite/browser-journey.json` |
| 同上 PostgreSQL / 5207 | 0，136 页面组合 | `browser-postgres.log`、`g4-qa-postgres/browser-journey.json` |
| `uv run --project backend python docs/reviews/v1-release-qa-2026-10-06/live-api-probes.py --instance …/g4-qa-sqlite` | 1，55 passed / 3 failed | `probes-sqlite.log`、实例 `live-api-probes.json` |
| 同上 PostgreSQL | 1，55 passed / 3 failed | `probes-postgres.log`、实例 `live-api-probes.json` |
| `browser-audit.py --instance …/g4-qa-sqlite --web http://127.0.0.1:5206 --axe …/audit-tools/node_modules/axe-core/axe.min.js` | 1，45 扫描、45 失败规则实例 | `browser-audit.log`、实例 `browser-audit.json` |
| `benchmark-data.py --rows 100000 --output …/scale-sqlite.json` | 0 | `scale-sqlite.json`、同名 log |
| `EXTRIO_TEST_DATABASE_URL=… benchmark-data.py --rows 100000 --postgres --output …/scale-postgres.json` | 0 | `scale-postgres.json`、同名 log |
| `benchmark.py --collectors 3 --pages 2` | 0，但 accepted=0；不能证明完整提取路径 | `pipeline-benchmark.log` |
| `pipeline-positive-control.py` | 0，6 Run、24 accepted | `pipeline-positive-control.json`、同名 log |
| `EXTRIO_E2E_PROJECT=extrio-e2e-releaseqa-20261006-sqlite … bash scripts/verify-compose.sh` | 0 | `compose-sqlite.log` |
| 同上 `EXTRIO_E2E_COMPOSE_FILE=…/compose.postgres.yaml`，专属 PostgreSQL 项目 | 0 | `compose-postgres.log` |
| Trivy fs，tracked Git archive，vuln/secret JSON | 0，作为发现扫描不设失败阈值 | `fs-scan.json`、`trivy-fs.log` |
| Trivy backend image，`--ignore-unfixed --severity HIGH,CRITICAL --exit-code 1` | 1，8 个可修复漏洞 | `backend-image.json`、`trivy-backend.log` |
| Trivy web image，首次共享缓存 | 1，缓存锁基础设施错误 | `trivy-web.log` |
| 同上，后端完成后串行重试，`--scanners vuln` | 0 | `web-image.json`、`trivy-web-retry.log` |
| `uvx pip-audit --path backend/.venv/lib/python3.12/site-packages --format json --output …/python-audit.json` | 1，19 条 / 4 包 | `python-audit.json` |
| `pnpm --dir web audit --json` | 1，npmmirror 缺少 endpoint | `web-audit.json` |
| `pnpm --dir web audit --registry=https://registry.npmjs.org --json` | 1，成功查询并发现 37 条告警 | `web-audit-official.json` |
| `uv tree --project backend --locked --invert --package pyjwt --package urllib3 --package multidict --package nltk` | 0 | `python-dependency-paths.txt` |
| `pnpm --dir web why undici fast-uri proxy-addr source-map-js brace-expansion` | 0 | `web-dependency-paths.txt` |
| GitHub CLI 只读查询 main/PR #34/Actions/Releases/Dependabot | 0 | `remote-checks.json`、`dependabot.jsonl` |
| Trivy 对新增报告、测试脚本、精选证据进行 secret-only 扫描 | 0，0 secret | `report-secret-scan.json`、同名 log |

三个新增测试脚本已执行 Ruff format/check。API 探针在格式化和闭包变量绑定调整后再次执行，最终双库结果保持 55/58；计数只算一轮，不累计重复验证。产品源代码没有修改，测试脚本的预期失败没有被掩盖。

## 可复跑入口

需要先创建新的专属 PostgreSQL 16 实例并设置 `EXTRIO_TEST_DATABASE_URL`，再使用新的 `g4-qa-*` 输出目录。原测试账号及浏览器会话文件已清理，不能直接接管原目录复跑。

```sh
uv sync --project backend --locked --python 3.12
pnpm --dir web install --frozen-lockfile
uv run --project backend pytest -c backend/pyproject.toml backend/tests -q
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
```

主旅程使用仓库现有 `scripts/g4-qa-instance.py` 和 `scripts/g4-browser-qa.py`。补充脚本的 `--help` 声明参数与本地所有权限制；模型 fixture 不替代真实模型验收。axe-core 4.13.0 单独安装于忽略目录，没有加入产品 package.json/锁文件。

## 环境清理

- 两个 QA supervisor 正常退出，API/Worker 子进程终止，G4 PostgreSQL 专属数据库由 supervisor 删除；停止前查询专属 PostgreSQL 实例无残留 `extrio_%` 数据库。
- Vite 两个 preview 进程主动 SIGTERM，退出 143 是测试结束后的预期停止，不是构建或浏览器失败。
- 两个 Compose 测试项目执行各自 `down -v --remove-orphans`，容器、网络、命名卷删除。
- 专属 PostgreSQL 16 容器已删除；通过 Docker volume unmount 事件确认归属于本次容器的匿名卷后，单独删除该卷。
- 本次 `extrio/qa-backend:20261006` / `extrio/qa-web:20261006` 镜像标签清理，扫描结果保留 Image ID。没有执行全局 Docker prune。
- 5206、5207、8056、8057、55436、18056、18057、18086、18087 均无监听；原有其他项目的 3 个运行容器保持不变。
- 临时 Git archive 副本和约 1.3GB Trivy 扫描缓存删除；原始扫描 JSON 保留。QA 登录密码与浏览器会话文件删除。
- 原始测试日志/数据库/截图等约 32MB 留在忽略目录，用于独立复核；精选脱敏证据及截图在本报告目录。没有提交、推送或改变生产环境。

清理核对日期：2026-10-06，Asia/Shanghai。
