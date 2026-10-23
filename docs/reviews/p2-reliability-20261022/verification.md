# P2 可靠性修复最终复验

日期：2026-10-22（Asia/Tokyo）。任务：`P2-RELIABILITY-20261022`。
状态：**源码修复与工程验证通过，待用户复核**；不是 `Accepted`、稳定版签收或发布授权。

复验分支：`codex/p2-reliability-20261022`；源码基线：
`cd60804a60aaa7bbbcbd4a07ec7a3738b0699c75`。本记录为提交前工作树的工程复验快照，不充当远程 CI 回执。
用户授权本轮修复的提交、推送、PR 与 CI 跟进；Git 交接边界见 [执行包](packet.md#git-交接授权)，具体提交与远程结果以 PR 元数据及 CI 回执为准。
本轮没有发布、部署、合并、打标签、升级既有实例或启用来源调度。

## 修复结论

| 问题 | 当前行为与回归边界 | 证据 |
| --- | --- | --- |
| F1：恢复调度遇到启动拒绝时整轮回滚、批次反复等待 | `RunStartError` 进入现有预期运行期拒绝路径；签名 key 退役/失信后批次终结为 `needs_attention / dispatch_rejected`，不预留预算或创建 Run；其他有效 host 的批次继续推进。未知异常继续抛出并回滚，不扩大异常吞噬范围 | [A001 RED/GREEN](recovery-evidence.md) |
| F2：创建来源丢响应重试生成新 key，零成功结果导航到不存在的需求 | 同一挂载表单的相同 payload 重试复用幂等键；payload 改变或确定结果后继续导入使用新键。新需求零创建返回 null 身份，结果页不显示虚构版本/详情链接；既有需求和部分成功保留真实身份 | [A002 RED/GREEN](creation-evidence.md) |
| D001：发行状态和稳定版门槛混用 | 四主合同、README、ROADMAP、RC2 与稳定版交接一致：RC2 已预发布，本轮修复未发布，稳定版仍为 `Needs_Review`，既有实例未升级。语义回归和 manifest 同步 | [D001 核验](docs-evidence.md) |

新增回归先在原实现上确认预期失败，再做最小修复。签名、人工审核、预算、权限、来源唯一性与生产 Run 不调用模型的边界未放宽。
独立 reviewer 检查完整静态 diff、异常调用链、nullable 响应消费者、重试状态和发行状态边界，并独立运行五个 SQLite 恢复回归节点；未发现新增 P0/P1/P2。全量和浏览器结果由主执行者实际运行并汇总如下。

## 自动化验证

使用隔离的冻结 Python 3.12.13 环境 `/tmp/extrio-health-20261022/backend-venv`，没有修改共享 `backend/.venv`。
PG16 仅为本轮 Docker 容器，数据目录使用 tmpfs，端口绑定 loopback；测试 fixture 创建/删除自己的临时库。完整后端在同一次运行中覆盖 SQLite 与 PostgreSQL，没有以多次结果相加冒称全量。

| 验证 | 最终结果 |
| --- | --- |
| 后端全量 `backend/tests` | **1125 passed，0 skipped**，282.93 秒；[原始输出](evidence/backend-test.txt)、[JUnit](evidence/backend-full.xml) |
| 最终冻结后恢复与创建两文件双库复跑 | **80 passed**，63.66 秒；[输出](evidence/final-targeted.txt)。包含全量开始收集后补充的既有需求身份断言，不重复计入 1125 |
| 前端 `pnpm --dir web test` | **43 文件 / 286 passed**，51.96 秒；[原始输出](evidence/frontend-test.txt) |
| `pnpm --dir web lint` | 退出 0 |
| `pnpm --dir web build` | TypeScript 与 Vite production build 退出 0；最终状态再次执行通过 |
| OpenAPI 重新生成到 `/tmp` 并与仓库类型 `cmp` | 完全一致，退出 0 |
| `ruff check backend/src backend/tests` | `All checks passed!` |
| 最终文档语义回归 | **5 passed**，0.04 秒；不重复计入后端全量 |
| `scripts/update-docset-manifest.py --check` | `documentation manifest is current` |
| `git diff --check` | 退出 0 |

主要复验命令：

```sh
env EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_p2_test@127.0.0.1:32790/postgres \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests -ra \
  --junitxml=/tmp/extrio-p2-qa/backend-full.xml
env EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_p2_test@127.0.0.1:32790/postgres \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_bounded_recovery.py \
  backend/tests/test_collector_input.py -q
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
pnpm --dir web exec openapi-typescript ../docs/contracts/openapi.yaml -o /tmp/extrio-p2-qa/schema-final.d.ts
cmp /tmp/extrio-p2-qa/schema-final.d.ts web/src/api/generated/schema.d.ts
/tmp/extrio-health-20261022/backend-venv/bin/ruff check backend/src backend/tests
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_docset_authority.py -q
/tmp/extrio-health-20261022/backend-venv/bin/python scripts/update-docset-manifest.py --check
git diff --check
```

上述 PG 凭据只用于已销毁的临时测试容器。原始完整日志保留在 `/tmp/extrio-p2-qa/`；关键 stdout 与结构化回执同时纳入本目录。
全量测试覆盖本地 HTTP/Chromium fixture、安装、历史/Alpha/RC1 升级、备份恢复及既有签名/调度/交付路径，不表示执行了真实业务实例迁移。

## 真实桌面浏览器

使用真实前端、API、worker 与独立 SQLite/Artifacts/密钥，不使用 MSW。QA 根目录为
`/tmp/g4-qa-p2-reliability-20261022`；API `8056`、Web `5206`、故障代理 `8060`；来源与模型均绑定本地合成 fixture。

1. 登录后通过新建来源页提交“P2 lost-response QA”。[故障代理](evidence/fault-proxy.py)在首次真实后端 200 提交完成后主动断开响应，页面显示请求失败且保留表单；再次提交返回原始对象。两次 key/body 哈希一致，第二次有 `Idempotency-Replayed`，API 确认该 URL 只有一个来源，没有重复需求。
2. 重复 URL 全部拒绝：中英文结果显示“未创建采集来源 / No sources created”和“未创建采集需求 / No requirement created”，没有虚构版本或需求链接；API 确认没有空需求。
3. 真实完整旅程：创建需求，设置必填、身份与指纹 title 字段，发布并刷新确认 v1；添加来源、生成候选、人工审核发布；配置本地签名 Webhook，运行一次成功，`accepted=1 / rejected=0`；检查条目、固定版本和 lineage，CSV/JSONL 各一行与实体/决策一致，接收端 HMAC 校验有效。
4. 合成模型只有生成候选前的 discover/compile 两次调用，Run 前后记录不增加；不把协议 fixture 视为真实模型质量验证。
5. 概览、需求列表/详情、来源列表/详情、运行列表/详情、条目列表/详情、设置共 10 个页面，中文/英文各四档桌面；再加零创建结果两语言四档，共 **88 组 CSS 尺寸与布局检查**。目标为 `1440x900`、`1280x800`、`1132x1028`、`1024x800`；实际尺寸均匹配，无页面级横向溢出，主页面无意外 alert。未测试移动端。
6. 最后退出登录，返回登录页。

结构化证据：[代理回执](evidence/proxy-receipts.jsonl)、[创建对象核验](evidence/creation-runtime-check.json)、[完整旅程核验](evidence/journey-runtime-check.json)、[88 组尺寸测量](evidence/desktop-measurements.json)。
两份只读 API 核验脚本保留为 [创建核验脚本](evidence/check-creation-runtime.py)与[旅程核验脚本](evidence/check-journey-runtime.py)；它们是本次临时实例的具体回执脚本，不是通用 CI E2E lane。

代表性截图：[重试获得原对象](evidence/02-retry-created-original-1440.png)、[运行结果](evidence/03-run-result-1440.png)、[中文零创建 1440](evidence/all-rejected-zh-1440.png)、[中文零创建 1024](evidence/all-rejected-zh-1024.png)、[英文零创建 1024](evidence/all-rejected-en-1024.png)、[1024 条目列表](evidence/items-zh-1024.png)。
截图像素尺寸与浏览器 CSS 尺寸可能因缩放不同，以测量 JSON 的实际 innerWidth/innerHeight 为准。88 组是布局/状态检查，不是 88 次独立完整业务旅程，也不代表逐像素设计或完整 AA 验收。

## 警告与兼容边界

- 后端保留一个第三方 `StarletteDeprecationWarning`；前端保留两次 jsdom 不支持跨 Document 导航提示。测试均正常通过，未过滤这些提示。
- 丢响应故障注入预期产生 Vite `socket hang up`；测试代理也记录浏览器导航时写入已关闭连接的 `BrokenPipeError`。这些属于故障代理/传输层测试输出，不是被忽略的业务断言失败。临时进程主动 SIGTERM 的 143 退出不作为测试失败。
- 本地前端运行于 Node 24.15 / pnpm 11.24，未在本轮本机重跑 CI 的 Node 22 环境。候选 PR 的精确 head CI 仍是后续独立门槛。
- `collectionId` / `collectionVersion` 对新需求零创建结果允许 null；同仓库调用方、OpenAPI、生成类型和 Mock 已同步。外部自编客户端须兼容该公开响应合同。历史幂等回执不重写；表单 key 不跨卸载或刷新持久化，不承诺离线队列。
- 签名可信状态由 API 与既有回归核验；浏览器旅程没有另行独立验算 Ed25519，Webhook HMAC 由本地接收端验证。
- 没有重建 Linux 双架构镜像、刷新漏洞扫描、重新验算发行签名/provenance 或安装已发布摘要。RC2 的发行与安全结果保留其冻结日期/提交范围，不移作本轮新制品结论。
- 没有访问真实来源或付费模型；没有重新统计实际采购网覆盖和历史质量积压，不把既有 72 小时观测豁免计为通过。

## 清理与交接

本轮 QA supervisor/API/worker、代理、Vite 及本地来源/模型 fixture 已停止，`8056/8060/5206/59007/59008` 无监听。
临时 PG 容器 `d42a38771bad5e38f86c1a7849b40d8452597d2875f35310afaa4a0a6a2534e8`
核对 owner label 与 tmpfs 后按精确 ID 删除，按 owner label 查询无残留容器。未删除或改动用户数据卷。
原有 `8000`（PID 24027）与 `5173`（PID 95547）仍监听，没有重启或替换；未改其数据库、环境或调度。
截图、回执和测试结果已保存，凭据、私钥及数据库文件未纳入仓库。

当前交接仅为用户复核本轮修复。稳定版业务/来源覆盖、目标用户验收、候选精确 CI、制品安全评估和发布/生产授权仍按
[稳定版交接](../../releases/v1.0.0.md)执行；本轮不继续发布或部署。
