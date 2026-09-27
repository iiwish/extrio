# 1.0 RC 本地验证

日期：2026-09-26。状态：`Needs_Review`，不代表正式发布或用户签收。
本地分支 `codex/v1-closeout-20260926`，基线 main 为
`72de56a0bb061e06e99c0cca37801a9a870e4ab8`。原有未提交工作全部保留；
当前候选版本为 `1.0.0rc1` / `1.0.0-rc.1`，尚无远程候选 SHA 或 tag。

## 验证矩阵

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 后端全量，SQLite + PostgreSQL 16 | 764 passed，0 skipped，179.25 秒 | `backend-final.log` |
| 发布升级与完整恢复回退 | 6 passed；含公开 Alpha 与 9 月 9 日基线，双库 | 全量测试及独立升级执行 |
| 前端全量 | 42 文件、264 passed | `web-final-tests.log` |
| Ruff / 前端 lint / TypeScript 与 Vite build | 通过 | 命令退出码 0 |
| OpenAPI 生成类型比较 | 字节一致 | `schema-final.d.ts` 与正式文件 cmp |
| sdist -> wheel | `extrio_backend-1.0.0rc1` 构建通过 | `packages-final/`，包内合同测试通过 |
| 文档 manifest / git diff --check | 通过 | 命令退出码 0 |
| 源码凭据扫描 | Trivy secret，0 findings | `scan-source-final.json`，仅 Git 可跟踪文件快照 |
| ARM64 双镜像扫描 | 可修复 HIGH/CRITICAL 均为 0；扫描层与本地制品逐层一致 | `scan-backend-final.json`、`scan-web-verified.json`，Trivy 0.69.3 |
| 双库 Compose 最终复验 | SQLite、PG16 均通过；显式迁移、readiness、鉴权与注销失效 | `compose-sqlite-final.log`、`compose-postgres-final.log`，退出码 0 |
| 双库浏览器全旅程 | 通过；各 136 组测量、0 page errors，各 1 个签名交付 | `browser-pg-rc1-final.log`、`browser-sqlite-rc1-final.log` |
| DeepSeek 真实模型 | 1 个任务成功，3 accepted samples，未发布 | 下表；原始结果仅本地受限目录 |

原始命令日志位于被忽略的 `backend/data/v1-closeout-20260926/`，目录权限 0700。
浏览器证据分别位于 `backend/data/g4-qa-final-pg-20260926/` 和
`backend/data/g4-qa-final-sqlite-20260926/`；没有将登录凭据、cookie、私钥或模型原始响应入库。
本目录 `candidate-files.sha256` 固定 380 个应用、合同、测试和构建输入文件的校验值，
不是远程 commit 身份。[制品记录](artifacts.json)保留本地 OCI index、扫描 config digest、
平台和包 SHA-256，不能冒充远程签名制品。[主视口需求](screenshots/collection-zh-1440.png)、
[最小视口英文运行](screenshots/run-en-1024.png)、[模型设置](screenshots/models-zh-1440.png)
和[英文新建来源](screenshots/new-collector-en-1024.png)为无真实业务信息的留档样本。

## 真实模型

| 属性 | 实测 |
| --- | --- |
| 端点 / 模型 | `https://api.deepseek.com` / `deepseek-flash` |
| 来源 | 北京政府采购中标公告公开列表，`A002004001index_1.htm` |
| 字段 | title、detailUrl、content |
| 执行时间 | 2026-09-26 12:09:04 至 12:10:38 UTC，94,022 ms |
| 终态 | `succeeded` / `candidate_ready` / `ready_review` |
| 调用 | 7 次，其中 2 次 `MODEL_RESPONSE_TRUNCATED`；有界任务内恢复，未重启任务 |
| token | 输入 43,471；输出 15,420；合计 58,891；无费用金额估算 |
| 样本 | 3 accepted、0 rejected、0 warnings |
| 发布 | false，未生成已发布 RuleVersion |
| 任务额度 | 已用 1 / 最多 3；剩余未使用 |

密钥通过关闭终端回显的 stdin 输入。脚本使用独立临时数据库、Artifact 和密钥目录，
不读取或改写用户实例配置，退出后销毁临时实例。结果文件以 0600 独占创建，禁止覆盖付费结果。
以上只有一个来源、一次任务，不能推算模型成功率或全站兼容性。

## 桌面与旅程

每个数据库覆盖 17 个页面/分区、2 种语言、4 个桌面视口，共 136 组，双库 272 组。
视口为 1440x900、1280x800、1132x1028、1024x800。包含概览、需求列表/新建/字段/来源、
来源列表/新建/配置/结果/规则、运行列表/详情、AI 任务、数据列表/详情、系统/模型设置。
检查页面宽度、语言属性和浏览器运行错误；人工抽查主视口与最低视口截图。

真实鉴权流程包括：创建需求、字段发布和刷新持久性、来源添加、合成模型候选、审核人身份、
Escape 关闭与焦点恢复、规则发布、Run 固定字段版本、正确提取、有效 HMAC Webhook、
CSV/JSONL 下载内容，以及 503 读取失败与刷新恢复。模型标为合成，不混入 P28 证据。
无移动端验收，不声称完整 WCAG 独立认证。

## 可复现命令

数据库 URL 由执行者指向自有临时 PG16，不能使用用户业务库。示例不含供应商密钥：

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml backend/tests -q
uv run --project backend --locked ruff check backend/src backend/tests scripts/verify-real-model.py scripts/verify-release.py scripts/g4-browser-qa.py scripts/g4-qa-instance.py
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
uv build --project backend
uv run --project backend --locked python scripts/update-docset-manifest.py --check
uv run --project backend --locked python scripts/g4-browser-qa.py --instance <owned-instance> --web <owned-loopback-web>
bash scripts/verify-compose.sh
git diff --check
```

## 边界

本机使用单独的 OrbStack PostgreSQL 16.15 容器，端口 55496；不改动用户现有 PostgreSQL 18
或其他项目数据库。两套 Compose 验收栈及卷、独立 PG16 容器及测试数据库、浏览器/API/Worker
进程均已清理。私有验收日志与虚构数据证据保留在忽略目录中，不作为正式部署。
真实模型任务无自动发布，QA 的发布仅针对虚构本地来源。
72 小时观测为豁免，历史短期基准不等于本候选长期 SLO。远程 CI、AMD64、镜像签名与
provenance、最终产品签收及生产部署均未执行，见[发布交接](../../releases/v1.0-rc.1.md)。
