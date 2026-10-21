# RC2 候选验证

日期：2026-10-21。工程验证通过，用户决定暂缓发布并继续安全处置；候选保持草稿 PR，未合并 main、未创建 RC2 标签、未发布镜像或部署。机器辅助验证不等于最终人工业务签收。

## 代码与远程检查

候选 PR 为 [#49](https://github.com/iiwish/extrio/pull/49)。应用代码提交 `417937bd9e5393e6be7e89424116a8d9837e46a0`；容器验证增强提交 `27c8c97bee63fca4c6b415fd5e4d194b71e18aec` 的以下检查均通过：

| 检查 | 证据 |
| --- | --- |
| repository-security / backend / web | [精确提交 CI](https://github.com/iiwish/extrio/actions/runs/39533490276) |
| SQLite 与 PostgreSQL 16 冷安装、鉴权、Worker readiness | [Container verification](https://github.com/iiwish/extrio/actions/runs/39533490291) |
| 双镜像可修复 HIGH/CRITICAL 门槛及完整漏洞清单 | 同一容器运行，完整报告为其 `container-vulnerability-inventory` artifact |

其他提交的结果不能替代候选最新 head、未来 main 精确提交或正式制品的独立检查。后续仅文档修改仍执行既有必需 CI，不绕过保护。

安全诊断提交 `3676f284a90ba434e1cefc81bf6298477d333262` 的[完整 CI](https://github.com/iiwish/extrio/actions/runs/39536007426)为后端 1074 通过、前端 278 通过，包含新增的 6 项诊断测试；lint、构建、包与文档检查通过。[同提交容器验证](https://github.com/iiwish/extrio/actions/runs/39536007421)通过双库安装和断网组件诊断，完整告警清单没有变化。该结果不是安全发布签收，后续文档提交仍须独立检查。

## 本地冻结回归

- 后端 SQLite / 独占临时 PostgreSQL 16：1068 通过，0 失败、错误或跳过。
- Web：278 通过 / 43 文件；backend/web lint、Web production build、docset、wheel 与 OpenAPI 生成一致性均通过。
- 343 个源码/测试/契约/包文件在回归前后逐文件相同；生成类型无漂移。临时 PostgreSQL 已移除。
- 当前代码包括定向安全依赖更新，不把旧 1068 项结果冒称为本次重跑。

命令入口为受限本地 `/private/tmp/extrio-tender-manual/regression.py --phase rc2-candidate`，回执在 `backend/data/tender-manual-20261019/regression-20261019/rc2-candidate/`。源分发/包安装测试使用生成的发行包和临时空数据库，不连接用户实例。

## 升级与恢复

`test_release_upgrade.py` 的 8 项全部通过：真实历史、已发布 Alpha、已发布 RC1 的 SQLite/PG16 升级与匹配源程序回滚共 6 项，以及双库并发空库迁移 2 项。完整备份和源包安装相关测试合计 19 项通过，无跳过。

RC1 schema 013 升级到 schema 014 保留既有迁移时间、规则、签名、字段版本、检查点、观测、投递、用户/会话、密钥和 Artifact；全量备份恢复到空目标，并用匹配 RC1 程序验证回滚。不是数据库原地降级，也不是在业务实例上试迁移。

本机大镜像及 Trivy DB 下载因网络速度中断，日志和中断回执保留，不记成功。本轮双库容器冷安装和镜像扫描采用上述原生 Linux 精确提交 CI，临时项目按脚本清理。本机唯一中断的 Compose 项目没有残留容器，不停止基线 Web/API/Worker。

## 数据保留与限制

只读保留核验覆盖 339 个 Run、9854 条观测行、18 个规则/18 个签名、3 个字段版本、1495 个策略、签名公钥、投递表及来源状态；旧 17894 个文件和原始数据库哈希保持相同。观测行数不是实体数量。全部 1480 个来源调度关闭，AI Run 仍为 26，真实队列为空，没有新来源请求或付费模型调用。

验证实例当前有效去重实体 4751、质量待处理 106；采购网保持未完成覆盖和原断点，扫描件/受限/模板公告不作为有效正文。既有失败 Run 和旧策略证据保留，不替换成成功。

提交仅含代码、迁移、测试、契约、说明和 URL 目录。Git 属性保留 CSV 的 UTF-8 BOM/工作区 CRLF，索引规范化换行；原始采集轮次和回执由忽略规则排除。Git 索引导出 secret 扫描为零。

发行安全状态与完整高等级清单见 [security.md](security.md) 和 [security-inventory.json](security-inventory.json)。用户未接受该风险，发布授权已暂缓，不进入合并/标签/镜像发布阶段。新增只读镜像诊断独立验证，不把诊断结果冒充漏洞已修复。

独立镜像精简的[对照、完整扫描及剩余边界](image-pruning.md)单独登记：默认构建保持不变，LLVM 路径因必需 GBM 依赖不采用，仅 headless/CUPS 实验通过双架构镜像内各 246 项定向回归。对应提交的完整主 CI 为后端 1088 / 前端 278，通过不代表所有安全风险解除；普通容器验证的 Alpine 仓库 TLS 失败保留，最终提交仍须重新通过原有流程。
