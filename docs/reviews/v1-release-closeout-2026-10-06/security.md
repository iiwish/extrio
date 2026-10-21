# 稳定版安全处置登记

日期：2026-10-06。状态 `Requires Decision`。责任角色：项目安全/技术负责人；决定期限：正式 `v1.0.0` 发行前。任何例外必须另行指定具名负责人、适用候选/部署边界、补偿措施、到期与再验条件；本文未授予例外。

## 实测整改

保留 Python 3.12 与既有采集引擎，使用官方多架构 Debian 13 基础镜像固定摘要；移除安装/有头显示工具，不移除 Chromium 所需共享库。PG16 工具链通过完整恢复，lxml 6.1.3 通过参数实体边界反例及内部实体正控制。

原95 条 HIGH/CRITICAL 包记录去重为42 个 CVE。最终完整扫描为374 个 Debian 包记录，其中1 CRITICAL / 67 HIGH；高等级68 条记录去重为27 个 CVE。全部与实际 dpkg source package、安装版本及 [Debian Security Tracker](https://security-tracker.debian.org/tracker/) 当前数据逐项映射，见 [登记 JSON](evidence/os-risk-register.json)。不对低等级和 unknown 项隐瞒；完整发现扫描见 [backend-image-full.json](evidence/backend-image-full.json)。

20 个基线高等级 CVE 不再被最终扫描报告；新增5 项为4 个 Expat 和1 个 libxml2 条目。没有据此自动宣称其不可达或接受风险。基线与当前并非同一套包版本，数量降低不是攻击面降低的充分证明。

## 待决策风险

| 组 | 事实与应用观察 | 当前处置 |
| --- | --- | --- |
| NLTK / CVE-2026-81726 | Crawl4AI 的非可选依赖；官方公告无 patched version、Dependabot #1 open；应用不提供任意模型文件路径，15 项正/负控制与关联回归未命中公告 API | 保持 open，不直接卸载或修改第三方源码；限定路径证据不是全局不可达；用户独立风险决定或等待可验证上游修复 |
| 系统 libxml2 / 8 条高等级包记录 | CVE-2026-6653 仍 CRITICAL；7 个 HIGH 也无发行版修复。实际 Python lxml 不动态链接系统 libxml2，Chromium 的直接 ldd 未显示该库，但 LLVM/图形驱动和其他加载路径不被排除 | 不标为 not affected；继续结合实际输入/动态库链复核，正式发行前必须处置或由负责人明确签收限定风险 |
| lxml 内置 libxml2 2.14.6 | 包的参数实体默认策略修复已验证；内置库仍低于若干原生公告的2.15.4边界，不能把pip-audit的包结果当作其完整原生评估 | 作为原生库风险单独保留；不使用非正式编译/vendor patch，不宣称所有XML风险已解决 |
| Expat / 4 条 HIGH | 最新图像实际链接 libexpat；Debian13 当前2.8.3包仍有 CPU复杂度、哈希熵、回调深度与UTF16相关报告 | 保留5项新增风险的适用性复核；下载预算和非root不足以证明不可达，不能统一忽略 |
| X11/XRender/CUPS / 5 条 HIGH | 为实际 Chromium共享库/依赖；xvfb/xserver进程工具已移除，但库仍存在 | 不以headless或无监听端口证明库安全；未验证路径保持待决定 |
| util-linux / 36、ncurses / 4、Perl / 4、curl / 4、systemd / 2、acl / 1 条 HIGH | 实际镜像包与source映射可复查；部分工具不属于匿名来源输入的直接入口，组件仍可能被加载/调用 | 保留完整结果；按触发条件/权限/运行路径判断，不从“未显式调用”推出全局不可达 |

上述OS各组计数合计68，是包记录而非独立漏洞数；NLTK和内置库另计，不混入OS计数。

## 有效但有限的保护

- 应用以非root UID10001运行；来源请求使用既有协议/主机/DNS/robots/预算限制，不提供任意用户代码、模型路径或SQL执行能力。
- Schema和真实浏览器/编译/运行边界的15个NLTK用例保持通过；测试不覆盖所有动态加载、未来可选策略和任意第三方输入。
- lxml外部DTD探针只使用受控Resolver，不读取生产文件；本机与最终镜像验证了所声明的参数实体修复，而非全部XML解析调用。
- 安全门禁保持 `--ignore-unfixed --severity HIGH,CRITICAL --exit-code 1`；两镜像通过。完整发现扫描保留未修复项，无新的ignore/VEX抑制，没有dismiss告警。

## 决策边界

推荐保持正式发行待决定，不用自动化green代替安全签收。批准继续候选审查不是风险接受；RC 的例外不是稳定版例外。若选择“所有已知高等级项均须消除”，需要另行规划发行版/依赖隔离或等待上游，不在本次局部整改中偷偷更换核心架构。

主来源：[NLTK公告](https://github.com/nltk/nltk/security/advisories/GHSA-8mgp-746c-j5xp)、[lxml 6.1.3 发布说明](https://pypi.org/project/lxml/)、[Debian libxml2 状态](https://security-tracker.debian.org/tracker/source-package/libxml2)、[Astral官方镜像](https://docs.astral.sh/uv/guides/integration/docker/)、[PostgreSQL归档兼容边界](https://www.postgresql.org/docs/17/app-pgdump.html)。这些来源支持相应版本/条件，不替代镜像和应用实测。
