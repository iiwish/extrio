# STABLE1 安全边界证据

状态：动态边界证据完成；稳定版残余风险待用户单独决策。本文不批准发布，不关闭告警。

## 漏洞与依赖

2026-09-27 核对 [NLTK 官方公告](https://github.com/nltk/nltk/security/advisories/GHSA-8mgp-746c-j5xp)
与 [Dependabot #1](https://github.com/iiwish/extrio/security/dependabot/1)：
GHSA-8mgp-746c-j5xp / CVE-2026-81726，HIGH，受影响范围 `<= 3.10.3`，
`first_patched_version=null`，告警为 `open`。本地安装链为 `crawl4ai 0.9.2 -> nltk 3.10.3`；
Crawl4AI 的基础依赖包含 `nltk>=3.9.1`，并非只由可选 extra 引入。

公告涉及 6 个模型读写 API：`TransitionParser.train/parse`、
`AveragedPerceptron.save/load`、`PerceptronTagger.save_to_json`、`save_maxent_params`。
依赖自身的路径约束绕过没有被本次修改修复。Extrio 不以 NLTK `pathsec` 作为应用隔离边界。

## 被测边界

新增 `backend/tests/test_nltk_boundary.py`，共 15 个测试。无生产代码、依赖或扫描策略修改。
测试以实际函数的 Python code object 观察调用，覆盖事先导入的函数别名；探针在调用入口先记录再抛错，
应用测试另断言记录为空，避免第三方捕获异常后假通过。无命中时还验证探针保持启用。
观察范围是当前线程及安装探针后创建的线程。

| 验证面 | 结果 |
| --- | --- |
| 6 个受影响 API 的逐个正控制 | 每次均记录准确 API 名并阻止其执行；目标文件未创建 |
| 新建 worker 捕获探针异常的正控制 | 异常被捕获后调用记录仍存在，不能隐藏命中 |
| `nltk.download` 正控制 | 下载入口被探针识别并阻止，无模型数据下载 |
| 实际 RestrictedBrowser / Chromium | 本地异步 DOM 实际请求 `/async` 与 `/single`；HTML 保留注入路径文本且未出现 canary 内容，文件/目录保持不变，受观察 API 无调用；文件 URI、绝对路径、`..` 与符号链接路径作为来源 URL 均被 `invalid_url` 拒绝 |
| 实际 CrawleeRuntime，HTTP 与 browser 各一条 | 完成列表到详情，产出 accepted Item；路径攻击文本被实际选择器提取为普通源数据；受影响 API 与下载入口调用均为 0 |
| 实际 Crawl4AIExplorer + ModelRuleCompiler | 实际浏览器取样，执行 discovery / compile 两轮及合同验证；模型配置与 completion 使用本地 fixture，不调用真实模型；注入 `modelPath/modelExportPath` 未进入规范化 RulePlan 或 GatherSpec |
| GatherSpec 配置负向验证 | `sourceContext`、`compiler`、`collect` 三处额外 `modelPath` 均被 schema 拒绝 |

路径样本位于 pytest 临时目录，包含绝对路径、父目录穿越、`file://`、符号链接及写出目标。
`NLTK_DATA` 与 `nltk.data.path` 指向专用数据目录；目录外 canary 的内容和文件清单在测试结束保持不变。
这些是应用输入的负向测试，不是 `pathsec` 隔离性验证，也不声称修复了 NLTK 本身。
应用正常写出的 HTML 与规则审计产物不属于 NLTK 模型产物。

静态检索 Extrio 与安装的 Crawl4AI 代码，未发现上述受影响 API 或 `nltk.data.path` 调用。
Crawl4AI 仍包含 NLTK 分句、分词、语料与 punkt 下载路径；不能由“未发现这些模型读写 API”推出整个依赖无风险。

## 验证命令

工作目录为仓库 `backend`，使用现有 `.venv`，未运行 `uv sync`：

```sh
.venv/bin/pytest tests/test_nltk_boundary.py -q
.venv/bin/pytest tests/test_nltk_boundary.py tests/test_security.py tests/test_browser_failures.py tests/test_model_gateway.py -q
.venv/bin/ruff check tests/test_nltk_boundary.py
```

独立边界测试：`15 passed`。关联回归：`49 passed`。Ruff：通过。
完整回归、镜像验证与双架构扫描由主任务集成；本文不把本地测试替代这些门槛。
原始输出保存在忽略目录 `backend/data/v1-stable-20260927/security-focused.log`；
脱敏告警快照为同目录 `security-dependabot-1.json`。

依赖核对命令为 `gh api repos/iiwish/extrio/dependabot/alerts/1`，版本来自 `importlib.metadata`。
静态检索命令为：

```sh
rg -n --no-ignore 'TransitionParser|AveragedPerceptron|PerceptronTagger|save_maxent_params|nltk\.data\.path' backend/src/extrio backend/.venv/lib/python3.12/site-packages/crawl4ai
```

结果无匹配（退出码 1），只作为有限动态测试的辅助证据。

## 残余风险与决策

被测应用路径没有触发公告 API，支持当前功能面的有限暴露评估，不构成全局不可达证明。
测试不覆盖探针安装前的 import 初始化、既存其他线程、所有第三方可选策略、任意未来规则或依赖变更，
也不证明容器文件权限能消除该漏洞。未使用真实模型、外部来源或生产环境测试。

建议允许提交未发布候选 PR，但稳定版发布保持 `Requires Decision`：等待可验证的上游修复，
或由用户明确接受针对稳定版的限定风险。例外须绑定候选版本/摘要、禁止开放任意模型文件路径、
保持告警与扫描可见，并在引入 NLP 模型读写能力或更新相关依赖时重新验证。
RC 风险接受不延伸到 stable；本报告不是风险接受、漏洞关闭或 stable Accepted 的依据。
