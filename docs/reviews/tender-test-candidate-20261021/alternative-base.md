# 受支持基础镜像独立验证

任务 `TENDER-IMAGE-BASE`，2026-10-21 用户明确授权直接执行。基线为草稿 PR #49 的 `02c895a8d7be08c05a63af0b1116c2e6dfa5fe62`，不委派。目标是验证官方 Ubuntu 24.04 / 26.04 LTS 能否消除系统 LLVM/libxml2 的 CRITICAL 风险，同时保留已验证的 headless-shell/CUPS 精简边界。

## 执行合同

- 默认 `docker/backend.Dockerfile`、现有服务、业务源码、Python/Web 锁文件和数据合同不变。只增加独立 Ubuntu Dockerfile、基础镜像工作流、验证/比较工具、相应测试及本目录报告；可有界扩展既有镜像工具以复用测试与删除保护。
- 使用官方多架构镜像摘要、同版本 uv 和 Python 3.12，冻结应用依赖。noble 使用 Ubuntu 官方 Python 3.12 及其发行版安全回补，resolute 单独验证 uv 管理的 Python 3.12.15，不使用其不兼容的系统 Python 3.14。Ubuntu 与 PGDG 仓库发行代号必须一致，不混入 Debian、testing/unstable、手工替换共享库或强制删除依赖。
- 只安装官方 Playwright headless-shell；有界卸载 CUPS，保留 GBM/LLVM 图形能力。保留既有 Debian headless 对照，不将基线风险接受延伸到任何候选。
- 先用反例测试约束跨发行版比较、完整清单、镜像身份、平台与删除边界，再实现。新 HIGH/CRITICAL、可修复未处置高危、缺失扫描/能力/测试证据均阻止建议采用，不添加忽略、风险例外或 VEX。
- 在原生 amd64/arm64 CI 对照 Debian headless、Ubuntu noble/resolute。每个运行镜像进行完整未过滤扫描和断网浏览器/Canvas/WebGL/PDF 实测；只增加冻结 Python 测试工具的派生镜像执行相同采集、原文/PDF/EPS、网络边界、SQLite/PostgreSQL 16 完整备份恢复回归，零跳过。
- 全量主 CI、普通容器安装升级验证和既有精简工作流仍独立执行；不能以主机测试替代实际镜像验证。失败实验原样留存，不扩大白名单或绕过 TLS/安全检查。
- 仅使用合成夹具、临时内部网络和独立测试数据库；现有实例只做本地只读保留核验。公开证据仅含源码、依赖/镜像和合成测试结果，不上传业务数据库、密钥、原始公告或实例运行回执。
- 本次不合并、不发布、不推送镜像、不部署、不开来源调度、不重试采购网、不调用付费模型。完成状态为草稿 PR 的机器辅助验证，不是独立人工验收或发行授权。

## 上游依据

- [Playwright 支持平台](https://playwright.dev/python/docs/intro#system-requirements)包括 Ubuntu 24.04/26.04 的 amd64/arm64；锁定的 1.62.0 驱动也包含两版原生平台映射，无需升级浏览器依赖。
- [PostgreSQL 官方 Ubuntu 仓库](https://www.postgresql.org/download/linux/ubuntu/)支持 noble/resolute 的两个目标架构，客户端固定主版本 16。
- [Ubuntu CVE-2026-6653](https://ubuntu.com/security/CVE-2026-6653)和[Debian 状态](https://security-tracker.debian.org/tracker/CVE-2026-6653)用于核查系统 libxml2，不延伸为 Python lxml 内置库或整个镜像的安全结论。最终以实际安装包、完整扫描、动态链接和能力测试共同判断。
- [uv 官方 Docker 用法](https://docs.astral.sh/uv/guides/integration/docker/)支持从摘要固定的 distroless 镜像复制二进制；本实验保持 uv 0.12.23，与既有基线一致。

## 证据要求

每个候选保存实际镜像 ID/层、发行版与完整已安装包、运行时加载库、冻结锁文件哈希、完整扫描 JSON、零跳过 JUnit、跨发行版新增高危和可修复高危清单。比较基于组件/CVE，不以发行版包版本字符串改变伪称全部修复；扫描器对发行版的判定变化不等于源码级不可达证明。完成后在本页记录真实结果、CI 入口、残余阻塞和适用范围。

## 保留的失败

初始提交 `7cec20e95725a79dae23199ae326833cc2738f1c` 的[独立矩阵](https://github.com/iiwish/extrio/actions/runs/39544388744)在 uv 管理的 Python 上执行系统 pip 卸载时，被 externally-managed 保护拒绝。这是候选构建失败，不是能力或安全验证通过。候选保持 uv 管理的解释器完整，不删除管理标记、不使用 break-system-packages；pip 和所有内置组件仍进入完整扫描，不能隐藏其风险。该限制不修改默认 Debian 镜像的既有构建。

提交 `61954ed957e6629ca0706491c0357f161b1451c6` 的[完整矩阵](https://github.com/iiwish/extrio/actions/runs/39544914984)在两个原生架构均通过每镜像 246 项能力/双库回归，但安全门槛真实失败：noble 为 1 CRITICAL / 5 HIGH，resolute 为 1 CRITICAL / 8 HIGH。目标系统 `CVE-2026-6653` 已不在清单，LLVM 和 GBM 均保留；新 CRITICAL 来自受管理解释器自带 pip 的旧 certifi，另有 msgpack、setuptools、urllib3 可修复 HIGH。resolute 自带的 `/usr/bin/pebble` 还引入 3 条 Go 标准库 HIGH。这些候选不采用，没有风险豁免。noble 继续独立验证官方系统 Python 3.12，应用依赖仍冻结；这不是手工清理受管理解释器或更改包元数据。

## 实测结论

冻结参考提交 `2caaa414db6d30a83113db539d59818888974671` 的[替代基础镜像矩阵](https://github.com/iiwish/extrio/actions/runs/39545727389)完成全部四组原生验证。Ubuntu 24.04 官方 Python 方案的两组安全/能力门槛通过；Ubuntu 26.04 两组因真实新增高危保持失败，整个矩阵结论为 failure，不冒称全绿。

| 独立镜像 | amd64 / arm64 完整清单一致结果 | 结论 |
| --- | --- | --- |
| 未改默认 Debian | 400 条：1 CRITICAL / 63 HIGH / 154 MEDIUM / 174 LOW / 8 UNKNOWN | 原默认产物，不宣称修复 |
| Debian headless/CUPS 对照 | 373 条：1 CRITICAL / 61 HIGH / 137 MEDIUM / 170 LOW / 4 UNKNOWN | 既有精简继续通过，LLVM/GBM 保留 |
| Ubuntu 24.04 + 官方 Python | 47 条：0 CRITICAL / 1 HIGH / 30 MEDIUM / 16 LOW | 无新增高危、无可修复未处置高危，允许后续审查，不是风险接受 |
| Ubuntu 26.04 + 受管理 Python | 83 条：1 CRITICAL / 8 HIGH / 65 MEDIUM / 9 LOW | 新增 certifi、msgpack、setuptools、urllib3 和 pebble/Go 风险，拒绝采用 |

这些是扫描器按各发行版供应商状态生成的包告警记录数，不能把跨发行版差值直接当成修复 CVE 数量。完整未过滤报告、镜像身份、JUnit 和运行时记录保留于上述 Actions artifacts；关键版本、精确镜像 ID 及报告 SHA256 见 [alternative-base-results.json](alternative-base-results.json)。下载后已独立重算四组比较，结果与原 CI 回执一致。

### LLVM、Python 与能力

- Ubuntu 24.04 实际保留 `libgbm1 25.2.8-0ubuntu0.24.04.4`、`libllvm20 1:20.1.2-0ubuntu1~24.04.3`，系统 `libxml2 2.9.14+dfsg-1.3ubuntu3.10` 包含供应商修复，高于官方 `CVE-2026-6653` 修复版本 `2.9.14+dfsg-1.3ubuntu3.8`。不是删除 GBM/LLVM 或修改扫描元数据来消除告警。
- Ubuntu 24.04 使用官方 `python3.12 3.12.3-1ubuntu0.17`，实际基础解释器为 `/usr/bin/python3.12`；补丁由 Ubuntu 包回补，不把 3.12.3 字符串等同于未打补丁的原生 CPython 3.12.3。它与默认镜像的 3.12.15 不同，应用合同仍为 Python 3.12，所有冻结依赖不变。未安装系统 pip/venv wheel 包，也未修改受管理解释器或 PEP 668 标记。
- 两种候选都只安装官方 headless-shell、实际卸载 `libcups2t64`；不安装完整 Chromium，不添加 unsafe GPU 参数。实际启动路径、ldd、完整安装包和 Essential 标记均已核对。
- 两个原生架构的每个候选及其对照各执行 246 项镜像内定向回归，零失败/错误/跳过。范围包括 RestrictedBrowser/Crawl4AI、列表/详情/翻页、异步 DOM、原文/PDF/EPS、来源边界、SQLite 和 PostgreSQL 16 完整备份及空目标恢复，规则签名/凭据/Artifact 保留。
- 实际运行镜像的断网夹具验证 Canvas 与截图像素 `[180,30,60,255]`、可用 WebGL 像素 `[64,128,191,255]`，PDF 经正式子进程提取正文，扫描件仍拒收，与 Debian 对照一致。Python lxml 内置 libxml2 仍为 2.14.6，和系统库分开记录；有限夹具不等于全局不可达证明。
- 仅增加冻结 Python 测试工具的派生镜像不补回系统库。回归通过不是“所有网页行为永不回退”的保证，也不是独立人工验收。

### 全量门槛与边界

同提交的[完整主 CI](https://github.com/iiwish/extrio/actions/runs/39545727394)通过后端 1100 项、前端 278 项，以及 lint/build、生成类型、文档契约、打包和真实历史/Alpha/RC1 双库升级恢复回归。[普通容器验证](https://github.com/iiwish/extrio/actions/runs/39545727380)通过默认镜像 SQLite/PG16 隔离冷安装、鉴权/readiness 和完整后端/Web 扫描，Web 完整扫描为零。[既有精简矩阵](https://github.com/iiwish/extrio/actions/runs/39545727384)的两个原生架构继续通过，各对照与 headless 镜像 246 项，减少的 27 条仍全部对应 CUPS 真正移除，没有新增。

Ubuntu 24.04 的唯一 HIGH 为 `NLTK 3.10.3 / CVE-2026-81726`，无上游修复版本，保持 open；其他 MEDIUM/LOW 也未忽略。默认镜像、业务源码、锁文件、现有数据/断点/原始证据和来源调度均未改变。未触发发布方请求或付费模型调用。受限实例保留核验仅留本地，不上传到公开 PR。

建议的后续候选方向是独立 Ubuntu 24.04 官方 Python 方案；本任务不切换默认镜像、不采用 Ubuntu 26.04、不接受任何残余风险。草稿 PR 保持暂停合并/发布/部署，后续正式选择和发行授权仍需明确决定。
