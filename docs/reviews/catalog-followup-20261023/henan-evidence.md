# 河南交易中心模板包证据

执行单元 `CATALOG-FOLLOWUP-20261023/A002`。范围是内乡、南阳、镇平三个精确主机的静态交易列表与详情字段提取；不包含其他河南站点、分页、跨站原文、PDF/OCR、附件读取或原生采集器规则。

## 接口和范围

- `scripts/tender_sources/catalog_template_henan.py` 提供 `extract_detail(soup, url) -> tuple[str, str, Tag | None] | None` 和 `list_title(anchor, url) -> str | None`。后者的 `url` 是当前列表 URL，不是详情 URL。
- 主机仅 `ggzyjyzx.neixiangxian.gov.cn`、`ggzyjy.nanyang.gov.cn`、`ggzyjyzx.zhenping.gov.cn`。URL 必须使用 HTTP/HTTPS 和标准端口，不接受用户信息、查询参数、片段、控制字符或相近域名。
- 详情路径是各主机已存响应证实的 category 白名单，加八位日期目录、UUID 文件名和 `.html`。未知主机、路径或页面结构返回 `None`。
- 内乡详情 category 为 `002001/002001002`、`002001/002001004`、`002001/002001005`、`002002/002002001`、`002002/002002003`。
- 南阳详情 category 为 `002001/002001002`、`002001/002001005`、`002002/002002001`、`002002/002002003`。`002001/002001004` 的已存列表不构成详情结构证据。
- 镇平详情 category 为 `002001/002001004`、`002001/002001005`、`002001/002001008`、`002002/002002003`。`002002/002002001` 的已存列表不构成详情结构证据。
- 列表按独立的逐主机白名单覆盖已保存的 20 个路径，包括聚合 `transactiontop.html`、镇平 `002002/transaction.html` 及已保存的两个 `002003/002003002/transaction.html`。列表标题提取不赋予跨站详情访问能力；后者仍由共同边界拒收。

## 保存响应结构证据

只离线读取 `/private/tmp/extrio-catalog-20261023` 的原批次响应及请求元数据，校验每个读取响应的 SHA-256 与对应 trace 相同。没有发起网络请求，没有更改原矩阵或账本，没有输出或写入真实公告正文及联系人。

- 20 个列表响应，每页 10 个候选，200 个锚点均具有完整父链 `.container.box > .box-con.public-box > .public-con > .box-content > #info-list.public-list > a.public-list-item[href]`。
- 锚点直系 `.item-title` 是公告标题，直系 `.item-date` 是独立日期。提取标题只读取 `.item-title`，不进行通用日期字符串截断，因此标题自身包含的日期得以保留。
- 28 个详情响应、24 个唯一详情 URL，分布为内乡 10、南阳 8、镇平 10。28 个响应均具有唯一 `.container.box > .box-con`，直系 `.box-header`、`.browse > .browse-main > .browse-item`，以及 `.box-content > .box-infor > #infoContentM.box-article`。
- 发布日期仅取详情元数据中以明确“发布时间”标签开头的唯一字段；不读取页脚、来源、更新时间、列表日期或 URL 日期。空字段及歧义字段返回空串，供共同质量门槛拒收。
- 共同布局的 `body.has-footer` 是整页布局标记，不是页脚区域。正文、元数据或祖先的实际 `footer/nav/header` 区域及其版权、导航标识仍排除。
- 正文返回原始 Tag，不删除 iframe/object/embed 或导航以伪造完整正文；共同质量门槛负责嵌入、PDF、导航占比、长度和公告语义拒收。

代表性详情响应哈希：

| 主机 | 私有样本 | SHA-256 |
| --- | --- | --- |
| 内乡 | `samples/request-00136.body` | `f42eb9ec2d3804625cc83d8e6ca16ea87d3254cf49a467a7b96ad8265ecbf6e0` |
| 南阳 | `samples/request-00137.body` | `039d1c12f5eac9f1c96c9fd0ec0b558ba7e68633e7b4bb984aabb03913b57e7b` |
| 镇平 | `samples/request-00153.body` | `73e36d986ff7709d45b802c66c57f8c60146fdf0e78fb490210c49f9921a24bb` |

使用独立的列表标题字段与详情原始字段离线比对，28 个响应的标题一致性、日期一致性、公告标题语义、正文不少于 100 字符、非导航正文占比、采购正文语义及无嵌入检查均为 28/28。该结果是原批次保存样本的离线重解析，不是本轮真实网络复验，不代表近 30 天覆盖、增量或生产就绪。

## 回归和检查

测试仅采用最小合成 HTML，不包含真实公告正文、联系人或真实公告标题。

- 初始接口 stub 的 RED：`27 failed, 21 passed`。
- 嵌套版权日期和导航标题的 RED：`2 failed, 48 passed`。
- `body.has-footer` 合成回归的 RED：`1 failed, 50 passed`。
- 列表独立标题字段接口 stub 的 RED：`5 failed, 66 passed`。
- 最终 GREEN：`71 passed in 0.09s`，覆盖三个主机及保存 category、20 个列表路径、缺字段、错误域名/路径/端口、页脚日期、重复字段、未知 DOM、导航正文、嵌入正文、未来日期原样交给共同门槛、标题自身含日期、缺标题不借日期和不修改输入 DOM。
- Ruff：`All checks passed!`。

执行命令：

```sh
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_catalog_template_henan.py -q
/tmp/extrio-health-20261022/backend-venv/bin/ruff check scripts/tender_sources/catalog_template_henan.py backend/tests/test_catalog_template_henan.py
```

交接代码 SHA-256：`3f223cff07bc5053794395b4a2650c77d183e55de8ec27b6310ac7215d3c1bf5`；测试 SHA-256：`6dda7c2e6aae7f04c197bd94e44f080fed5ba33fcc75bef7860e86819dc689a4`。

后续集成保持共同 `titles_consistent`、发布日期和正文质量门槛不变。缺乏详情证据的两个复核 category 保守待适配；新增证据必须另行记录，不能把保存列表或离线提取记作实测成功。本单元没有改动 catalog/runner 核心、生产后端、现有业务库、调度或模型配置，没有执行提交、推送、合并、发布或部署。
