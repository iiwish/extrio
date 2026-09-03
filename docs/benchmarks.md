# Extrio 基准说明

| 字段 | 内容 |
| --- | --- |
| 文档名称 | Extrio 基准说明（benchmarks） |
| 文档版本 | `v0.1.0` |
| 状态 | `Active` |
| 基准工具 | [`scripts/benchmark.py`](../scripts/benchmark.py) |
| 最后更新 | `2026-09-03` |

本文档说明 Extrio 采集执行管线的基准方法，并记录由 `scripts/benchmark.py`
实际运行产生的基线数字。所有结果数字均来自脚本的真实输出，不使用手写估算。

## 1. 基准目标与口径

基准度量的是“已发布固定规则 → 确定性采集 Run”这一核心执行管线的吞吐与延迟，
即运行期不调用 LLM 的那部分工作负载（对应不变量 `INV-001`）。

度量口径：

- **页面（pages）**：Run 抓取的列表页与详情页 HTTP 响应数量之和（`listPagesFetched + detailPagesFetched`）。
- **接收 Item（accepted）**：通过必填字段质量门并冻结进 accepted set 的 Item 数量。
- **运行耗时**：`Worker.process` 处理一次 Run 作业的墙钟时间，包括规则证明核验（attestation 验签）、
  页面抓取、字段提取、质量分类与持久化。
- **吞吐**：`页面/分钟`、`接收 Item/分钟`，分母为包含环境准备在内的总墙钟时间。
- **p50 / p95**：全部 Run 耗时样本的最近秩百分位。

## 2. 环境与数据源

| 项目 | 说明 |
| --- | --- |
| 数据源 | 仓库内置 demo 源（`backend/src/extrio/demo.py`）：北京市公共资源交易公告演示页，2 个列表页共 4 条公告（其中 1 条缺采购单位，用于可选字段路径） |
| 源承载方式 | 基准进程内启动 uvicorn，仅挂载 demo 路由，绑定 `127.0.0.1` 随机端口；全程无外部网络访问 |
| 规则 | 每个采集器使用一份手写固定 GatherSpec（`extrio.gather.v1`，两阶段 `list_detail`，`page` 分页，maxPages=3），发布路径与生产一致（Ed25519 RuleAttestation），不调用 LLM |
| 存储 | 每次基准运行使用独立临时 SQLite 数据库与临时 artifact/key 目录（`EXTRIO_DATABASE_URL` 等），结束后自动删除，不污染真实部署数据 |
| 执行路径 | 复用生产代码路径：`create_run_operation` 构建 Run 与固定完整性上下文，`Worker.process` 完成核验、抓取（Crawlee ParselCrawler，HTTP 传输）、质量分类与 Checkpoint 推进 |

每次基准运行的数据完全确定：每次 Run 抓取 3 个列表页 + 4 个详情页 = 7 页；
首次 Run 接收 4 个新 Item，同一采集器的后续 Run 以增量模式复跑同一数据，
4 个 Item 全部判定为未变化（指纹字段未变化），Checkpoint 不回退。

## 3. 运行方式

```bash
uv run --project backend python scripts/benchmark.py --collectors 3 --pages 2
```

参数：

- `--collectors N`：创建的临时采集器数量（默认 3）。
- `--pages M`：每个采集器执行的采集 Run 次数（默认 2）。

任一 Run 未达到 `succeeded` 终态时脚本以非零退出码失败；全部成功时输出
汇总表和一段可直接粘贴进本文档的 Markdown 数据块（带生成注释标记）。

## 4. 基线结果

<!-- 以下数据块由 scripts/benchmark.py 实际运行生成，请勿手写数字。 -->

- 运行参数：`--collectors 3 --pages 2`（3 个采集器 × 2 次运行 = 6 次）
- 运行日期：2026-09-03
- 环境：Python 3.12.13 / macOS-26.5.2-arm64-arm-64bit
- 存储：临时 SQLite（每次基准运行独立创建，结束后删除）
- 数据源：本机 demo 源 `http://127.0.0.1:56798/demo/tenders`（进程内 uvicorn，无外部网络）

| 采集器 | 运行 | 终态 | 停止原因 | 列表页 | 详情页 | 页面合计 | 接收 | 拒绝 | 变化（新增/更新/未变） | 耗时 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | succeeded | next_link_exhausted | 3 | 4 | 7 | 4 | 0 | 4/0/0 | 0.57 |
| 1 | 2 | succeeded | next_link_exhausted | 3 | 4 | 7 | 4 | 0 | 0/0/4 | 0.94 |
| 2 | 1 | succeeded | next_link_exhausted | 3 | 4 | 7 | 4 | 0 | 4/0/0 | 0.92 |
| 2 | 2 | succeeded | next_link_exhausted | 3 | 4 | 7 | 4 | 0 | 0/0/4 | 0.89 |
| 3 | 1 | succeeded | next_link_exhausted | 3 | 4 | 7 | 4 | 0 | 4/0/0 | 0.60 |
| 3 | 2 | succeeded | next_link_exhausted | 3 | 4 | 7 | 4 | 0 | 0/0/4 | 0.63 |
| **合计** | | | | | | **42** | **24** | **0** | **12/0/12** | **6.34** |

吞吐：**397 页/分钟**、**227 接收 Item/分钟**；单次运行耗时 p50 = **0.63s**、p95 = **0.94s**。

### 4.1 结果解读

- 全部 6 次 Run 达到 `succeeded` 终态，停止原因均为 `next_link_exhausted`（demo 源第 3 页为空后自然停止）。
- 每个采集器的第 1 次 Run 为初始模式（新增 4 Item），第 2 次 Run 为增量模式
  （复用 Checkpoint，4 Item 全部未变化），验证了增量回看窗口与去重路径。
- 单次 Run 耗时在 0.5–1s 量级，主要成本是每次抓取批次内 Crawlee 爬虫的初始化
  与事件循环开销，而非页面传输（本机回环）。
- 本基线反映的是确定性执行管线的本地开销，不代表真实外网站点或生产容量
  （容量包络见 [`product-contract.md`](./product-contract.md) 第 8 节）。

## 5. 边界说明

- 本基准不覆盖：浏览器传输（Crawl4AI）路径、Webhook/Kafka 交付吞吐、LLM 探索与规则编译耗时、PostgreSQL 后端。
- 数字依赖运行机器与并发环境，仅用于同机回归对比；跨机器比较时应重新采集基线。
- demo 源的公告内容固定，因此数据路径确定；耗时数字存在正常抖动。
