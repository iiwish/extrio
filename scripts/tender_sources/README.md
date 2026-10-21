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

## 边界

每站串行、请求至少间隔2秒；每次最多240个底层请求、600秒、80MB总响应字节，单响应5MB，最多2跳重定向。嵌入正文PDF每源最多10个，每个最多40页；OCR最多10页并设独立进程超时。源站401/403/429、robots拒绝或明显访问挑战会停止该来源。没有代理轮换、登录、验证码、付费、CA、未公开接口探测或广泛子域名通配。

robots未发布不等于明确授权。匿名可读、业务投标、附件权限、商用使用和全文再分发应分别核验。测试适配器未接入控制台发布或生产调度。

## 验证

```bash
backend/.venv/bin/python -m pytest -q -c backend/pyproject.toml \
  backend/tests/test_tender_source_adapters.py \
  backend/tests/test_source_network.py \
  backend/tests/test_pagination_navigation.py \
  backend/tests/test_runtime.py
```

`summarize.py` 接受六个明确指定的来源结果及可选失败重试结果，校验正文哈希和原文公告阶段，生成不含正文的验收汇总及仓库外的记录证据。不会把开发轮次的重复请求计作新增公告。
