# RC2 安全核查与风险决策

日期：2026-10-21。状态：`RC2 Authorized / Gated`。用户明确授权候选检查通过后正常合入 main 并仅发布 `v1.0.0-rc.2` 预发布版，执行边界见 [release-closeout.md](release-closeout.md)。没有接受高危残余风险，任何 HIGH/CRITICAL 均阻断；正式版、生产部署和来源调度均未授权。

当前默认构建采用 Ubuntu 24.04 官方 Python 3.12/headless-shell，受限浏览器直接使用稳定 Playwright，冻结依赖中没有 Crawl4AI/NLTK。完整扫描包含未修复项；任何 HIGH/CRITICAL 都阻断候选。实施边界和精确提交结果入口见 [playwright.md](playwright.md) 及[草稿 PR #49](https://github.com/iiwish/extrio/pull/49)。依赖移除不修复上游 NLTK，也不更新现有实例或历史镜像，不从 CI 绿色推断发布授权。

冻结提交 `631cf6771bfa1548f3b7d84dd6e37b42480eb477` 的 Ubuntu 原生双架构报告为 0 CRITICAL / 1 HIGH / 30 MEDIUM / 16 LOW，唯一 HIGH 是当时的 NLTK 3.10.3；原报告、预发布隔离研究及适用边界保留在 [default-ubuntu.md](default-ubuntu.md) 和 [default-ubuntu-results.json](default-ubuntu-results.json)，不是当前无 NLTK 候选的扫描证据。

## 已完成核查

- Python 定向更新 `aiohttp 3.14.4`、`certifi 2026.10.19`、`mcp 1.30.0`、`Pillow 13.0.0`，其余关联锁定变更为 `yarl 1.25.1`。Python 原 19 条告警仅剩 NLTK 1 条，无修复版本。
- Vite 为 `8.3.3`，关联 Rolldown 为 `1.2.14`。npm 官方全依赖审计为零；保留镜像源审计接口不可用的回执，不把该失败当通过。
- Trivy 0.76.0 官方校验和通过；Git 索引导出副本的 secret 扫描为零。提交排除数据库、密钥、原始网页/API/PDF/模型响应及采集运行回执，只保留 URL 目录和脱敏说明。
- [精确候选容器验证](https://github.com/iiwish/extrio/actions/runs/39536007421)完成 SQLite、PostgreSQL 16 隔离冷安装、鉴权与 Worker readiness，以及断网原生组件诊断；原有可修复 HIGH/CRITICAL 为零门槛通过，另留存未过滤的完整镜像报告。

## 历史 Debian 发现

冻结的 Debian 基线镜像有 400 条包告警记录：1 CRITICAL、63 HIGH、154 MEDIUM、174 LOW、8 UNKNOWN。HIGH/CRITICAL 去重为 23 个 CVE，64 条记录均没有扫描器认定的已发布修复版本。该基线不是当前默认 Noble 构建；历史记录和原报告保持。包记录数不是独立漏洞数，零可修复高危也不是零风险。

脱敏的高等级包/版本/CVE 清单为 [security-inventory.json](security-inventory.json)。完整 CI 原报告只保留在其 Actions artifact 和受限本地证据目录，不夹带采集数据。

与 2026-10-06 冻结候选相比，高等级清单减少 6 条并增加 `libcups2t64 / CVE-2026-55453` 1 条。不能据此宣称攻击面整体安全，旧候选的风险接受也不延伸至 RC2。

| 范围 | 实际边界与处置 |
| --- | --- |
| NLTK 3.10.3 | [官方公告](https://github.com/advisories/GHSA-8mgp-746c-j5xp)无修复版本；涉及调用者控制的模型文件读写路径。当前应用不提供该模型路径入口，15 项边界与关联回归通过，但有限路径证据不是全局不可达证明。保持 open。 |
| 系统 libxml2 | 含 `CVE-2026-6653` 的 1 CRITICAL/7 HIGH。当前 [Debian trixie 状态](https://security-tracker.debian.org/tracker/CVE-2026-6653)仍为 vulnerable；不能用版本字符串中的 2.12.7 忽略其实际 2.9.14 来源。Python lxml 的内置库与系统库分开评估，其他动态加载链未获完整不可达证明。 |
| CUPS | [官方上游公告](https://github.com/OpenPrinting/cups/security/advisories/GHSA-7hqf-mfhx-7r3v)描述远端打印机状态注入和后续打印作业链；[当前 Debian trixie 包](https://security-tracker.debian.org/tracker/CVE-2026-55453)仍受影响。镜像保留 Chromium 所需 libcups，不提供打印队列配置入口；未进行全依赖动态链不可达证明，不标 not affected。 |
| X11/XRender、util-linux、ncurses、Perl、curl 库、systemd/udev、ACL | 具体包、版本、告警和严重性保留于清单。非 root、下载预算和 headless 不是消除漏洞的证明。保持 open，不新增忽略或 VEX 抑制。 |
| 原生内置库 | lxml/Pillow/Chromium 的内置库不以 Python 包审计结果统一判安全；沿用既有原生库残余风险登记，正式发行仍须独立评估。 |

## 历史基线处置

兼容官方依赖试算确认 lxml/NLTK 没有可用锁定升级；当前 lxml 6.1.3 内置 libxml2 2.14.6、NLTK 3.10.3。系统包和 Python 内置库分别记录，不从包名或库版本字符串推断漏洞已经修复。

容器 CI 增加无网络的实际组件核查：读取 dpkg 的安装版本、Essential 标记和声明反向依赖，检查打印链组件路径，并对固定 HTML/XML/PNG/SVG/PDF 夹具记录 lxml/Pillow/Chromium 的 ldd 与动态加载库。运行不提供任意网址/文件参数，不初始化业务数据库或触发采集，结果只作有限路径证据，不自动判定 not affected 或关闭告警。诊断结果和完整漏洞报告共同留存于 Actions artifact。

### 实际镜像结果

提交 `3676f284a90ba434e1cefc81bf6298477d333262` 的上述 CI 已通过，范围为 Linux amd64，不延伸为 arm64 制品验证。6 项诊断测试通过，包含已卸载/仅剩配置包不冒充已安装包的反例；固定夹具截图 7993 字节、PDF 7118 字节，动态诊断在 `--network none` 容器内执行。完整扫描清单与 `27c8c97` 逐条比较相同，没有新增或消失的告警，也没有修复数量变化。

| 组件 | 镜像实测 | 处置边界 |
| --- | --- | --- |
| 系统 libxml2 | 安装版本为 `2.12.7+dfsg+really2.9.14-2.1+deb13u3`；声明反向依赖只有 `libllvm19:amd64`，LLVM 又声明依赖 libxml2；固定夹具动态日志未观察到系统 libxml2/LLVM 初始化 | 可优先隔离验证 LLVM/图形依赖精简，但本轮没有卸载。单一无网络夹具未加载不证明所有 GPU、Canvas、网页或未来路径不可达。 |
| Python lxml | lxml 6.1.3 的运行/编译内置 libxml2 均为 2.14.6；其扩展 ldd 不链接系统 libxml2 | 与系统漏洞分开登记，仍须核对内置库适用的原生公告，不能只靠 pip-audit 关闭。 |
| CUPS | 选定的 cupsd、IPP backend、Foomatic filter、lp/lpr 路径均不存在；完整 Chromium 的 ldd 明确包含 `libcups.so.2`，即使 dpkg 没有声明反向依赖 | 打印链组件缺失缩小了已观察范围，不代表 libcups 可直接删除或两项 CUPS 告警均不适用。先完成具体公告函数与二进制适用性核验，保持 open。 |
| Perl / 系统工具 | `postgresql-client-common` 声明依赖 Perl；`perl-base`、`bsdutils`、`util-linux` 标为 Essential | 不用强制删除或清除 dpkg 元数据来减少告警；保留 PostgreSQL 备份恢复与运行能力。 |

这些结果仅形成处置优先级，没有移除运行依赖、修改业务解析或关闭任何漏洞。报告文件 SHA256 保留在 `security-inventory.json`，完整输出保留于该 CI artifact 和受限本地目录。

## 后续门槛

候选保持草稿，不宣称安全验收完成。告警保持 open，不降低既有可修复 HIGH/CRITICAL 门槛，不直接引入 Debian unstable 包或非正式 vendor patch。只有经过验证的官方修复、组件移除或明确的适用性证据才能更新处置结论；重新发布仍需用户明确授权。未采用风险例外，也没有生效的风险豁免期限。

独立镜像的[依赖精简实测](image-pruning.md)保留冻结的 Debian 精简记录：仅 headless-shell/CUPS 通过双架构能力对照，减少 27 条，其中 2 HIGH；LLVM 删除会移除必需的 libgbm1，保护检查阻止采用。历史 Debian 配方仍为 1 CRITICAL/63 HIGH，其 headless 对照为 1 CRITICAL/61 HIGH，告警均未豁免，不能把 Noble 结果改写为 Debian 告警已修复。

NLTK 继续核对官方修复或评估替换完整上游依赖，不能局部卸载后保留失效的 Crawl4AI 导入。其余 Essential 与原生库等待受支持发行版修复或独立验证的基础镜像方案，不以无补丁为由接受风险。

受支持[替代基础镜像实测](alternative-base.md)保留其冻结证据：Ubuntu 24.04 的 libxml2 漏洞由 Ubuntu 包修复，LLVM/GBM 保留；Ubuntu 26.04 的受管理 Python/pip 及镜像自带 pebble 引入可修复新高危，失败证据保留且拒绝采用。用户授权的默认 Noble 构建选择与完整复验单独记录于 [default-ubuntu.md](default-ubuntu.md)，不改写历史镜像或冒称发行已获准。

本地完整回执位于 `backend/data/tender-manual-20261019/release-rc2-20261021/`。本机大镜像/漏洞库下载因速度中断，回执保留为未通过；安装与镜像安全结论来自上述原生 Linux 精确提交 CI，不冒称本机镜像安装完成。
