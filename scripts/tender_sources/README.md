# 招投标来源测试适配器

这是可独立重跑的匿名只读测试工具。它复用 Extrio 的 `SourceNetwork`、列表字段提取和严格标题比较，不修改生产网络策略，也不生成已发布的 GatherSpec。没有数据库、业务账号、定时任务、模型调用或投递模块。

## 运行

从仓库根目录使用已安装后端依赖的 Python：

```bash
backend/.venv/bin/python scripts/test-tender-sources.py \
  --all-discovered \
  --output /private/tmp/tender-results-example \
  --content-dir /private/tmp/tender-content-example \
  --pdf-python /absolute/path/to/python-with-pypdf
```

- `--sources ccgp csg fudan xmu hospital agency` 选择来源，默认全部六个。
- 默认每站 3 个列表页、最多 20 条详情。`--all-discovered` 处理这 3 页内发现的全部不同 URL，硬上限为每站 100 条，不表示全站历史采集。
- `--details N` 可指定 1 至 100 条，按页面轮流选取，避免样本只来自首页。
- `--output` 保存元数据、请求哈希、失败原因和分页证据。目标目录必须不存在。
- `--content-dir` 是可选的正文/结构化记录证据目录，必须在仓库外，目录权限为 0700。没有配置时不持久化正文。记录可能含公告公开的业务联系人信息，不应进入 Git 或直接对外分发。
- PDF 只处理公告正文中明确嵌入的公开 PDF，不遍历其他招标附件。解析依赖 `pypdf`；本工具不安装或下载依赖。

macOS 扫描 PDF 可选本地 Vision OCR：

```bash
swiftc -module-cache-path /private/tmp/tender-swift-cache \
  scripts/tender_sources/vision_ocr.swift -o /private/tmp/tender-vision-ocr
```

运行时增加 `--ocr-command /private/tmp/tender-vision-ocr --pdftoppm /absolute/path/to/pdftoppm`。Poppler 将页面转成图片，Vision 逐页识别；临时 PDF 和图片在处理结束后删除。OCR 文本始终标为待人工复核，不自动接收金额、截止时间等关键数据。没有配置 OCR 时，扫描件明确失败，不把空正文当成成功。

只重试传输/解析失败的详情，不重抓成功或待复核条目：

```bash
backend/.venv/bin/python scripts/test-tender-sources.py \
  --sources fudan --retry-from /absolute/path/to/previous/fudan.json \
  --output /private/tmp/tender-retry-example
```

PDF/OCR 参数与普通运行相同。复核条目不通过重试自动放行。

## 适配范围

| 来源 | 列表与分页 | 详情与质量检查 |
| --- | --- | --- |
| 中国政府采购网 | 采购列表；只解析已知 `Pager` 的字面参数，不执行 JS | 公告标题、发布日期、正文、摘要表中的采购单位/项目名/原始预算等 |
| 南方电网 | 采购列表与字面下一页；同一 URL 的完整 title 属性优先 | 无完整属性时，仅针对末尾截断标题，要求至少40字前缀、同日、面包屑与详情标题同时一致；不改全局标题规则 |
| 复旦大学 | 采购公告与字面下一页 | HTML、嵌入 PDF、公开原文跳转；HTTP政采原文跳转只尝试同路径HTTPS，不发送降级HTTP请求 |
| 厦门大学 | `curPage` 公开 GET 分页，校验当前页与总记录数 | 自有正文或页面明确链接的政采原文；保留发现页/原文两套标题、日期与来源关系，按项目名、采购单位和公告阶段核验 |
| 浙大一院 | 首页公告；后续使用官网脚本公开的 `content/get_article` GET 接口 | 限定栏目193，逐项提取发布日期，详情正文独立读取，不使用页脚日期 |
| 广东省机电设备招标中心 | 官网采购列表与字面下一页 | 精确放行 eps.gdebidding.com；跟随页面 iframe 与已知公开模板数据，核对列表/iframe/API的GUID及项目公告类型；只输出白名单业务字段，不声称还原全文或取得受限附件 |

URL 身份用于测试窗口内去重，不代表已经实现跨站项目/标段/公告类型去重。更正、结果和招标公告不合并为同一条记录。

## CSV 全清单核验

`scripts/test-tender-catalog.py` 对显式传入的 CSV 做匿名、静态、限量核验，不使用六站脚本的分页或 `--all-discovered` 模式。主表每行最多一页列表、两条本页发现的详情；待复核表默认只诊断一页列表，不抓详情。授权包含详情采样时，仅显式 opt-in 的待复核 ID 可采最多两条详情，原输入组和 ID 不变。没有付费模型、受限浏览器、PDF/OCR、附件下载、业务库、投递或来源调度。

```bash
backend/.venv/bin/python scripts/test-tender-catalog.py \
  --main-csv test-data/tender-sources/tender-source-lists.csv \
  --review-csv test-data/tender-sources/tender-source-lists-review.csv \
  --output /private/tmp/tender-catalog-example --dry-run

backend/.venv/bin/python scripts/test-tender-catalog.py \
  --main-csv test-data/tender-sources/tender-source-lists.csv \
  --review-csv test-data/tender-sources/tender-source-lists-review.csv \
  --output /private/tmp/tender-catalog-example --resume --group main --limit 20
```

后续保持两份输入和输出目录相同，使用 `--resume --group main` 处理剩余主表，再使用 `--resume --group review` 完成待复核诊断。`--limit` 限制本次处理行数，不改变完整输入分母。输出已存在时必须显式恢复；输入、实现指纹或限制变化拒绝混跑。已完成行和终态主机阻断不重跑，不能靠恢复重置预算。目录采用 POSIX 单进程锁，不可同时运行两个写入者。

待复核详情采样必须同时提供 `--entry-id "$REVIEW_ENTRY_ID" --sample-review-entry-id "$REVIEW_ENTRY_ID"`；仅接受 manifest 中真实的 review ID，不能省略本次显式选择、改成 main 或未知 ID。策略和策略 SHA 持久化；恢复时省略策略参数沿用原策略，显式改动拒绝。默认诊断不会隐式升级为详情采样。

- 同主机共享串行、至少 2 秒请求间隔、robots 缓存和熔断；最多 4 个不同主机并发。不自动信任 CSV 的样本详情 URL，也不扩大跨站主机或端口范围。
- 主表和显式 opt-in 的待复核详情采样每行最多 12 个底层请求，普通待复核诊断每行最多 3 个；每行 60 秒、单响应 2MB；全批累计最多 8000 个底层请求、1GB、90 分钟。robots、跳转与受控 TLS 兼容请求均计数，恢复不清零。
- 登录、限流、验证码、robots 拒绝或无法核验的 robots HTML 停止该主机；网络故障不反复重试。后续同站行明确标为继承阻断，而非声称逐页已验证。历史限制与本轮实际响应分别记录。
- `sample_readable` 只表示本轮静态样本通过标题、日期及主体门槛；`candidate_list` 只表示发现候选。未知模板、JS 壳、跨站原文、PDF及正文不完整保持待适配，不代表已签名规则、控制台原生采集、历史覆盖或增量验收通过。
- 高校、河南三站和浙师大模板采用精确主机、已证栏目路径及 DOM 结构提取，保留公共质量门槛；河南列表的独立标题字段与日期分离，不使用通用日期截断或放宽标题一致性。未知栏目不盲套模板。模板和实际网络/解析依赖均纳入代码指纹。
- 每项 JSON/CSV 保留输入组、行号、原始 URL、历史日期、实际请求和原因；完整分母包含未执行项。完成处理与采集成功分别统计，中断或预算耗尽不报完整采样完成。
- `ledger.json`、`rows.jsonl`、`matrix.csv`、`summary.json` 及请求 trace/私人样本写在仓库外的规范绝对路径，目录 0700、文件 0600。拒绝软链接路径和仓库内输出；macOS 使用 `/private/tmp` 而不是软链接 `/tmp`。CSV 对公式前缀做安全显示转义，原值保留于 JSON。

完整响应和正文可能包含公开联系人信息，不进入 Git 或发行包。robots 未发布、页面匿名可读均不是商业授权或全文再分发许可。全清单首轮范围见 [执行包](../../docs/reviews/catalog-validation-20261023/packet.md)，首轮原始矩阵口径及工具错误见 [首轮记录](../../docs/reviews/catalog-validation-20261023/verification.md)。处理完成不代表全部入口已采通。

## 复验矩阵合并

不同实现版本使用独立运行账本，原账本和样本不覆盖。本地合并器只读取 manifest 与真实逐行终态，不读取正文、不发送请求；没有新结果的入口保留原证据。基线、复验及模板批次的 SHA、代码、采样范围和历史判断均保留。

```bash
backend/.venv/bin/python scripts/merge-tender-catalog.py \
  --baseline /private/tmp/original-run/ledger.json \
  --overlay /private/tmp/retest-run/ledger.json \
  --overlay /private/tmp/template-run/ledger.json \
  --output /private/tmp/catalog-matrix-example
```

合并目标必须是仓库外全新的规范绝对路径，采用 0700/0600 权限。输入 manifest/ID、计数、终态和批次顺序须一致，未执行行不能覆盖已有结果。衍生 `matrix.csv` 区分 `baselineStatus`、`latestStatus` 和最新证据；`summary.json` 记录原始物理请求总量与最新归因请求数，不将它们混作“新增采集量”。143 入口复验及三包适配范围见[后续执行包](../../docs/reviews/catalog-followup-20261023/packet.md)，当前矩阵统计和验收边界见[复验结果](../../docs/reviews/catalog-followup-20261023/verification.md)。

## 六站脚本边界

每站串行、请求至少间隔2秒；每次最多240个底层请求、600秒、80MB总响应字节，单响应5MB，最多2跳重定向。嵌入正文PDF每源最多10个，每个最多40页；OCR最多10页并设独立进程超时。源站401/403/429、robots拒绝或明显访问挑战会停止该来源。没有代理轮换、登录、验证码、付费、CA、未公开接口探测或广泛子域名通配。

robots未发布不等于明确授权。匿名可读、业务投标、附件权限、商用使用和全文再分发应分别核验。测试适配器未接入控制台发布或生产调度。

## 验证

```bash
backend/.venv/bin/python -m pytest -q -c backend/pyproject.toml \
  backend/tests/test_catalog_template_university.py \
  backend/tests/test_catalog_template_henan.py \
  backend/tests/test_catalog_template_zjnu.py \
  backend/tests/test_catalog_followup.py \
  backend/tests/test_catalog_merge.py \
  backend/tests/test_tender_catalog.py \
  backend/tests/test_tender_catalog_network.py \
  backend/tests/test_tender_source_adapters.py \
  backend/tests/test_source_network.py \
  backend/tests/test_pagination_navigation.py \
  backend/tests/test_runtime.py
```

`summarize.py` 接受六个明确指定的来源结果及可选失败重试结果，校验正文哈希和原文公告阶段，生成不含正文的验收汇总及仓库外的记录证据。不会把开发轮次的重复请求计作新增公告。
