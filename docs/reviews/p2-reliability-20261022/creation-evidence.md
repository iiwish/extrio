# A002：创建来源重试与零创建结果

任务：`P2-RELIABILITY-20261022/A002`。日期：2026-10-22。状态：实现及定向回归通过，待主执行者全量验证和用户复核。分支：`codex/p2-reliability-20261022`。未提交、推送、发布或部署。

## 实现范围

- `web/src/features/collectors/new-collector-page.tsx`：沿用新建需求页的 payload/key 引用模式。相同 payload 的不确定重试保留同一 key；payload 改变生成新 key；收到确定结果后点“继续导入”清除旧引用。提交中禁用保护保留。
- `backend/src/extrio/app.py`：仅修改 batch collectors 结果的两个身份字段。新需求全部逐项拒绝时 `collectionId=null / collectionVersion=null`，不创建空需求；选择既有需求时，即使全部拒绝也保留真实既有身份与版本。
- `docs/contracts/api-contract.md`、`docs/contracts/openapi.yaml`、`web/src/api/generated/schema.d.ts`：同步 nullable 响应和逻辑命令 key 的合同。没有用 TypeScript 强制断言隐藏响应差异。
- `web/src/api/handlers.ts`：隔离 Mock 的零创建结果与真实 API 一致。
- `web/src/i18n/locales/{zh,en}/collectors.json`：零成功结果显示“未创建采集来源 / No sources created”；没有需求对象时明确“未创建采集需求 / No requirement created”。结果页不渲染不存在的需求详情链接，也不显示虚构版本。
- 回归：`backend/tests/test_collector_input.py`、`web/src/features/collectors/new-collector-page.ui.test.tsx`、`web/src/api/async-contract.test.ts`、`web/src/api/contracts.test.ts`。

`CollectionSourceDialog` 已使用稳定 payload/key，且不消费返回的身份生成导航，无需修改。`types.ts` 的现有生成类型别名自动传播 nullable；`client.ts` 已支持可选稳定 key，均无需修改。A001 的 `RunStartError(RuntimeError)` 改动完整保留。

## RED

业务实现前先添加正确预期测试，运行：

```sh
pnpm --dir web test \
  src/features/collectors/new-collector-page.ui.test.tsx \
  src/api/contracts.test.ts src/api/async-contract.test.ts

env -u EXTRIO_DATABASE_URL \
  EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_p2_test@127.0.0.1:32790/postgres \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_collector_input.py -k batch -q
```

- Web：7 failed / 13 passed。失败分别证明页面没有传入稳定 key、payload 变化没有显式新 key、零创建仍使用成功标题/无需求链接保护缺失，以及 OpenAPI/Mock 不接受或返回 null 身份。
- 后端 SQLite/PG16：4 failed / 2 passed。四项失败均是新需求全部拒绝时仍返回不存在的身份；已有需求全部拒绝和部分成功的控制用例通过。
- 初稿测试有一处测试基线计数和一处表单标签误写，均在业务代码修复前校正，再次确认上述 RED。没有把测试设置错误当作产品失败。
- 完整 RED 日志：`/tmp/extrio-p2-20261022/creation-web-red-confirmed.log`、`creation-backend-red-confirmed.log`。

## GREEN 与扩展回归

最小实现后：上述 Web 三文件 20 项通过；后端输入文件双库 38 项通过。随后增加新需求/既有需求两模式的丢响应参数化，以及错误复用 key 对改变 payload 的 409 控制断言，最终执行：

```sh
pnpm --dir web test \
  src/features/collectors/new-collector-page.ui.test.tsx \
  src/features/collectors/new-collector-page.test.ts \
  src/features/collections/collection-workflows.test.tsx \
  src/features/collections/collection-crud.test.tsx \
  src/api/contracts.test.ts src/api/async-contract.test.ts

env -u EXTRIO_DATABASE_URL \
  EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_p2_test@127.0.0.1:32790/postgres \
  /tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/test_collector_input.py \
  backend/tests/test_api.py backend/tests/test_collections.py \
  backend/tests/test_contracts.py -q

pnpm --dir web api:generate
pnpm --dir web lint
pnpm --dir web build
/tmp/extrio-health-20261022/backend-venv/bin/ruff check backend/tests/test_collector_input.py
git diff --check
```

- 最终 Web：6 文件 / **50 passed**，10.38 秒。
- 最终后端：**85 passed**，18.78 秒，SQLite 和独占 PG16 均覆盖；一个第三方 Starlette TestClient 弃用提示保留。
- API 类型生成、lint、TypeScript/Vite production build、定向 Ruff、diff whitespace 检查全部退出 0。
- 日志：`/tmp/extrio-p2-20261022/creation-web-final.log`、`creation-backend-final.log`。
- 测试包括：提交后响应丢失同 key 重试；改变 payload 新 key；确定结果后继续导入新 key；pending 双击只发一次；新需求全部拒绝无详情链接；既有需求全部拒绝保留真实链接；真实 API 同 key replay 原对象；不同 body 错误复用 key 为 409 且无额外写入；新需求全部拒绝不建空对象；部分成功不改变既有需求定义/归属。

## 边界与剩余风险

只使用本轮专用 PG16 的随机测试库及临时 SQLite/Artifacts/密钥。没有访问现有业务 API、真实来源或模型。此执行者没有创建长驻进程；PG 清理由主执行者统一负责。

`collectionId` 和 `collectionVersion` 的 null 语义是明确的公开响应合同修正，同仓库调用方、生成类型和 Mock 已同步。外部自编客户端应按更新后的 OpenAPI 处理零创建结果；没有修改历史幂等回执或用户数据库。现有已保存回执不会被重写。

本记录仅说明定向实现与回归，不代表全量测试、真实浏览器、Linux 镜像、签名/provenance 或发布摘要安装在此 attempt 重新通过。全量和桌面 QA 由主执行者汇总。需求、预算、来源唯一性、人工审核和签名边界没有放宽。
