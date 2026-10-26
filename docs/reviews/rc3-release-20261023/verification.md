# RC3 预发布与制品核验

任务：`RC3-RELEASE-20261023`。制品核验：2026-10-23；附件公开：2026-10-26（Asia/Tokyo）。
状态：RC3 已预发布；真实制品、签名、完整扫描和摘要安装通过，三份脱敏回执已公开并完成下载哈希核对。文档回执与其对应 PR/主干检查分别记录；不是正式稳定版签收或部署。

## 源码与发行身份

- 基线：已合并 #50、#51 的 main `2d4fa91f4df68e66ecafd097ea20a9d82e6b4f34`。
- 发行准备 [PR #52](https://github.com/iiwish/extrio/pull/52)：head `67c4fb8a84a1b12da9ea68f96a7c95eb9073e610`，正常 squash 合并为 `4f3929202d65601ced4ace3656eb726c64287459`。两个提交的文件树一致。
- [v1.0.0-rc.3 预发布](https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.3)于 2026-10-23 19:33:33（Asia/Tokyo）创建，`prerelease=true`、`draft=false`。标签对象 `a481f40e8d53eb53919b8e82da661271e351db5b` 解引用为上述实际 main 源提交；既有标签未移动。
- Python/Web 为 `1.0.0rc3` / `1.0.0-rc.3`。API 合同、schema 014、运行行为和冻结依赖不变；uv lock 仅更新项目自身版本。发行后的文档提交不改变已发布源提交、标签或制品。

## 准备验证

版本/文档回归先在旧元数据上取得 **6 failed / 1 passed**，最小实现后版本、wheel、docset 与 release-gate **26 passed / 0 skipped**。锁校验、Ruff、manifest 和空白检查通过。独立 diff 复核未发现阻断 P0/P1/P2；结构化比较确认依赖不变，旧 RC1/RC2 与历史证据未改写。

本地前端从候选提交导出到独占临时源码，使用冻结依赖安装，**43 文件 / 286 passed**；类型重生成与仓库一致，lint/build 通过。源码锁、临时源码锁和实际安装锁 SHA256 均为 `842b9c29d4334c3173af033ba88798fe3392898fd6c2a60e4c1c415862f6e7ab`。未重装用户共享 `node_modules` 或修改 `backend/.venv`。

本地构建环境中止保留：wheel 初始 cache 无写权限、离线临时 cache 缺 hatchling，补齐隔离构建缓存后完整测试通过；pnpm 初始无 TTY 自动依赖检查和命令参数准备未执行测试，最终独占临时源码的实际测试已完整执行。这些不是远程 CI 重跑或被跳过的测试。

PR 精确 head 的首次 [CI](https://github.com/iiwish/extrio/actions/runs/39935246327)、[Container](https://github.com/iiwish/extrio/actions/runs/39935246233)、[原生双架构](https://github.com/iiwish/extrio/actions/runs/39935246251)和[镜像裁剪](https://github.com/iiwish/extrio/actions/runs/39935246325)全部成功后才转 Ready 并正常合并；没有管理员绕过、auto-merge 或保护规则变更。

## 实际发行源门禁

以下结果均绑定 `4f3929202d65601ced4ace3656eb726c64287459`、首次运行，不使用 PR 事件结果替代实际 main 验证。

| 验证 | 实际结果 |
| --- | --- |
| [main CI](https://github.com/iiwish/extrio/actions/runs/39936649256) | push，后端 **1523 passed / 0 skipped**，前端 **286 passed / 0 skipped**；类型、Ruff、manifest、wheel 和包内 OpenAPI 通过 |
| [main Container verification](https://github.com/iiwish/extrio/actions/runs/39936649414) | push，SQLite/隔离 PG16 安装和镜像安全门禁通过 |
| [main noble 原生双架构](https://github.com/iiwish/extrio/actions/runs/39936691181) | workflow_dispatch，amd64/arm64 默认镜像内各 **258 项**，零失败/错误/跳过；浏览器/PDF/EPS、网络负例、完整备份及固定历史/Alpha/RC1 双库升级回滚通过 |
| [RC3 发行工作流](https://github.com/iiwish/extrio/actions/runs/39938028391) | RC3 标签 push，verify/publish 成功；四组含未修复项的 HIGH/CRITICAL 扫描、签名/provenance、晋升前重验及预发布创建成功 |

原生 artifact 独立下载并验证 GitHub archive digest、精确 run/SHA、架构、运行版本、锁、能力探针及真实 JUnit。RC3 锁 SHA256 为 `86b0ba492b75557bdd9e0cbe26ba0c82dec212a79d04cec21ef53271efbbfd11`。后端唯一测试 warning 为既有 Starlette TestClient/httpx 弃用提示；没有过滤或计作跳过。

## 真实发布制品

| 镜像 | 已验证不可变索引 |
| --- | --- |
| backend | `sha256:c35097886b6640f725c60686a4d9050b8db0885a8888cb2bb876e5ff2c66f10c` |
| web | `sha256:9c477c019548d08b67d1f9e90faa3908af82e9132d7d86b16cb58a2b9076abb5` |

两个镜像的版本标签与 `sha-4f3929202d65601ced4ace3656eb726c64287459` 标签指向同一各自索引，平台精确包含 `linux/amd64`、`linux/arm64`。cosign 和 GitHub attestation 独立核验真实摘要、`release.yml@refs/tags/v1.0.0-rc.3` 身份、GitHub OIDC issuer、精确源 SHA/ref 与托管 runner，未只采信工作流成功状态。

四个平台使用注册表原始发布载荷，验证平台 manifest、配置摘要与每层 rootfs diff ID 后扫描 Docker archive；没有本地重建或只用 SBOM 代替完整文件扫描。包含未修复项、全部严重度，未启用忽略文件。后端每架构 **0 CRITICAL / 0 HIGH / 30 MEDIUM / 16 LOW**，Web 两架构全部为零；实际后端告警集合与对应原生候选一致，均无扫描器列出的修复版本。

与 RC2 冻结清单相比，新报告包含 `CVE-2026-88648`，不再报告 `CVE-2026-85091`；不把告警消失宣称为代码修复。新 GnuTLS 条目保留扫描器的 Ubuntu MEDIUM、Red Hat CVSS 7.4、affected 和无修复版本信息。[Ubuntu 官方记录](https://ubuntu.com/security/CVE-2026-88648)于 2026-10-22 更新，优先级 Medium、Ubuntu CVSS 3.7、Noble 修复延期；攻击前提涉及受控下级 CA 与证书约束验证。未认定不受影响或误报，不修改既有 HIGH/CRITICAL 门槛，不新增豁免，不宣称零漏洞。

## 发布摘要安装

在本机 `linux/arm64` OrbStack 使用上述已验签、复扫的发布索引摘要执行 `scripts/verify-compose.sh --image-only`。SQLite 与 PG16 分别使用独占 UUID 项目、loopback 端口、新合成账号与新临时卷，验证空实例迁移、ready、鉴权初始化/登录态、受保护读取、Web 页面与退出拒绝。未使用本地重建镜像，也未访问既有业务库。

两次安装均成功，项目容器、卷、网络和额外离线 runtime 探针容器均已清理；原有三个容器 ID、启动时间及重启次数与执行前一致。其他项目或并发出现的非本任务资源不认领、不清理。

实际发布运行包为 `1.0.0rc3`、锁匹配发行源；离线浏览器 canvas/WebGL 像素、文本 PDF 与扫描 PDF 拒收通过。发布摘要双库安装只证明本机 ARM64 的限定鉴权安装旅程；双架构原生专项属于独立证据，不冒称四组发布摘要安装或完整用户旅程。

## 回执与失败保留

最终回执汇总的首次尝试在前端 CI 摘要解析处失败关闭：GitHub CLI 输出将颜色控制符呈现为字面 `^[[...m`，原解析器只归一化实际 ESC，未生成成功回执。该次 25 条只读命令全部 exit 0，真实 CI/发行、扫描和安装没有失败或重跑；原代码、命令回执与原始 CI 日志哈希保留在本轮私有目录。

聚合器仅增加实际 ESC 与字面 caret 颜色标记的归一化，真实日志及失败/跳过/错总数/重复摘要等 **15 项离线回归**通过；独立 AST/diff 审查确认物理验证方法、安全门禁和工具摘要不变。原聚合器 SHA256 `98af6e6a788aa70dfc868754cfab77f679f23473aaf4c6052327dd3e31a4d0bf` 和首轮回执完整保留；修复版 SHA256 为 `248b6621062eb806e333a4a323a43d34c58bb08137c40914a1a8d6fdc41e7296`。

经独立审查后，主执行者手动调用独立 `receipt_reviewed` 命名空间，只重新读取元数据/日志和汇总本地回执；未重跑 CI、扫描、签名或安装。汇总成功，原始私有发行回执 SHA256 为 `77b0ff93e271dd4eebe1443fa17b502b25d5ade8184412e85d3907fe74fbb428`。

首次上传三份 JSON 被自动审核拒绝，原因是公开 Release 将披露 CVE、组件版本和制品核验元数据，须取得用户对披露范围的明确确认。授权前没有重试上传或改用其他渠道，原文件保留在本机受限目录。公开版仅移除回执的两处本机工具路径，验证结论、漏洞条目和原证据哈希不裁剪。

用户于 2026-10-26 明确授权评估三份文件，未发现公开阻断风险即公开。主执行者与独立复核均未发现凭据、个人信息、业务内容、原始采集内容、工作站绝对路径、内网服务或非公开利用代码。公开 CVE 和组件版本会降低指纹识别成本，但对应制品已公开且不含实际部署目标，残余披露风险低；这不是零风险或制品无漏洞的结论。

| 公开附件 | 上传及匿名回读 SHA256 |
| --- | --- |
| [release-verification.json](https://github.com/iiwish/extrio/releases/download/v1.0.0-rc.3/release-verification.json) | `6f65c98b764ec31242058aa3c058ad574557e0cfdfaa94c35847b2397dfcf6eb` |
| [vulnerability-inventory.json](https://github.com/iiwish/extrio/releases/download/v1.0.0-rc.3/vulnerability-inventory.json) | `2b507fccf2aa2f5a3b1e17ade455f6cc80dca23b0961c920fc1fa672ad8fab5f` |
| [security-assessment.json](https://github.com/iiwish/extrio/releases/download/v1.0.0-rc.3/security-assessment.json) | `8beffd3cb70ab0c89015d068d692708f5738e6afe7c948468a77d6bc3e933121` |

三份文件于 2026-10-26 16:44:45（Asia/Tokyo）正常上传，没有覆盖既有附件；GitHub asset API ID 分别为 `677404012`、`677404013`、`677404011`。GitHub 元数据、CLI 下载和不带凭据的匿名 HTTPS 下载三方均与审核文件的长度和 SHA256 一致，JSON 均绑定 RC3 与源提交 `4f3929202d65601ced4ace3656eb726c64287459`。标签对象与解引用源提交未变，Release 保持 `prerelease=true`、`draft=false`。公开回执仍是 2026-10-23 的验证快照，本次没有重新扫描、签名核验或安装。

独立本地复核确认三份脱敏附件的长度、哈希和来源绑定一致；发行回执只删除两处工作站路径并增加脱敏说明，另两份文件与原件逐字节一致。五个阶段摘要、63 条实际命令回执及扫描/原生证据哈希吻合，未发现凭据、业务内容或原始采集内容。文件仍含 CVE、组件版本和制品元数据，本地审查通过不替代用户公开披露授权。

## 文档收尾

发行后的 canonical 状态、实际源提交、工作流、摘要及公开回执同步在本轮文档中；GitHub Release 说明已同步完成状态、三份下载链接和哈希，并明确核验与附件公开日期。本文件随本轮回执文档 PR 提交，遵守正常保护规则；远程检查和合并结果以承载本文件的 PR 及其实际 main 提交工作流为准，不移作 RC3 发行源提交的验证结果。

独立审查发现升级手册的可执行安装示例仍指向 RC1，已将 backend/Web 摘要与 RC3 发行表格对齐，并增加各镜像唯一摘要与可执行示例一致的回归断言。另修正引导语，明确附件待披露授权，示例不替代独立签名和 provenance 核验。两组新增断言分别先取得 **1 failed**，修正后相关集 **26 passed / 0 skipped**；manifest、Ruff 和空白检查通过。

附件公开前的独立最终复核未发现新增 P0/P1/P2，实测文档合同及发行门禁 **24 passed**。旧 RC1 摘要、删除待授权说明、删除独立验签边界三项纯内存负控均被回归拒绝。上述文档验证未重跑真实制品阶段。

附件公开前，主执行者使用隔离 Python 和离线构建缓存复跑版本、wheel、docset 与发行门禁，结果为 **26 passed / 0 skipped，2.64 秒**；Ruff、manifest `--check` 和 `git diff --check` 通过。

2026-10-26 按实际公开回执更新文档断言，先取得 **1 failed**，同步三附件链接、精确哈希和快照/公开日期边界后 **26 passed / 0 skipped，1.59 秒**；Ruff、manifest 与空白检查通过。冻结 RC1/RC2、源码行为、版本与依赖锁未改，不把文档检查计作制品重验。

主执行者独立复跑上述 26 项全部通过、零跳过，耗时 1.24 秒。

公开后的独立最终复核未发现新增 P0/P1/P2，相关 **26 passed / 0 skipped，1.42 秒**，manifest、Ruff、空白检查通过。错误附件哈希、RC1 可执行摘要、删除快照日期边界三项纯内存负控均被拒绝；独立无凭据下载三附件再次确认 SHA256 一致。此结论支持本轮 13 文件文档 PR，不代替该 PR 的远程 CI 或正常保护规则。

## 保留边界

正式 `v1.0.0` 保持未发布和 `Needs_Review`。采购网首次历史/真实增量、106 条质量待处理、六来源支持边界、目标用户旅程与产品/技术签收仍独立；1364 入口中 68 个静态样本和三个模板包不等于全站生产规则。72 小时观测沿用已有豁免，不计通过。

本轮未部署、升级或重启既有实例，未处理其他既有 PR、真实采集、付费模型、业务库读写或启用来源调度。真实响应、业务库、密钥、凭据和完整运行账本不提交或上传；Release 仅附三份已审核的脱敏核验与安全文件。
