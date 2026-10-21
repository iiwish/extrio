# RC2 安全核查与风险决策

日期：2026-10-21。状态：`Requires Decision`。本轮提交和测试候选版发布授权不是安全风险豁免；未取得限定风险接受前，不合并 main、不创建候选标签、不发布镜像。

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

## 决策条件

建议在未接受风险时保持草稿 PR，不宣称安全验收完成。若项目负责人明确接受，仅适用于本次 RC2 的受限测试发行，不适用于正式版或生产；复审截止 2026-11-04。告警保持 open，不降低既有可修复 HIGH/CRITICAL 门槛，不直接引入 Debian unstable 包或非正式 vendor patch。未列明的新高等级风险及新增可修复高危均须暂停并重新审阅。

本地完整回执位于 `backend/data/tender-manual-20261019/release-rc2-20261021/`。本机大镜像/漏洞库下载因速度中断，回执保留为未通过；安装与镜像安全结论来自上述原生 Linux 精确提交 CI，不冒称本机镜像安装完成。
