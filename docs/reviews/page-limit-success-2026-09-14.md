# 配置页数完成状态

运行达到配置页数上限属于正常结束；没有拒绝记录时为 succeeded，有拒绝时沿用部分成功或失败判定。抓取失败、超时及其他异常不因本规则获豁免。max_pages 保留为可审计停止原因，不推进增量水位，因为按页数完成不证明时间范围已遍历完整。

验证：Worker 29 项通过（包括 max_pages 成功、拒绝分支及不推进 checkpoint 的完整终结测试）；Worker/runtime 组合 37 项通过；前端 7 项通过；build、lint、diff check 通过。

本地历史记录 run_x_5fe4c7fb61b942 在核对 max_pages、0 拒绝、200/200 详情成功后，仅校正 status 和 recoveryAction。备份为 /tmp/extrio-before-page-limit-status-20260914.db。其他采集结果、规则、停止原因、水位不变；不批量改写其他历史记录。不调用模型，不重新采集，不发布规则。

API、Worker、Web 重载，readyz=true。桌面核验使用该记录的只读快照及 GET API 替身，不发起真实业务写入。
