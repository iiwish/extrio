# Extrio RulePlan v1 语义合同

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 规范标识 | `extrio.rule-plan.v1` |
| 文档版本 | `v1.0.0` |
| 状态 | `Confirmed` |
| JSON Schema | [`rule-plan.schema.json`](./rule-plan.schema.json) |
| 下游合同 | [`gather-spec.md`](./gather-spec.md) |
| 最后更新 | `2026-09-01` |

## 2. 定位

RulePlan 是 Source 接入期的受约束编译中间表示。LLM 负责从非可信网页样本理解记录边界、页面拓扑和字段位置，并输出 RulePlan；平台负责 Schema、语义、安全和样本校验，再把合法 RulePlan 编译成不可变 GatherSpec。RulePlan 不是运行时 prompt，也不是可执行代码。

生产 Run 不读取 RulePlan、模型设置或 API Key，只解释已发布 GatherSpec。Source 结构漂移需要重新采样、重新编译、审核和发布，不允许运行时自行改写规则。

## 3. 执行模型

- `single`：入口响应本身就是一个 Item；`list` 阶段同时承担输出提取，分页固定为 `none`。
- `list_detail`：`list.itemsSelector` 定义 Item 边界，列表字段在每个 Item 节点内求值；`detailUrl` 交接到同一 RuleVersion 的详情阶段，详情字段形成业务输出。
- `transport=http`：运行时保存并解析原始响应字节，避免中间 DOM 序列化改变已验证 selector 的语义。
- `transport=browser`：只使用受限浏览器获取渲染后 HTML，仍由相同字段解释器执行规则。
- `responseType=html` 使用 `css:`；`responseType=json` 使用 `jsonpath:`。

## 4. 字段规则

每个字段具有稳定 ASCII key、用户可读 label、selector、类型、必填性、错误策略、多匹配策略和 transforms。支持的值类型为 `string`、`integer`、`number`、`boolean`、`datetime`、`url`、`html` 与 `json`；支持的 transforms 为 `trim`、`collapse_whitespace`、`lowercase`、`uppercase`、`absolute_url` 与 `strip_html`。

HTML selector 相对当前列表 Item 或详情文档执行，并以 `::text`、`::html` 或 `::attr(name)` 明确取值。JSONPath 相对当前 JSON Item 或响应执行。必填字段不得使用 `onError=null`；列表阶段和详情阶段的必填字段都参与 Item 质量终结。

## 5. 语义绑定

`bindings` 把任意站点字段映射到平台兼容展示角色，而不要求网站使用固定字段名：

| 角色 | 用途 |
| --- | --- |
| `detailUrl` | list → detail 请求交接 |
| `listTitle` | 列表上下文标题 |
| `listPublishedAt` | 时间窗口与 Checkpoint 判断 |
| `title` | Item 主标题 |
| `publishedAt` | Item 业务发布时间 |
| `content` | Item 正文或主要内容 |

绑定值使用 `list.field` 或 `detail.field`。CollectionVersion 的完整结构化结果保存在 `extractedData`，兼容展示字段只是绑定后的投影，不限制通用字段集合。

## 6. 身份与变化

- `identityFields` 定义稳定实体键输入；`list_detail` 通常使用 `detailUrl` 或站点业务 ID。
- `fingerprintFields` 定义 Revision 变化检测输入；运行时只比较这些字段，不把采集时间、Run ID 或其他易变元数据算作业务变化。
- 列表上下文字段和详情输出字段一起进入 `extractedData`；同名时详情输出覆盖列表值。编译器应优先生成不冲突的字段名。
- 所有详情输出字段自动进入 fingerprint，避免模型遗漏业务内容变化。

## 7. 分页

- `none`：只执行入口页。
- `next_link`：从受约束 selector 提取同源下一页链接，并受 `maxPages` 限制。
- `page`：只支持 query 参数页码，明确 parameter、start、step、maxPages 和空页停止策略。

跨主机分页固定禁止。路径模板、任意 URL 模板、游标脚本、无限滚动和模型自适应翻页不属于 v1；模型提出未支持策略时，平台保留已经样本验证的发现规则，不把不可执行建议写入 GatherSpec。

## 8. 两阶段编译与验证

1. Crawl4AI 获取入口样本并裁剪脚本、样式和注释等主动内容。
2. 默认模型编译发现计划；平台执行它并要求 `list_detail` 至少发现两个详情记录。
3. 平台抓取最多三个详情样本；默认模型编译完整 RulePlan。
4. 平台规范化有限别名，验证 Schema、selector 命中、必填字段、详情交接、allowedHosts、分页、身份、指纹和兼容绑定。
5. 合法计划转换为 GatherSpec，保存 provider、model、promptVersion、RulePlan Artifact 与样本证据，进入人工审核。

网页文本始终是不可信数据。模型不得输出 JavaScript、XPath、正则程序、凭据、请求 Header、安全边界、Sink、签名或可执行网络指令。

## 9. v1 支持边界

v1 面向公开或已授权、可由 HTTP 或受限浏览器访问的 HTML/JSON Source，覆盖单页与列表详情结构、CSS/JSONPath 字段、同源 next link 和 query page。登录交互、验证码、复杂表单、GraphQL 游标协商、无限滚动、附件解析和多级详情链需要后续方言或显式平台能力，不得通过模型生成代码绕过。
