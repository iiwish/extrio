# 独立镜像依赖精简验证

任务 `TENDER-IMAGE-SLIM`，2026-10-21 用户明确授权执行。直接执行，不委派。基线为草稿 PR #49 的 `de99c756688b01ee65c20b5900f65c50cda5aaaa`，默认构建、业务代码、数据库及来源合同保持不变；不合并、不发布、不部署、不开调度、不忽略告警。

## 范围与计划

1. 使用同一冻结依赖的独立基线镜像，核对 LLVM/libxml2 删除计划及 headless-shell/CUPS 精简目标；不修改正式 Dockerfile 的默认产物。LLVM 删除计划会移除必需的 libgbm1，保护检查已阻止实际删除，此路径不采用；CUPS 独立精简，不联动删除 LLVM。
2. 先验证删除计划与浏览器路径保护的失败用例，再实现有界删除。只允许明确列出的图形依赖，禁止 Essential 包、强制删除依赖、清除扫描数据库或混用发行版。未知删除计划立即失败。
3. 在原生 amd64/arm64 隔离 CI 中，分别验证基线及 headless-shell 精简，同时保存 LLVM 的只读阻塞计划。运行网络与外网隔离，只允许容器内部 PostgreSQL 16 和本机合成 HTTP 夹具，不请求发布方或模型。
4. 在实际运行镜像验证截图、PDF 文本解析、扫描件拒收、Canvas/图形状态及原生加载库；使用仅增加冻结 Python 测试工具的派生镜像复跑受影响的真实浏览器采集、官方原文/PDF/EPS、网络边界和双库完整备份恢复测试，不向测试镜像补回被删除的系统包。
5. 主 CI 仍执行完整后端/前端回归、升级、打包和安全检查；独立镜像保存完整未过滤扫描、已有可修复高危门槛和能力对照。不能用定向容器测试代替主 CI，也不能用主机测试替代镜像内验证。

## 文件边界

允许独立 `docker/backend-slim.Dockerfile`、`scripts/prune-image-runtime.py`、镜像核查/隔离验证工具、相应测试、Container verification 工作流及本目录脱敏报告。核心业务及冻结 Python/Web 依赖无预期修改。沿用发布暂停状态，不引入风险例外、VEX 或告警忽略。

本地现有实例只运行只读保留核验；数据库、密钥、原始公告和真实运行证据不提交。独立测试只用合成数据、临时数据库/网络及唯一命名的测试容器，清理仅针对本轮资源。

## 验收与停止条件

- 删除前后 dpkg 与实体文件一致；实际删除包必须落在允许清单且不含 Essential。
- 所有既有 headless 调用保持工作；不新增 unsafe GPU 参数、禁用安全边界或改用联网浏览器安装兜底。
- 基线与精简镜像的固定能力结果一致；不以 PDF 文件非空替代正文解析成功，扫描件仍拒收。
- 候选镜像内定向回归无失败/跳过；双库完整备份、空目标恢复、密钥/签名/证据保留不回退。完整主 CI 独立通过。
- 完整扫描保留所有等级和未修复项；告警减少必须对应组件真正移除，没有新增未解释高危。失败实验保留，不冒称通过。
- 只有有完整证据的实验能建议后续采用；本任务不切换现有服务或默认发行镜像。

## 执行结果

LLVM 删除计划已核实不可采用：两种架构均会连带移除 `libgbm1`、`libgl1`、`libglx0`，其中 libgbm 是实际浏览器的必需链接库。保护检查在 apt 真正删除前失败，没有扩大白名单或改写依赖元数据。系统 libxml2/LLVM 的漏洞保持 open，这不是精简成功。

### 原生对照

提交 `271e1944a16926808e3655f7e592cc75765febae` 的 [Independent image pruning](https://github.com/iiwish/extrio/actions/runs/39540258071) 两个原生架构均通过。每架构的基线与 headless 候选各执行 246 项镜像内定向回归，均为 0 失败、0 错误、0 跳过，四组共 984 次测试执行，不是 984 个独立用例。

| 对照 | amd64 / arm64 一致结果 |
| --- | --- |
| 实际移除 | 完整 Chromium 目录及 `libcups2t64`；没有移除 LLVM/libxml2、GBM、Essential 或 PostgreSQL 客户端 |
| 浏览器 | 实际启动 Playwright headless-shell；Crawl4AI/RestrictedBrowser、列表详情、翻页、异步 DOM、原文/PDF/EPS 和固定来源夹具通过 |
| 图形 | Canvas 绘制与截图像素为 `[180,30,60,255]`；WebGL 可用，像素 `[64,128,191,255]`；与基线相同，无新增 unsafe GPU 参数 |
| PDF | 实际浏览器生成 PDF 后经正式隔离子进程提取文本；扫描件仍拒收。原始日期、转载日期、页脚例外及不完整正文质量门槛通过 |
| 备份恢复 | 实际镜像的 pg_dump/pg_restore 和 SQLite 全量备份、空目标恢复、规则签名、凭据和 Artifact 保留用例通过；仅连接临时 PostgreSQL 16 |
| 完整扫描 | 基线 400 条：1 CRITICAL / 63 HIGH / 154 MEDIUM / 174 LOW / 8 UNKNOWN；候选 373 条：1 CRITICAL / 61 HIGH / 137 MEDIUM / 170 LOW / 4 UNKNOWN |
| 告警差异 | 减少的 27 条全部对应真正卸载的 libcups 包，包括 `CVE-2026-34980`、`CVE-2026-55453` 两项 HIGH；无新增告警。高等级独立 CVE 从 23 个变为 21 个 |

完整扫描保留所有等级、未修复项及状态；直接从完整清单拒绝新增高危和存在修复版本的未处置高危，没有给独立工作流添加 ignore-unfixed 过滤。扫描的 `Metadata.ImageID`、DiffIDs 与受测镜像配置/层逐一匹配；Trivy 的 ArtifactID 是扫描缓存身份，不替代镜像 ImageID。镜像 ID 和报告哈希见 [image-pruning-results.json](image-pruning-results.json)。

同提交[完整主 CI](https://github.com/iiwish/extrio/actions/runs/39540258063)通过后端 1088 项、前端 278 项，以及 lint/build、升级、打包与契约检查。后续仅验证保护/文档提交仍执行独立完整检查，不挪用本次结果。

### 保留的失败

- 初始 BuildKit 不提供 `/.dockerenv`，构建保护阻止执行；工具采用显式一次性构建标志、Linux/root 和固定镜像路径组合核验，不放开删除计划。
- 本机合成 PDF 的正文不足和字体连字曾触发质量拒收/夹具断言；调整的只有夹具正文及断言 NFKC，正式解析和拒收规则未变。
- 临时 PG 的 Unix socket 曾在初始化阶段短暂就绪后退出，测试正确失败；改用最终 TCP readiness，不跳过 PG 用例。
- [LLVM 真正删除前的失败运行](https://github.com/iiwish/extrio/actions/runs/39539545161)证明依赖冲突，白名单保持拒绝，不宣称 LLVM 精简成功。
- [普通容器验证](https://github.com/iiwish/extrio/actions/runs/39540258035)发生 Alpine 官方仓库 TLS/APKINDEX 下载失败。失败保留，不使用 `--force-missing-repositories`、关闭 TLS 或沿用旧镜像绕过；最终提交重新核验既有完整容器流程。

### 适用边界

实验未更改默认 `docker/backend.Dockerfile`、业务源码、冻结依赖、字段/身份/日期合同或现有服务；也未上传或操作业务数据库、密钥和原始公告。仅增加测试工具的派生镜像不安装系统包或补回被移除的库，正式运行镜像另作完整扫描和能力验证。受限实例的只读保留回执单独留在本地，不追加内部明细到公开 PR。

候选只覆盖 Extrio 现有 headless 调用，不承诺手动 headed、扩展或显式完整 Chromium channel 的使用。实验基于分层基线，文件移除不代表历史层或下载体积变小；本轮不声称制品体积优化或正式镜像已切换。

LLVM/libxml2、NLTK 及其余告警继续 open。默认镜像仍为 1 CRITICAL / 63 HIGH；独立候选为 1 CRITICAL / 61 HIGH，均未获得风险接受。后续需受支持上游补丁或独立基础镜像方案，不能破坏 GBM 依赖或降低浏览器能力来清空告警。PR 保持草稿，不合并、不发布、不部署、不开调度；机器辅助验证不等于最终人工验收。
