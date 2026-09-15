# AE-06 内部交接字段修复

状态：Needs_Review。用户已确认修复范围，直接执行，不委派。

内部 `list.detailUrl` 是运行时交接标识，业务合同 `detail_url` 是输出字段；两者不能通过业务字段归一化相互覆盖。已验证列表在编译中保持交接语义，输出字段遵守绑定的 CollectionVersion。不可用的固定发现上下文在调用模型前直接失败，不向模型反复要求修复应用内部状态。

允许文件：model_gateway、对应 explorer/worker 错误处理、相关后端测试与本记录。验证脚本必须通过 Store.collector_compilation_context 获取 Worker 等价输入。无新增付费调用、发布、生产数据写入、迁移或无关改动。

TDD：覆盖 detail_url 业务字段与内部 detailUrl 共存、阶段绑定不串用映射、绑定需求合同完整样本验证、内部上下文错误零模型调用。运行模型网关、修复、冻结合同、阶段交接及 Worker 回归。检查现有工作区修改并保留。完成后重载空闲本地 API/Worker，确认 readiness。

## 结果与边界

- RED：三个新增测试全部失败，确认固定交接被业务字段映射破坏，以及无效固定上下文会先消耗模型调用。
- GREEN：生成、修复、冻结合同、阶段交接、自适应会话及 Worker 恢复相关测试 115 passed。测试包含有/无详情页自引用链接两个分支。
- 映射只作用于输出阶段的字段绑定，不把详情字段别名应用于列表绑定。缺少独立业务 URL 提取时，从已验证的 list.detailUrl 复制提取规则到业务 detail_url，保留内部交接键与原发现对象。
- 固定发现上下文预检使用不可重试的 CompilationContextError；它不属于可由模型纠正的 ModelCompileError，不进入 explorer 的纠错循环。模型生成的可修正字段错误仍可在原预算内重试。
- `replay-handoff-contract.py` 使用最新失败任务的完整快照和 Store.collector_compilation_context 返回的四字段合同；确定性模型替身输出经过真实编译与完整样本校验，3 个 accepted，业务 URL 与三个详情样本 URL 一致，冻结合同摘要保持不变。结果见 handoff-contract-replay.json。
- 本次真实模型调用为 0，不发布、不覆盖现有候选或生产 Item。离线通过不等于真实模型端到端验收；16 次预算未继续提高。
- 最终模型网关与新增回归复验 21 passed，相关 Ruff 与 git diff --check 通过。未重跑全仓全量测试；未修改前端代码。
- 确认队列无活动任务并完成数据库备份后重启本地 API/Worker，保留 Vite；readiness 通过，采集器与最新失败任务在重启前后比较均未改变。

AE-05 的独立五次调用验证遗漏 Worker 注入的需求合同，只能作为无该合同条件下的模型结果，不能证明此来源在实际任务上下文可成功。真实验证脚本已改用 Worker 等价上下文，但没有重新运行或覆盖历史结果。
