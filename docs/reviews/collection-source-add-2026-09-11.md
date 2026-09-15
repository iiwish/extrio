# 需求内添加来源修复验收

## 范围

- 任务：修复需求详情添加来源的上下文中断与关联结果不可见。
- 执行：局部直接修复，沿用当前工作区已有实现，不回滚其他未提交工作。
- 实现文件：`web/src/features/collections/collection-source-dialog.tsx`、`collection-page.tsx`、`web/src/api/client.ts`、`web/src/features/collectors/new-collector-page.tsx`、中英文 common 文案及 `web/src/index.css`。
- 合同：同步 SSOT、product-contract、frontend-prototype、v0.2-acceptance 与文档清单。

## 检查结论

通用创建页允许选择其他需求或新建需求，且单来源成功后导航到来源详情；需求内操作缺少固定归属及关联列表落点。需求详情添加入口采用原地弹窗，直接提交当前需求 ID，成功后重新读取真实需求详情并选择关联来源分区。

后端按 Collection ID 持久化及读取来源的相关测试通过，未据此修改后端关联逻辑。浏览器核对发现，北京区级采购意向地址已有来源，列表归属为“标讯”；向“标讯测试”重复添加该地址返回 `SOURCE_ALREADY_EXISTS`。这证明重复添加不会建立新的关联，但不能单凭此次验证还原用户此前的全部操作。

## 验证

- `web: pnpm test`：36 个文件、181 个测试通过。
- 焦点恢复调整后重跑 `pnpm test src/features/collections/collection-page.test.tsx`：13 个测试通过。
- `web: pnpm build`：通过。
- `web: pnpm lint`：通过。
- `backend: uv run pytest tests/test_collections.py -q`：15 个测试通过；包含创建后立即按需求读取来源 ID 与 sourceCount。
- `backend: uv run python ../scripts/update-docset-manifest.py --check`：通过。
- `git diff --check`：通过。
- 浏览器：原地弹窗、固定需求、重复 URL 拒绝、输入保留、放弃确认已实测；1440x900、1280x800、1132x1028、1024x800 截图已检查，输入与按钮无重叠。
- 回归覆盖：固定 ID 提交、刷新关联列表与计数、保留搜索参数、失败保留输入、幂等重试、部分失败仅重试失败项、提交中禁用关闭与编辑、关闭后焦点恢复。

## 边界

- 未在用户数据中创建测试来源，成功路径由前端集成测试与真实后端 API 测试分别验证。
- 未迁移已有来源归属，未启动探索、发布或部署。
- 文件导入保留在原采集来源创建页面；需求内弹窗支持逐行批量输入。
- 全量前端测试有两条既有 jsdom 跨文档导航提示，不影响测试通过。
