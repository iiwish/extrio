# 高校模板包证据

任务 `CATALOG-FOLLOWUP-20261023/A001`。代码仅负责从已证实的高校详情 DOM 提取原始标题、发布日期字段和正文 Tag，不自行判定公告可采。真实响应、正文和联系人均保留在仓库外，本包没有发出网络请求。

## 结构与覆盖

候选池为 16 个精确主机的 49 个主表 `index.chtml` 入口及 22 个对应复核入口；路径相似不代表同一模板。对原私有批次 `/private/tmp/extrio-catalog-20261023` 的保存响应进行只读分析，涉及 96 份主表详情响应。每份响应的 SHA-256 均与原 trace 相符。

其中 15 个主机、46 个详情栏目路径的 94 份响应具有以下共同结构：

- `div.wrap` 内唯一的 `div.ctitle`，直接子节点 `h1` 为标题。
- `div.ctitle > div.info > i` 的独立“发布日期”字段为日期来源；94 份字段均为无嵌套标签的独立 `i`。
- 唯一 `div.ccontent` 与 `div.ctitle` 同父；正文范围不含相邻附件、上一条/下一条链接或页脚。

范围白名单见 `scripts/tender_sources/catalog_template_university.py` 的 `OBSERVED_COLUMNS`。精确主机包括 `zhbb.cumt.edu.cn`、`caigou.ucas.ac.cn`、`cgzx.cpu.edu.cn`、`cgxx.ecnu.edu.cn`、`czzx.ecust.edu.cn`、`cgzx.hust.edu.cn`、`czzx.njau.edu.cn`、`zbb.njau.edu.cn`、`zbb.nju.edu.cn`、`zb.nju.edu.cn`、`nkzbb.nankai.edu.cn`、`ztb.xmu.edu.cn`、`cgyztb.whut.edu.cn`、`cwcggl.swpu.edu.cn`、`cg.qdu.edu.cn`。南开 14 份、西南石油 10 份均符合上述框架。模块不把同主机的未知栏目自动纳入白名单。

原响应集指纹为 `080db0fe2a309dcc892c17649eba8ae693593353235e56a62c52535199a8d9be`，计算方式：按原 trace 文件名排序，将每份详情的 `url + NUL + trace.sha256` 以换行连接，再取 SHA-256；只包含 URL 和响应哈希，不包含正文。

## 离线回放

| 指标 | 结果 |
| --- | ---: |
| 读取且校验响应哈希 | 96 |
| 精确主机/栏目/DOM 提取匹配 | 94 |
| 匹配且原始标题非空 | 94 |
| 匹配且独立发布日期字段非空 | 94 |
| 匹配且正文 Tag 存在 | 94 |
| 匹配正文内有 iframe/object/embed | 11 |
| 不匹配且保留待适配 | 2 |

上述 94 是结构提取匹配数，不是详情质量通过数。11 个嵌入正文保留原节点供公共质量门槛拒收；不执行嵌入链接、PDF 或原文跳转。

中国药科大学 `/dyly/` 的两份响应不具备该详情结构，返回 `None`；西安电子科技大学没有保存详情响应，不加入适配白名单。复核池的新栏目、下载/办事路径及未知结构保持待适配，不能据本包宣称全池采通。

## 回归验证

合成测试在实现前执行，因模块不存在产生 `ModuleNotFoundError`，退出码 2。补充空 `ctitle` 未知结构反例后得到真实断言失败：`1 failed, 100 passed`；最小结构判别修复后为 `101 passed`。所有测试内容均为最小合成 DOM，没有复制真实正文。

测试覆盖 46 个已证栏目、HTTP 和中文栏目编码、未知/相似主机、未知/下载/办事路径、未证 CPU/西电栏目、列表页、错误端口/协议/用户信息、重复或混合详情容器、缺标题/日期/正文、页脚与导航日期污染、元信息排序、嵌入/PDF/原文指针保留，以及不修改原始 DOM/日期。未来日期、标题一致性、正文长度/公告语义与非导航正文门槛交由 catalog 集成回归验证，本模块不放宽这些门槛。

使用隔离解释器 `/tmp/extrio-health-20261022/backend-venv/bin/python`：

```sh
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_catalog_template_university.py -q
# 101 passed in 0.16s
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_catalog_template_university.py backend/tests/test_tender_catalog.py -q
# 178 passed in 0.42s
/tmp/extrio-health-20261022/backend-venv/bin/ruff check scripts/tender_sources/catalog_template_university.py backend/tests/test_catalog_template_university.py
# All checks passed!
```

模块 SHA-256：`e4524694010fdb900567015883770ad46af5065c461df868d0de21bc4b524db8`。测试 SHA-256：`8496a1ad339a27a39c9c657ff15d7e19574686b7eb9655e1fe5fa5c7a54d5655`。

本单元不修改 catalog/runner、生产后端、Web、CSV、原输出或数据库；不启用模型/调度，不执行提交推送、合并、发布或部署。真实限量采样、矩阵更新、公共质量门槛集成和完整回归由主执行者完成。
