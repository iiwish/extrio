# 受支持基础镜像独立验证

任务 `TENDER-IMAGE-BASE`，2026-10-21 用户明确授权直接执行。基线为草稿 PR #49 的 `02c895a8d7be08c05a63af0b1116c2e6dfa5fe62`，不委派。目标是验证官方 Ubuntu 24.04 / 26.04 LTS 能否消除系统 LLVM/libxml2 的 CRITICAL 风险，同时保留已验证的 headless-shell/CUPS 精简边界。

## 执行合同

- 默认 `docker/backend.Dockerfile`、现有服务、业务源码、Python/Web 锁文件和数据合同不变。只增加独立 Ubuntu Dockerfile、基础镜像工作流、验证/比较工具、相应测试及本目录报告；可有界扩展既有镜像工具以复用测试与删除保护。
- 使用官方多架构镜像摘要、同版本 uv 和 Python 3.12，冻结应用依赖。Ubuntu 与 PGDG 仓库发行代号必须一致，不混入 Debian、testing/unstable、手工替换共享库或强制删除依赖。
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
