# RC2 安全核查与风险决策

日期：2026-10-21。状态：`Release Deferred`。用户明确要求暂缓发布、保留草稿 PR 并继续安全处置；没有接受残余风险。不得合并 main、创建候选标签或发布镜像，正式版/生产/来源调度均未授权。

## 已完成核查

- Python 定向更新 `aiohttp 3.14.4`、`certifi 2026.10.19`、`mcp 1.30.0`、`Pillow 13.0.0`，其余关联锁定变更为 `yarl 1.25.1`。Python 原 19 条告警仅剩 NLTK 1 条，无修复版本。
- Vite 为 `8.3.3`，关联 Rolldown 为 `1.2.14`。npm 官方全依赖审计为零；保留镜像源审计接口不可用的回执，不把该失败当通过。
- Trivy 0.76.0 官方校验和通过；Git 索引导出副本的 secret 扫描为零。提交排除数据库、密钥、原始网页/API/PDF/模型响应及采集运行回执，只保留 URL 目录和脱敏说明。
- [精确候选容器验证](https://github.com/iiwish/extrio/actions/runs/39533490291)完成 SQLite、PostgreSQL 16 隔离冷安装、鉴权与 Worker readiness；原有可修复 HIGH/CRITICAL 为零门槛通过，另留存未过滤的完整镜像报告。

## 完整发现

后端镜像有 400 条包告警记录：1 CRITICAL、63 HIGH、154 MEDIUM、174 LOW、8 UNKNOWN。HIGH/CRITICAL 去重为 23 个 CVE，64 条记录均没有扫描器认定的已发布修复版本。Web 镜像完整扫描为零。包记录数不是独立漏洞数，零可修复高危也不是零风险。

脱敏的高等级包/版本/CVE 清单为 [security-inventory.json](security-inventory.json)。完整 CI 原报告只保留在其 Actions artifact 和受限本地证据目录，不夹带采集数据。

与 2026-10-06 冻结候选相比，高等级清单减少 6 条并增加 `libcups2t64 / CVE-2026-55453` 1 条。不能据此宣称攻击面整体安全，旧候选的风险接受也不延伸至 RC2。

| 范围 | 实际边界与处置 |
| --- | --- |
| NLTK 3.10.3 | [官方公告](https://github.com/advisories/GHSA-8mgp-746c-j5xp)无修复版本；涉及调用者控制的模型文件读写路径。当前应用不提供该模型路径入口，15 项边界与关联回归通过，但有限路径证据不是全局不可达证明。保持 open。 |
| 系统 libxml2 | 含 `CVE-2026-6653` 的 1 CRITICAL/7 HIGH。当前 [Debian trixie 状态](https://security-tracker.debian.org/tracker/CVE-2026-6653)仍为 vulnerable；不能用版本字符串中的 2.12.7 忽略其实际 2.9.14 来源。Python lxml 的内置库与系统库分开评估，其他动态加载链未获完整不可达证明。 |
| CUPS | [官方上游公告](https://github.com/OpenPrinting/cups/security/advisories/GHSA-7hqf-mfhx-7r3v)描述远端打印机状态注入和后续打印作业链；[当前 Debian trixie 包](https://security-tracker.debian.org/tracker/CVE-2026-55453)仍受影响。镜像保留 Chromium 所需 libcups，不提供打印队列配置入口；未进行全依赖动态链不可达证明，不标 not affected。 |
| X11/XRender、util-linux、ncurses、Perl、curl 库、systemd/udev、ACL | 具体包、版本、告警和严重性保留于清单。非 root、下载预算和 headless 不是消除漏洞的证明。保持 open，不新增忽略或 VEX 抑制。 |
| 原生内置库 | lxml/Pillow/Chromium 的内置库不以 Python 包审计结果统一判安全；沿用既有原生库残余风险登记，正式发行仍须独立评估。 |

## 安全处置

兼容官方依赖试算确认 lxml/NLTK 没有可用锁定升级；当前 lxml 6.1.3 内置 libxml2 2.14.6、NLTK 3.10.3。系统包和 Python 内置库分别记录，不从包名或库版本字符串推断漏洞已经修复。

容器 CI 增加无网络的实际组件核查：读取 dpkg 的安装版本、Essential 标记和声明反向依赖，检查打印链组件路径，并对固定 HTML/XML/PNG/SVG/PDF 夹具记录 lxml/Pillow/Chromium 的 ldd 与动态加载库。运行不提供任意网址/文件参数，不初始化业务数据库或触发采集，结果只作有限路径证据，不自动判定 not affected 或关闭告警。诊断结果和完整漏洞报告共同留存于 Actions artifact。

## 后续门槛

候选保持草稿，不宣称安全验收完成。告警保持 open，不降低既有可修复 HIGH/CRITICAL 门槛，不直接引入 Debian unstable 包或非正式 vendor patch。只有经过验证的官方修复、组件移除或明确的适用性证据才能更新处置结论；重新发布仍需用户明确授权。未采用风险例外，也没有生效的风险豁免期限。

本地完整回执位于 `backend/data/tender-manual-20261019/release-rc2-20261021/`。本机大镜像/漏洞库下载因速度中断，回执保留为未通过；安装与镜像安全结论来自上述原生 Linux 精确提交 CI，不冒称本机镜像安装完成。
