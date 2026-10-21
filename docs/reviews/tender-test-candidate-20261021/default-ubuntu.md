# Ubuntu 默认镜像与 NLTK 风险处置

任务 `TENDER-DEFAULT-UBUNTU`，2026-10-21 用户明确授权执行，基线 `fdc6fa852e7877d643f347174172b9f51b0cab01`。直接执行，不委派。采用已通过双架构验证的 Ubuntu 24.04 官方 Python 3.12/headless-shell/CUPS 精简方案作为默认构建；既有手动实例不切换、不重启。

## 执行合同

- 允许修改默认/对照 Dockerfile、原生镜像验证工具及工作流、相关测试、安装说明和本目录脱敏证据。Python 依赖只有经官方来源核对和独立反例验证的 NLTK 处置才可修改；不改业务字段/日期/身份/指纹合同，不改用户数据库、断点或采集证据。
- 保留官方 Ubuntu/uv 多架构摘要，使用 Ubuntu 官方 Python 3.12 安全回补和 noble-pgdg 客户端 16，冻结应用依赖，非 root、下载/网络边界和质量拒收规则不变。只安装 headless-shell，有界卸载 CUPS，保留 LLVM/GBM，不改系统包元数据或强制删除依赖。
- 默认构建必须落到运行目标，验证目标只增加冻结 Python 测试工具；默认镜像不得携带开发依赖。历史 Debian 配方独立保留为不发布的研究对照，Ubuntu 26.04 的失败记录保留，不采用其受管理 Python/pip/pebble 方案。
- 先执行默认镜像/工作流合同的失败测试，再实现。完整扫描保留全部等级、未修复项与镜像身份；NLTK 无官方稳定补丁时仍 open，不能用“当前未调用”或版本号改写宣布修复，不删除 dist-info 或加忽略/VEX。
- 用户明确选择保留 NLTK 稳定依赖，3.10.4-rc1 源码仅作隔离评估，不修改正式锁文件。第三方包/模型不安装到现有实例，不请求招投标发布方或模型服务。
- 原生 amd64/arm64 验证默认镜像的断网截图/Canvas/WebGL/PDF、列表/详情/翻页/原文/EPS、网络边界与 SQLite/PG16 完整备份恢复。镜像内升级使用 git archive 导出的固定历史代码及合成数据库，不挂载整个工作区、真实数据或 .git，不连接现有数据库。
- 完整主 CI、生成类型/打包和真实历史/Alpha/RC1 双库升级恢复独立执行；默认容器的双库冷安装、鉴权/Worker readiness、后端/Web 完整扫描全部复验。失败保留，不降低门槛或跳过测试。
- 只读核验现有实例和原始数据库保留情况，回执留受限本地目录；公开 PR 仅更新源码、依赖/镜像与合成测试证据，不上传数据库、密钥或原始采集证据。
- 本轮不合并、不发布、不推镜像、不部署、不开来源调度、不重试采购网、不调用付费模型；完成后保持草稿 PR。

## NLTK 官方状态

[官方公告](https://github.com/advisories/GHSA-8mgp-746c-j5xp)仍列 `<=3.10.3` 受影响、无 patched version。2026-10-21 官方 PyPI 元数据的稳定版为 3.10.3，无 3.10.4 发行文件；[上游 v3.10.4-rc1](https://github.com/nltk/nltk/releases/tag/v3.10.4-rc1)为源码预发布，含广泛路径/下载/解析安全变更。Crawl4AI 0.9.5 的官方依赖仍要求 NLTK，单纯升级 Crawl4AI 不会消除本风险。具体采用结论必须来自包来源、受影响 API 的实际攻击反例和全量兼容性，而非扫描版本范围之外就视作安全。

## 证据与完成条件

保存默认运行镜像与层身份、系统/Python/PG 版本、锁文件哈希、完整漏洞清单和 JUnit；新 CRITICAL/HIGH、可修复未处置高危、能力变化或任何跳过均阻止采用。NLTK 原 HIGH 未接受也不忽略。默认构建切换只是代码变更，不是替换现有容器、主机系统或上线。历史实验报告保留其冻结来源与失败结论，不冒充本轮默认镜像证据。

## 验证结果

冻结源码 `631cf6771bfa1548f3b7d84dd6e37b42480eb477` 的[完整主 CI](https://github.com/iiwish/extrio/actions/runs/39554200962)、[默认镜像双库冷安装与完整扫描](https://github.com/iiwish/extrio/actions/runs/39554201000)、[默认原生镜像/升级与隔离评估](https://github.com/iiwish/extrio/actions/runs/39554200976)、[历史 Debian 精简对照](https://github.com/iiwish/extrio/actions/runs/39554200960)均成功。下载后独立核对镜像身份/层、能力、JUnit 和完整清单，结果与原 CI 一致。

| 项目 | 实测 |
| --- | --- |
| 默认构建 | Ubuntu 24.04 LTS / 官方 Python 3.12 安全回补 / noble-pgdg PG16；默认最终目标继承运行层，不含 verification 开发工具层 |
| 两架构完整后端扫描 | 各 47 条：0 CRITICAL / 1 HIGH / 30 MEDIUM / 16 LOW；全部保留，无忽略。Web 完整扫描为零 |
| 唯一 HIGH | `NLTK 3.10.3 / CVE-2026-81726`，仍 open，无稳定补丁，未接受风险 |
| 原生镜像内回归 | amd64/arm64 默认镜像各 255 项，零失败/错误/跳过；历史 Debian 对照与 headless 精简也各 255 项 |
| 安装与升级 | 实际默认镜像双库隔离冷安装、鉴权和 Worker readiness 通过；镜像内执行固定历史、Alpha、RC1 的 SQLite/PG16 升级与匹配源程序备份回滚，以及双库并发空库迁移，只处理合成实例 |
| 采集/文档与恢复 | 浏览器列表/详情/翻页、异步 DOM、原文/PDF/EPS、网络边界、扫描件拒收、完整双库备份/空目标恢复、凭据/签名/Artifact 保留通过 |
| 全量源码回归 | 后端 1104 项，前端 278 项；lint/build、生成类型、契约、打包与源包安装通过 |

运行镜像仍保留 LLVM/GBM，CUPS 真正移除，仅安装 headless-shell。Canvas/截图和 WebGL 像素、正式 PDF 子进程提取和扫描件拒收与对照相同。锁文件、业务源码、迁移及 Web 依赖没有修改。精确镜像 ID、锁文件与报告哈希见 [default-ubuntu-results.json](default-ubuntu-results.json)；完整原报告留于对应 Actions artifacts 和受限本地目录。

Ubuntu 26.04 保持拒绝采用；其失败证据和手动重现入口保留，不再作为 PR 的默认候选矩阵。PR 持续验证实际默认 Noble 配方，不是跳过 Noble 扫描或豁免旧镜像风险。默认镜像代码切换不表示已发布镜像或替换现有实例。

## NLTK 隔离评估

按用户明确选择，`backend/pyproject.toml` 与 `uv.lock` 保留稳定依赖，预发布源码不写入运行镜像。固定官方 tag `v3.10.4-rc1` 的提交 `ba6b259aa94a85168c031ad60e4072538c30b513`，下载归档 SHA256 为 `2d401f212e7d872d9349bd43dedcab08bda54a807ce99957569725b567714464`，执行前严格校验。

两个原生架构都在非 root、只读根文件系统、无网络、无额外 capability 的容器内加载只读挂载的预发布源码；HOME 使用新建 tmpfs，不挂载宿主用户目录、数据库或密钥，也不安装包/模型。结果为：

- 五个受影响 API 的绝对路径、`..`、符号链接逃逸共 15 次真实调用均由 PermissionError 拒绝；另有 3 次独立 pathsec 负控制，外部 canary 始终未变。
- AveragedPerceptron 模型和 maxent 参数的两项合法读写往返通过，避免把所有读写失效当安全成功。
- `TransitionParser.train` 仅核对源码的 `pathsec_open` 写入路径；未安装可选 scikit-learn，未执行真实训练，不声称该路径已经动态验证。
- 上游源码自报版本是 `3.10.4`，但 tag 仍是 RC，没有对应稳定 PyPI 包。不能因为版本超出扫描器受影响范围就宣布漏洞关闭。

这是有限安全反例评估，不是完整 NLTK 资格认证、预发布包全量兼容性验证或生产风险接受。稳定运行镜像中的 NLTK HIGH 持续保留，官方稳定包和公告状态仍须跟进；不加 VEX、忽略或第三方源码补丁。

## 系统边界与保留

业务规则不绑定 Ubuntu 品牌；容器用户态仍包含 Python 原生扩展、Chromium、LLVM/libxml2、证书和数据库工具，其包版本、ABI 和安全回补属于运行依赖。Docker 固定这些用户态依赖，宿主或 Docker VM 内核、CPU 架构与网络边界仍有影响。修改基础镜像不要求更换用户电脑系统，也不修改数据库内容。

本地只读保留核验通过，原始数据库、既有数据/断点/文件证据保持，来源调度关闭且无额外模型调用。回执不上传公开 PR。草稿保持，不合并、不发布、不部署；机器辅助验证不是独立人工验收。
