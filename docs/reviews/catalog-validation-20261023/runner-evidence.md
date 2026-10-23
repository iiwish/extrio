# A002 安全批量执行器验证

任务 `CATALOG-20261023/A002`，状态为工程验证及独立复核完成；主执行者的完整回归和真实清单结果见[核验结果](verification.md)。此单元记录不代表控制台原生采集验收。

## 实现范围

- `scripts/tender_sources/catalog_run.py`：显式 CSV manifest、逐行持久账本、矩阵与汇总、断点续跑和保守静态样本诊断。
- `scripts/test-tender-catalog.py`：opt-in CLI，支持 `--dry-run`、`--limit`、`--entry-id`、`--group` 和 `--resume`。limit/group 只筛选本次待处理行，全部输入一直保留在 manifest 和输出矩阵中。
- `backend/tests/test_tender_catalog_network.py`：44 个完全离线的 MockTransport/本地文件系统测试，不访问真实来源。

网络层沿用 `SourceNetwork`，不另造 HTTP 客户端，不导入业务数据库、服务、账号、投递、模型或调度代码。精确单主机白名单不随重定向或候选详情扩大。每个 hop 再验 scheme、端口、用户信息及 URL，DNS/public-IP 固定、证书验证、HTTPS 降级拒绝保持生效。

同一 host 共用行锁、每次底层 `_request_once` 的至少 2 秒节奏、robots 缓存和终态熔断；TLS 兼容握手重试也经过请求记账和节奏。最多 4 个不同 host 请求并发，同 host 等锁不占这 4 个全局槽位。robots 200 HTML、HTML 片段及重定向到 HTML 均拒绝。401/403/429、实际可见的中文/英文访问挑战、robots 拒绝、普通网络错误均停止该 host；后续行明确为继承阻断而非独立实测。

默认硬上限为全批 8000 次请求、1 GB 解码响应、90 分钟；单响应 2 MB、每行 60 秒、main 12 次实际请求、review 3 次实际请求。每次实际网络请求前先持久计数，读取响应时累计字节持久化，取消、超时、TLS/重定向失败不会撤销计数。行 deadline 同时受全批剩余时间约束。取消/进程中断的行保留 interrupted，相关 host 熔断，汇总不能标完整通过。

正文和原响应仅存仓库外私人目录；目录 0700、文件 0600，拒绝仓库内、含 symlink 的输出及 `..` 逃逸。原子写入、单 writer 文件锁、输入/代码/限制指纹避免并发覆盖或混合实现。resume 不重跑终态行，不重置计数、deadline、robots、上次请求时间或 host 熔断。CSV 对公式前缀做显示转义，JSON 保留原值；历史核验日期保留 checkedOn。

## RED / GREEN

使用 `/tmp/extrio-health-20261022/backend-venv/bin/python`，Python 3.12 隔离环境。先写离线测试，首次收集因尚无 A001 catalog 模块而 RED；接口到位后继续补充可执行的行为反例，以下 RED 均实际观察到：

- 17 项控制通过、4 项失败：详情候选非法端口和 HTTPS 降级仍发请求、代码变化可静默 resume、live 可降低节奏/放宽预算。
- CSV 历史日期遗漏：22 通过、1 失败；实际字段 checkedOn 未导出。
- 单 writer 缺失：25 通过、1 失败。
- redirect 端口和隐藏挑战模板误熔断反例失败；TLS 测试另有一次测试自身缺少 time import，修正后验证实际 TLS 兼容请求计数与间隔。
- 全批 deadline 未设置 stopReason：33 通过、1 失败。
- robots HTML 片段仍继续列表请求：35 通过、2 失败。

首批真实执行代码冻结前的命令：

```text
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_tender_catalog.py backend/tests/test_tender_catalog_network.py backend/tests/test_tender_source_adapters.py backend/tests/test_source_network.py -q
176 passed in 3.11s

/tmp/extrio-health-20261022/backend-venv/bin/ruff check scripts/tender_sources/catalog_run.py scripts/test-tender-catalog.py backend/tests/test_tender_catalog_network.py
All checks passed!
```

37 项网络执行器测试覆盖输入总分母、limit/resume、review 不请求详情、robots 共享及拒绝/HTML/重定向/片段、跨 host/端口/HTTPS 降级/private DNS、同 host 串行和底层请求节奏、最多 4 个 host 并发、TLS 兼容尝试、403/429/中文和 GBK 挑战、隐藏模板负控制、预算及重定向请求计数、全批与单行超时、未知异常、取消续跑、私人权限、仓库/symlink 拒绝、公式转义、checkedOn、代码/输入指纹及排他 writer。

## 嵌套隐藏样式回归

真实批次结束后，主执行者授权只修复 `_challenge` 对嵌套带 style 节点的 `AttributeError`。BeautifulSoup 的 `decompose()` 会清空子节点属性；正序遍历先移除隐藏祖先，再对已销毁后代调用 `node.get()` 会报错。实现只把 `[style]` 节点遍历改为倒序，使后代先处理，不修改网络、熔断、预算、解析门槛或执行策略。

先增加 7 项离线反例再改实现，实际 RED 为 **6 failed、1 passed、37 deselected**。失败覆盖 `display:none` / `visibility:hidden` 祖先嵌套 styled 后代、隐藏假验证码与页面可见验证码共存，以及 MockTransport 端到端正常行误报 error / 可见挑战未正确分类。正常非隐藏 styled 公告作为控制通过。

单行实现修复后的最终验证：

```text
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_tender_catalog.py backend/tests/test_tender_catalog_network.py backend/tests/test_tender_source_adapters.py backend/tests/test_source_network.py -q
183 passed in 2.74s

/tmp/extrio-health-20261022/backend-venv/bin/ruff check scripts/tender_sources/catalog_run.py scripts/test-tender-catalog.py backend/tests/test_tender_catalog_network.py
All checks passed!

git diff --check
(exit 0)
```

网络执行器套件合计 44 项。端到端反例证明：只有隐藏假验证码的正常列表不进入 error、后续同 host 行继续受控诊断；另有真实可见验证码时首行 restricted、后续同 host 行 inherited_block，且不额外发请求。

本修复仅做离线验证。首批真实执行代码保留在主执行者的私人 `executed-code` 归档；本单元没有读取或修改原始 ledger、trace 或 results，没有 resume 或重新请求来源。旧批次的工具错误及继承阻断必须保持原始结论，不能因离线修复转写为站点可采；已保存响应回放由主执行者另行审计记录。

## 验证边界

- 此单元没有执行真实外网请求；完整清单 dry-run、小批及真实批次由主执行者统一执行并另行记录。
- 静态候选解析只报告 `candidate_list` / `sample_readable`，不代表已签名采集规则、完整字段、分页、历史覆盖或原生运行通过。review 组不发详情请求。
- 不执行 JS、OCR、PDF 或附件，不跟随未知跨站原文；未知模板、访问受限和正文不全保持明确状态，不放宽网络安全或质量门槛追求通过率。
- 90 分钟 deadline 在 resume 中保持原始起点，包含两次执行之间的停顿，采取保守预算口径；不静默延长。
- 本单元不提交、推送、合并、发布或部署；不访问现有业务库，不调用付费模型，不修改现有服务或调度。
