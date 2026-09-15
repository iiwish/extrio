# G3 持续观测交接

状态：Stopped_Pending_Analysis。用户要求仅保留 5173 实例，本次观测于 2026-09-11 10:56（Asia/Shanghai）正常停止，保留 869 个样本与全部原始证据；实际窗口约 14.5 小时，不证明 72 小时通过。持续观测验收 Pending，恢复验收需另行批准完整新窗口。

## 环境与窗口

- 开始：2026-09-10 20:26:20（Asia/Shanghai），UTC `2026-09-10T12:26:20.135675Z`。
- 目标结束：2026-09-13 20:26:20（Asia/Shanghai），完整窗口 259,200 秒。
- 隔离目录：`/Users/iiwish/self/extrio/backend/data/g3-observation-20260910-2028`，仅本包新建，SQLite、Artifact、key 与账号均独立。
- API：`http://127.0.0.1:8038`；仅本地 fixture 来源与 HMAC 接收器 `http://127.0.0.1:62028`。不连接真实来源、模型、maco 或用户数据库。
- 三来源，每五分钟调度（Asia/Shanghai），每 60 秒记录样本；启动额外触发三次 warmup。本地来源每分钟变化，观察新 revision 与 Delivery。
- 监督器 PID `58989`，API PID `59008`，Worker PID `59009`。PID 为启动快照，后续操作必须先核对 state 及对应命令，不能按旧 PID 杀无关进程。
- 部署摘要：`d9590532e5b30852f911f7dc013489513f10ac6365c65f1102fe95aaf2f4aa1b`。

## 状态与原始证据

目录内 `state.json` 保存当前状态、UTC 起止、进程、最新样本；`samples.jsonl` 保存每次 readiness、Worker、队列、Run、Delivery、schedule occurrence、派发延迟和样本间隔；`receiver.jsonl` 保存 Delivery ID、payload digest 与 HMAC 检查结果。`api.log`、`worker.log` 是故障定位日志。登录文件仅拥有者可读，不提交或复制到文档。

启动验证（2026-09-10 20:30:20）：已有 5 个样本，1 Worker 就绪且部署匹配，队列/执行数均为 0。三次 warmup 加 20:30 首个计划周期的三次调度，共 6 个 Run succeeded、6 个 Delivery delivered；3 个 schedule occurrence dispatched，最大派发延迟 4.759s。接收器 6 次请求、0 无效签名，两个子进程均存活，最大已见样本间隔约 60.05s。该证据证明真实 scheduler 已工作，不只是手工 warmup；不据此推断余下窗口通过。

本任务的监控 `extrio-g3-72` 每 30 分钟只读检查。状态正常且无可行动变化时保持安静；仅新故障、超过五分钟样本停滞、需要用户操作或窗口结束时通知。结束后暂停监控，不自动启动 G4 或部署。

## 停止与分析

正常停止先核对当前 state 的 supervisorPid 与 `observe-runtime.py` 命令，再向监督器发送 SIGTERM；监督器等待并停止自己启动的 API/Worker 和接收器，保留全部证据。不要用全局 pkill、删除目录或移除密钥“修复”观察。监督进程异常被强杀时须先核对自有子进程，避免遗留运行或误杀其他实例。

正常到期为 `completed_pending_analysis`，主动停止为 `stopped_pending_analysis`，异常为 `failed`；都不是自动通过。G4 至少分析完整时间覆盖、样本空洞、进程/Worker 就绪、队列滞后、计划派发和跳过/失败原因、Run 终态、签名错误、重试/死信、相同 Delivery ID 重复及资源增长。宿主休眠或关机属于证据缺口，不能补零或把墙钟经过等同于连续运行。

影响结论的代码/合同修复必须明确是否重启新窗口，保留旧窗口证据；不在同一观察记录中掩盖中断。本轮没有 PG 持续 72 小时、外站/模型容量或生产 SLA 的证明。

## G4 证据适用性

本窗口继续覆盖上述冻结 G3 进程的稳态调度、运行和交付，不覆盖 G4 候选制品全部路径。G4 的候选样本展示、数据库首次并发初始化、前端状态和 Python 打包修复在独立实例验证；现有观测进程不执行这些初始化/编译/构建路径，合同文件保持不变，因此不重启本窗口。最终报告必须把稳态观测与候选制品的补充回归分开，不能将该窗口记作候选新代码的逐字节 72 小时运行证明。观测未完成前不关闭 P31。
