# RC2 发行收尾

任务 `TENDER-RC2-RELEASE`。用户于 2026-10-21 明确授权：检查通过后将 PR #49 转为 Ready、正常合入 main，并仅发布 `v1.0.0-rc.2` 预发布版。不发布正式版，不部署生产，不启用来源调度，不新增真实采集、模型调用或风险豁免。直接执行，不新增委派。

## 范围与门禁

- 候选行为基线为 `44fc9170c7bf559a1bb18b7ce29556808093621b`。本轮仅整理发行状态、审查和安装说明及必要的文档指纹，不新增业务能力或重写规则/检查点。PR #40 的代码已包含在 #49；最终安装以 main 合并提交和 RC2 制品为准，不重复应用旧 PR。
- 文件范围：本目录发行记录、`docs/releases/v1.0-rc.2.md`、稳定版交接中的授权边界、对应 `test_docset_authority.py` 文档合同测试及生成的 docset manifest。运行期源码、冻结依赖、迁移与全部用户数据不变。
- 审查采用现有功能/安全记录与真实回执核验，检查完整变更清单、访问边界、生命周期、字段/覆盖合同、冻结依赖、安装恢复和发行工作流。不伪称独立人工审计或以维护者身份自批准自己的 PR。
- 正常保护规则必须满足，不使用 admin bypass。冻结 PR head，核对全部必需检查成功、无未处理阻断后才正常 squash merge；实际 main 合并提交重新通过 CI/Container verification，不能沿用 PR 事件的成功来满足 `verify-release.py`。
- 只创建不存在的 `v1.0.0-rc.2` 标签，不覆盖或移动已存在标签。发行工作流在该精确提交执行双架构构建、全部 HIGH/CRITICAL（含未修复项）扫描、keyless 签名和 provenance；失败不跳过，不自动重建/重试或提升标签。
- 发布后独立核对 backend/web 的不可变摘要、amd64/arm64 平台、签名的工作流/标签身份，以及 provenance 的源提交与 ref。再用已发布摘要执行 SQLite/PG16 隔离安装，不能用本地重建镜像替代。临时资源须独占标签/项目名、只处理合成数据、验证后清理。
- RC2 发布说明明确采购网历史/增量未完成、106 条质量待处理及非全站兼容边界；保留 30 MEDIUM/16 LOW 等实际完整清单，不宣称零漏洞。旧实例不升级，旧版本的告警不手动关闭。
- 数据库、私钥、凭据、Cookie、原始公告/API/PDF/模型响应及真实采集结果不提交或上传。既有实例以只读清单验证保留，基线 Web/API/Worker 不重启，全部来源调度保持关闭。

## 发行前审查

候选 `44fc917` 的[完整主 CI](https://github.com/iiwish/extrio/actions/runs/39559449526)、[双库冷安装/完整扫描](https://github.com/iiwish/extrio/actions/runs/39559449596)、[原生双架构/升级恢复](https://github.com/iiwish/extrio/actions/runs/39559449515)和[精简配方对照](https://github.com/iiwish/extrio/actions/runs/39559449522)全部成功。下载后重新核对镜像身份、探针、全部等级清单和 JUnit：后端 1108/前端 278 项；两架构默认镜像各 258 项，零失败/错误/跳过，0 CRITICAL/0 HIGH/30 MEDIUM/16 LOW；Web 扫描为零。

本轮定向审查未发现新增 P0/P1；未将来源覆盖缺口或质量待处理关闭。控制面权限、已签名规则、版本化策略、覆盖/质量分离、网络限速/IP 校验、浏览器失败清理与合成双库升级/恢复的证据沿用各自精确提交，不外推长期 SLA、平台容量或商业上线验收。GitHub 必需审查人数为零，不意味着存在独立人工审查；用户授权仅用于本次受限预发布。

## 结果入口

实际合并、标签与制品状态以 [PR #49](https://github.com/iiwish/extrio/pull/49) 和 [RC2 Release](https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.2) 为准。只有发行工作流成功且已发布摘要完成独立验证后，才能宣布收尾完成。Release 的 `release-verification.json` 记录精确源提交、工作流、不可变摘要、签名/provenance 与摘要安装结果；不是发布前的本地 image ID。
