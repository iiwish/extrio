# A004 集成与证据合并验证

任务 `CATALOG-FOLLOWUP-20261023/A004`。实现状态为离线工程验证完成，待主执行者独立审计及真实采样；本单元不执行真实网络请求。

## 实现合同

`catalog_merge.py` 与 `scripts/merge-tender-catalog.py` 是纯本地合并器，只读取指定 ledger JSON，不读取正文、联系人样本或调用网络。按 baseline 和显式 overlay 顺序，以实际 results 的稳定 entry ID 覆盖最新视图；缺失行保留原结果，不接受 not_executed、running 或未知 ID 冒充新证据。输入 manifest/fingerprint、终态、批次时间、请求计数、继承停止、单行物理请求上限与采样策略均核对。输出保留 baselineStatus、latestStatus、reason、逐次 history、来源批次/path、ledger/code 指纹、samplingScope 和 independentlyTested；物理总请求和最新归因请求分开汇总，组内状态和计数可追溯。合并算法及 CLI 自身指纹在 summary 中保存。

合并输出必须是仓库外全新目录，0700/0600，拒绝 symlink、仓库内输出和覆盖。CSV 按显示值转义公式前缀，JSON 保持原值。CLI stdout 只输出聚合和输出路径；详细 143 行差异保留在私人 summary/JSONL，不把大批逐行内容刷入日志。

`catalog.py` 连接三个精确模板的 `extract_detail(soup, url)` 原始字段提取。已匹配模板标记 `templateId` 和 `html_template_candidate`；未知结构保守回退通用静态检查。缺失详情标题或日期不从列表回填。标题一致、真实且非未来日期、公告语义、正文长度、非链接正文占比、PDF/iframe/原文指引等共享门槛保持生效。河南列表仅对经证据限定的主机、路径及 DOM 调用 `list_title`，从独立 item-title 取标题，日期仍走原 row-date；未知主机/结构不做全局正则剥日期或放宽标题一致性。

`CatalogRunner(..., sample_review_entry_ids=...)` 和 CLI `--sample-review-entry-id` 提供显式复核详情采样。只允许 manifest 中 review ID，并要求该策略的全部 ID 仍在本次显式 `--entry-id` 选择中；group 排除 review 不能偷偷采样。默认 review 只诊断列表、3 次物理请求；显式 opt-in 最多两条详情、12 次物理请求。原 group/ID 不变，逐行 samplingScope 和 summary 的 samplingPolicy 明确区分深度。

samplingPolicy 及自身 SHA 持久化；resume 未提供新策略时沿用保存策略，不静默清除，显式不同策略或损坏指纹拒绝恢复。本次代码指纹包括 catalog/runner、adapters、三个模板、SourceNetwork、public_pagination、harvest、pagination、contracts、integrity 和 official_documents。网络公开 IP/robots/精确主机/TLS/HTTPS 禁降级、全局主机锁/节奏/熔断及所有预算保持原约束。

## RED / GREEN

- 合并器首次测试因尚无模块收集 RED；最小实现后 10 项通过。计数缺少终态、伪可读零请求、单行超过上限、非法 stopReason 后续反例实际 **4 failed、12 passed**；严校验完成后全部通过。合成 1364 行 manifest 加 54 main/89 review 的 143 条 overlay，验证总分母、组内覆盖和未复测行证据均保留。
- 集成/策略首次实际 **8 failed、4 passed**：模板日期和身份缺失、review 无 opt-in 接口、解析依赖未入指纹。补齐实现后通过；默认 review 不发详情为负控制。
- 保存的 samplingPolicy 被改写但 resume 空参数仍接受的反例实际 **1 failed**；加入策略 SHA 和合法 ID 校验后通过。
- ZJNU 中文 `版权` 日期字段端到端反例实际 **1 failed、30 passed**。原模板 worker 修复其 chrome 排除后，本单元端到端拒收及三模板全局门槛回归通过；本单元未修改模板 worker 文件。
- review 预算合成重定向链实际证明默认只发 **3** 请求，显式采样可到 **12** 请求，所有 robots/重定向均计入，不把默认放宽。

最终离线命令：

```text
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_tender_catalog.py backend/tests/test_tender_catalog_network.py backend/tests/test_tender_source_adapters.py backend/tests/test_source_network.py backend/tests/test_catalog_followup.py backend/tests/test_catalog_merge.py backend/tests/test_catalog_template_university.py backend/tests/test_catalog_template_henan.py backend/tests/test_catalog_template_zjnu.py -q
459 passed in 1.90s

/tmp/extrio-health-20261022/backend-venv/bin/ruff check scripts/tender_sources/catalog.py scripts/tender_sources/catalog_run.py scripts/tender_sources/catalog_merge.py scripts/merge-tender-catalog.py backend/tests/test_catalog_followup.py backend/tests/test_catalog_merge.py
All checks passed!

git diff --check
(exit 0)
```

## 边界

原始清单、私人原始 ledger/trace/results、生产后端、Web、数据库和服务均不由本单元修改。没有调用付费模型、启调度、提交、推送、合并、发布或部署。原始 143 行及后续模板采样结果只有主执行者真实执行回执可以更新，离线通过不能替代真实采样、完整历史/分页/增量或原生签名规则验收。
