# 定向依赖安全修复核验

任务：`DEP-SEC-20261026`。日期：2026-10-26（Asia/Tokyo）。状态：本地针对性验证和独立代码复核通过，精确提交 CI 与双架构制品结果单独记录于本任务 PR。不是用户签收、合并、发行或部署。

## 来源与修复边界

用户授权见[执行包](packet.md)。修复追加到 PR #53 的原始回执提交 `b579ef542b1788f47b485021c4999d2dd519dfb4`，不改写首轮 CI 失败：Container `40288214343`、原生镜像 `40288214327`、镜像裁剪 `40288214377` 的首次失败保持可见。普通 CI `40288214318` 成功不等于安全门禁通过。

首轮 backend 重建完整扫描为 0 CRITICAL / 4 HIGH / 30 MEDIUM / 18 LOW，四条 HIGH 为 filelock 的 `CVE-2026-112940` 和 pypdf 的 `CVE-2026-115572`、`CVE-2026-115580`、`CVE-2026-115585`。这是 CI 新建镜像，不冒称已发布 RC3 摘要的当日复扫。上游 filelock 为 High，pypdf 三项上游为 Moderate；扫描器 HIGH 门槛不变，不通过评级差异豁免。

结构化比较确认锁仍为 98 包，只更新 filelock 3.32.4 → **4.2.1**、pypdf 6.21.1 → **6.21.2**，其他 95 个第三方包记录完全一致；项目本身只更新对应依赖声明元数据，版本保持 `1.0.0rc3`。新锁 SHA256 为 `2010536667d070c57e0f22c86f229756b2006f6d8461a5a43489a7dbe2a4be4a`，旧锁为 `86b0ba492b75557bdd9e0cbe26ba0c82dec212a79d04cec21ef53271efbbfd11`。

直接依赖 pypdf 为 `>=6.21.2,<7`；传递依赖 filelock 通过 uv 项目约束为 `>=4.2.1,<5`，未增加无关直接依赖。仓库及 OCI 使用 frozen/locked uv 安装；filelock 的 uv 约束不进入 wheel Requires-Dist，不外推普通 pip 单独解析 wheel 的同等安全下限承诺。

## 本地回归

- 结构化安全测试在旧配置、锁和隔离环境上真实取得 **6 failed / 6 passed**；定向更新锁后，旧环境负控仍为 **2 failed / 10 passed**，准确拒绝已安装版本与锁不符。
- 新独占环境实际安装 filelock 4.2.1、pypdf 6.21.2、tldextract 5.3.2、crawlee 1.9.3。安全测试 **12 passed / 0 skipped**；wheel/package 加安全回归 **14 passed / 0 skipped**，离线 `uv lock --check` 成功。
- tldextract 离线缓存冷/热/新实例磁盘路径，以及 FileLock 真实跨进程竞争超时和释放后重获：旧环境兼容基线 **2 passed**，候选 **2 passed / 0 skipped**。只用临时路径，拒绝 HTTP，不模拟掉锁核心行为；不把 FileLock 结果外推为 ReadWriteLock 协议兼容。
- 主执行者新增原生清单与文档历史边界回归，先 **2 failed**，最小实现后相关 **11 passed**；两个依赖测试已追加到原生镜像实际 pytest 清单，不改变扫描规则。
- 主执行者使用候选环境独立执行安全、兼容、wheel、docset、发行门禁及镜像合同：**45 passed / 0 skipped**。Ruff、manifest、`bash -n`、空白检查通过。

独立实现复核未发现新增 P0/P1/P2，实测针对性 **25 passed / 0 skipped**；旧版本及 prerelease/dev 版本四个纯内存负控均被拒绝。原生只读 mounts 覆盖新增测试所需 metadata、锁与临时路径；没有削弱能力、安全或零跳过门禁。

## 本地全量准备阻断

本地全量后端为 **Not_Run（环境准备阻断）**，没有 JUnit 或 pytest 成功记录。初次隔离 PG16 准备因缺失 `postgres:16-alpine` 下载超过 120 秒中止；临时网络已清理，pytest 尚未启动，原四个容器 ID、启动时间和重启次数一致。原始准备失败回执保留，SHA256 为 `5b203e32b16b922db8ae75a7e841a8e1e6dc133c002e0725dbec3bccf5ca72c9`。

单独准备该官方 PG16 镜像随后在 Docker/containerd 解压层处报 `no space left on device`；没有运行本地全量、清理其他项目镜像/卷/缓存、重启 Docker 或借用既有数据库。备用的新命名空间 helper 未执行，不计通过。隔离 PG16 后端全量和双架构真实镜像验证由本任务新提交的现有 CI 完成，结果不沿用旧提交。

## 远程证据与剩余门槛

以本文件所在 PR 的修复提交精确 SHA、首次运行工作流、原始扫描及 JUnit 为准；不得把旧 head 的失败直接重跑成新结果。每个新 head 的检查和下载制品独立核对，完成结论记录在该 PR 的回执评论中，不把文档记载替代真实远程结果。

RC3 标签、已发布镜像与三份公开 JSON 保持冻结，依赖安全修复不包含在已发布 RC3 中。源码修复或未发布 CI 制品成功不代表 RC3 已消除高危风险，也不是未来稳定候选的发布门禁。正式稳定版保持 `Needs_Review`；本轮不合并、不新建标签或 Release、不部署，不进行真实采集、付费模型、现有业务库读写或启用来源调度，其他既有 PR 不处理。
