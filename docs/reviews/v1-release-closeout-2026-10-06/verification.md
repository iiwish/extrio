# 发布收尾执行与复核记录

工作目录 `/Users/iiwish/self/extrio`，日期2026-10-06。原始日志位于受忽略的 `backend/data/v1-release-closeout-20261006/`，下文日志名相对该目录。测试口令不写入本记录。不得用本文批准发布或接受风险。

## 隔离与对象

自有PG16容器 `extrio-release-closeout-pg16-20261006` 仅绑定 `127.0.0.1:55438`，不读取其他项目数据库URL。G4 API8058/8059、Vite生产预览5208/5209、随机来源/HTTPS协议模型/Webhook服务分别隔离。旧G4实例在lxml同步后关闭，新 `g4-qa-*-frozen` 用全新SQLite/专属PG数据库复验。只使用协议fixture，不调用付费模型。

Docker采用自有 `extrio-e2e-closeout-*` 项目与18058/18059/18088/18089端口；脚本拒绝接管既有项目，trap清理容器/网络/卷。最终镜像、产品指纹和有效计数见 [report.md](report.md)，重复执行不累加。

## 命令与结果

| 命令/检查 | 退出与观察 | 原始日志 |
| --- | --- | --- |
| `pytest …/test_backend_image_contract.py -q`，旧Dockerfile | 1，2 failed；PG16客户端单项更新后为1 failed/1 passed | `image-contract-red.log`、`pg-client-contract-red.log` |
| `vitest run app-shell/items-page.ui/home-page`，语义实现前 | 1，3 failed/16 passed | `named-roles-red.log` |
| 最终全量 `pnpm --dir web test` | 0，265 passed/42文件，33.42s | `frontend-test-frozen.log` |
| 最终 `EXTRIO_TEST_DATABASE_URL=… uv run --project backend pytest -c backend/pyproject.toml backend/tests -q --junitxml=…` | 0，847 passed/0 skipped，231.77s | `backend-test-frozen.log`、JUnit |
| lxml实际解析器边界，6.1.2 | 1，外部DTD回调被捕获；1 failed/1内部实体正控制passed | `lxml-red.log` |
| `uv lock --project backend --upgrade-package lxml`、`uv sync --locked --python 3.12` | 0，6.1.2→6.1.3，仅定向patch更新 | `lxml-lock-update.log`、`lxml-sync-final.log` |
| `pytest test_lxml_boundary.py test_backend_image_contract.py -q`，最终 | 0，4 passed | `lxml-and-image-green-final.log` |
| Ruff、`pnpm --dir web lint/build/api:generate`、生成类型git diff检查、`uv build` | 0，类型无差异；sdist/wheel完成 | 真实工具输出、`frontend-build-release-final.log`、`api-generate.log`、`package-build-frozen.log` |
| `g4-browser-qa.py --instance …/g4-qa-*-frozen --web http://127.0.0.1:520*` | 两库各0、136组合、真实审核运行交付/导出 | `browser-*-lxml-frozen.log` |
| 原 `live-api-probes.py` 与 `browser-audit.py --axe …/axe.min.js` | 各0；每库58/58与45扫描0违规 | `api-*-lxml-frozen.log`、`a11y-*-lxml-frozen.log` |
| `keyboard-qa.py`，两库两语言四桌面 | 各0，32键盘用例/40详细扫描，无确定违规/generic命名反例 | `keyboard-*-lxml-frozen.log` |
| `verify-compose.sh`，显式自有镜像/端口；PG指定 `EXTRIO_E2E_COMPOSE_FILE=…/compose.postgres.yaml` | 各0，最终冻结镜像SQLite/PG16 health/setup/login/logout | `compose-*-frozen-lxml.log` |
| 原镜像PG17.11完整恢复 | 1，PG16不识别 `transaction_timeout`；没有修改归档掩盖错误 | `image-recovery-red.log` |
| 最终非root镜像 `image-backup-smoke.py`，只读挂载脚本、仅访问自有PG16 | 0，两库完整数据库/Artifact/签名key/加密凭据恢复；自有临时库finally删除 | `image-recovery-frozen.log` |
| 最终镜像、`--network none`、真实Worker benchmark/RestrictedBrowser | 各0，14页8accepted及Chromium200，基础pip和安装/显示工具不存在 | `image-pipeline-frozen.log`、`image-browser-frozen.log` |
| 最终镜像调用两项 `test_lxml_boundary.py` 函数 | 0，6.1.3与内置2.14.6，外部参数实体拒绝/内部实体保留 | `image-lxml-frozen.json` |
| 官方registry `pnpm audit --json` | 0，全部等级0、包括dev | `web-audit.json` |
| `pip-audit --path …/site-packages` | 1，只有NLTK无补丁告警；不当作通过 | `python-audit-frozen.json` |
| 固定摘要Trivy，最终镜像原HIGH/CRITICAL可修复门禁 | 两镜像0；完整发现扫描375条，其中OS374、NLTK1，无可修复项 | `backend-frozen-full/gate.json`、`web-frozen-gate.json` |
| Trivy fs，当前产品文件快照，vuln/secret/include-dev-deps | 0，NLTK1/Web0/secret0；0是发现命令退出，不是零漏洞 | `source-frozen.json` |
| Trivy fs `--scanners secret --exit-code 1`，最终暂存候选1517文件，含显式归档日志 | 0，0 secret；独立补充证据扫描，不替代冻结依赖漏洞扫描 | [staged-secrets.json](evidence/staged-secrets.json) |

扫描器固定为Trivy0.75.0摘要 `sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa`，同一cache串行扫描。快照来自当前 `git ls-files --cached --others --exclude-standard`，不是旧HEAD；不含.env、虚拟环境、node_modules、运行数据库或私有QA目录。全部依赖告警和低等级/unknown扫描记录保留。

## 中间结果与证据边界

- 供应商弹窗实测4.06:1，修复前确实RED；补充扫描等待实际CSS动画完成，不放宽对比度门槛。初版键盘脚本遗漏“编辑字段”前置步骤、随后在模型读取禁用态尝试focus；补齐真实前置与enabled/focus断言，不删除用例。初版多加了需求列表live status，全量测试检出重复状态；装饰骨架改为aria-hidden，原测试不变。
- lxml首次异步lock命令尚未完成时提前sync读到了旧锁文件，边界再次RED；等待lock完成、确认真实6.1.3后重新同步并复验。该中间结果不计为GREEN。
- Node/jsdom既有navigation warning、TypeScript6/openapi-typescript7 peer范围提示保留；未改变TypeScript或降低检查。
- 图像source index可因BuildKit attestation时间变化而变化；全部构建完成后冻结标签，再扫描和运行最终容器。不能把中间Image ID当成最后对象。
- 无新增独立人工读屏器、Safari/Firefox、真实付费模型、生产来源/证书、长期SLA或性能优化证据。旧PG17生成归档没有被虚假签出为PG16兼容。
- Git全范围whitespace检查识别出RQA1原始统一diff的合法单空格上下文空行；差异以 `gzip -n` 无损归档、解压后cmp一致，原始副本保留在忽略目录。没有修剪diff内容、增加whitespace例外或降低代码检查。归档的测试输出因全局*.log忽略，提交时只显式force-add已审查的证据日志，不修改全局ignore。
- 提交的六份展示日志仅机械去除行尾空格/Tab和文件末尾多余空行；测试内容、断言、计数和结果不变。逐字节原始副本保留在上述忽略目录的 `raw-evidence-logs/`，原始与展示版SHA-256见 [log-normalization.json](evidence/log-normalization.json)。

## 交接规则

产品/技术审查和安全例外保持待决定。送审只提交、推送和创建未发布候选PR；精确head的远程checks由GitHub记录，不沿用PR#34或RC检查。main合并、正式tag/release、registry发行与生产部署没有在本执行包取得授权。

清理只针对自有测试资源：G4及preview、临时PG数据库和容器、Compose容器/网络/卷、测试镜像标签、scanner cache/源码副本、QA口令与浏览器会话。其他项目服务不修改，没有全局prune。

实际清理：旧G4 supervisor19959/19965及冻结26368/26379正常结束，临时PG库finally删除；preview19989/20006结束143。停PG前查询无 `extrio_%` 库，容器stop/rm-v后专属匿名卷 `5870da9fd8432a28474b3ed562d0ff822c903674e10c64945736f4485fc8e394` 确认不存在。9个固定测试端口无监听；8个QA口令/浏览器会话文件删除。自有镜像标签、scanner cache/源码副本清理。三个既有其他项目容器保持原状，原始测试日志与合成SQLite证据保留在忽略目录。
