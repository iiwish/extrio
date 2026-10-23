# 恢复调度启动拒绝修复

任务 `P2-RELIABILITY-20261022`，attempt `A001`。日期：2026-10-22。执行范围和用户授权见 [packet.md](packet.md)。实现及定向验证完成，等待主执行者 review；不表示稳定版签收或发布授权。

## 修改范围

- `backend/src/extrio/app.py`：`RunStartError` 继承 `RuntimeError`，进入恢复调度已有的预期启动拒绝处理分支。异常的 code/message/status 和显式 HTTP、MCP、调度调用方处理不变。
- `backend/tests/test_bounded_recovery.py`：为恢复 seed 提供不同 host 的真实候选/签名规则构建；增加五个逻辑回归节点，PG 参数路径共十个节点。
- 本证据文件。没有修改 `bounded_recovery.py`、数据库 schema、签名校验、请求预算、权限或自动重试策略。

## 验收断言

1. 合法恢复批次冷却期间，签名 key 分别变为 `retired`、`compromised` 后，到期 dispatch 不抛未处理启动拒绝，批次持久化为 `needs_attention / dispatch_rejected`。
2. 无不可信 Run 入队，无预算预留，无新 attempt；来源进度、调度关闭状态和原始失败 Run 保留。后续 tick 不再次尝试该终态批次。
3. 第二个不同 host、不同有效签名 key 的真实恢复批次在同一 tick 仍启动一次；预算为 120，请求上限、签名完整性、恢复关联与原覆盖断点固定。原始两个 Run 不变，后续 tick 不重复入队。
4. 未知 `KeyError` 继续抛出并回滚，不伪装成正常启动拒绝。没有增加 `except Exception`。

## RED

仅加入正确预期测试、尚未修改异常基类时运行：

```sh
env -u EXTRIO_TEST_DATABASE_URL -u EXTRIO_DATABASE_URL \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_bounded_recovery.py \
  -k 'untrusted_signing_key or signing_rejection or unknown_dispatch_error' -q
```

实际退出 1：**4 failed / 1 passed / 16 deselected**，4.84 秒。四个退役/失信场景都失败于真实 `create_run_operation` 抛出的 `RunStartError: signing key is not trusted for new Runs`。不同 host 的第二批次已成功建立，不是 fixture 失败。未知异常可见性对照在修复前即通过。

## GREEN

将 `RunStartError(Exception)` 改为 `RunStartError(RuntimeError)` 后：

```sh
env -u EXTRIO_TEST_DATABASE_URL -u EXTRIO_DATABASE_URL \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_bounded_recovery.py -q
```

实际退出 0：**21 passed**，6.10 秒。包含本次新增节点和原有冷却、期限、预算、重启、幂等、租约、取消、同域互斥和只读权限回归。

使用主执行者创建的本轮独占临时 PG16，再运行签名/密钥/调度关联测试：

```sh
env EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_p2_test@127.0.0.1:32790/postgres \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_bounded_recovery.py \
  backend/tests/test_integrity.py backend/tests/test_key_operations.py \
  backend/tests/test_schedule_recovery.py -q
```

实际退出 0：**71 passed / 0 skipped**，24.95 秒；fixture 为 SQLite/PG 创建独立临时库并清理，不访问既有数据库。PG 容器的最终清理由主执行者统一负责，本 attempt 未停止该共享测试资源。

```sh
/tmp/extrio-health-20261022/backend-venv/bin/ruff check \
  backend/src/extrio/app.py backend/src/extrio/bounded_recovery.py \
  backend/tests/test_bounded_recovery.py
git diff --check -- backend/src/extrio/app.py backend/tests/test_bounded_recovery.py
```

两项均退出 0，Ruff 输出 `All checks passed!`。未额外重构运行期代码。

## 设计与剩余边界

恢复分发已有 `(ValueError, RuntimeError)` 捕获和持久化 `dispatch_rejected` 路径。启动被拒绝属于预期运行期命令错误，调整其异常基类使所有标准拒绝进入该路径，比引入循环依赖、重复异常类型或扩大为全部异常捕获更小。现有显式捕获 `RunStartError` 的入口继续保留 HTTP 错误合同。

本 attempt 的测试使用冻结 `/tmp` Python 3.12.13 环境及本地合成数据。一个第三方 Starlette TestClient 弃用提示保留，未过滤。全量后端/前端、文档一致性及桌面 QA 由主执行者汇总；本 attempt 不把定向 71 项冒称为全量回归。

没有提交、推送、发布、部署、重启业务实例、真实来源请求或付费模型调用；没有改共享 `backend/.venv`。本 attempt 已结束全部命令 session，并交还 `app.py` 给后续串行 attempt。
