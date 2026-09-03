# Extrio 规则编写指南（GatherSpec 权威作者手册）

> 本文档是 Extrio 采集规则（GatherSpec，`extrio.gather.v1`）的**权威编写指南**：
> 解释规则为什么这样设计、每个字段块如何填写、transforms 如何执行、规则如何演进、
> 以及评审人在发布前应当核对什么。语法以
> [`gather-spec.schema.json`](./contracts/gather-spec.schema.json) 为准，
> 执行语义以 [`extraction-semantics.md`](./contracts/extraction-semantics.md) 为准，
> 两者与本指南冲突时，Schema 与语义合同优先。

## 目录

1. [设计哲学：规则为什么被"冻结"](#1-设计哲学规则为什么被冻结)
2. [一张图看懂 GatherSpec](#2-一张图看懂-gatherspec)
3. [逐块字段字典](#3-逐块字段字典)
4. [Transforms 完整参考](#4-transforms-完整参考)
5. [演进政策](#5-演进政策)
6. [发布前审核清单](#6-发布前审核清单)

---

## 1. 设计哲学：规则为什么被"冻结"

Extrio 的采集规则不是一段爬虫脚本，而是一份**可审计的数据合同**。它必须同时满足四个性质：

- **确定性（Deterministic）**：同一规则 + 同一响应字节 ⇒ 永远产出同一规范化结果。没有 LLM、没有随机性、没有"再试一次也许能解析出来"。
- **冻结（Frozen/Immutable）**：规则一经发布即不可修改（`INV-002`）。行为变化只能发布新 RuleVersion，而不是原地改写。
- **可证明（Attested）**：每个已发布规则都附带 Ed25519 RuleAttestation，记录"谁、依据什么证据、经谁审核"批准了这份规则。
- **钉扎（Pinned）**：规则显式声明它依赖的运行时语义版本（正则方言、HTML parser、Unicode、tzdb），任何一项不匹配就拒绝执行，而不是"大概能跑"。

### 1.1 与同类系统的对比：GatherSpec 独有什么

| 系统 | 规则形态 | 治理方式 | 与 GatherSpec 的关键差异 |
| --- | --- | --- | --- |
| Crawl4AI `JsonCssExtractionStrategy` | 库内 CSS schema（代码里的字典） | 无版本治理，随代码改动 | GatherSpec 是版本化 JSON 合同：独立 digest、不可变发布、attestation 谱系；schema 改动走明确的演进政策 |
| Apify Actor `INPUT_SCHEMA` | 面向 Actor **输入参数**的表单描述 | 由 Actor 作者自定义 | 它描述"用户给 Actor 什么"，不描述"Actor 如何把页面变成数据合同"；GatherSpec 的 `contract` 块（identity/fingerprint/quality）才是数据合同 |
| Firecrawl `/extract` | LLM 现场抽取（每次调用重新理解页面） | 无冻结、无证明 | Extrio 的 LLM 只在**编译期**出现（`compiler.agent` 记录血统），运行期（`INV-001`）绝不调用模型；同一规则可以无限次重放同一结果 |
| Skyvern workflow | 面向 RPA 动作序列（点击、填表） | 面向操作而非数据 | GatherSpec 只表达受控请求、selector 提取、规范化与质量门，不表达通用程序；因此它能被静态审计、被 Schema 拒绝、被 digest 钉死 |

GatherSpec 独有的五件套：

1. **`runtimeCompatibility` 钉扎** —— 正则方言（RE2）、parser、tzdb、Unicode 版本全部写进规则。今天发布的规则，三年后在任意 Worker 上必须产出逐字节相同的结果；不匹配的 runtime 必须在第一个请求发出前失败。
2. **`compiler.agent` 血统** —— 规则若由模型参与编译，provider/model/promptVersion 永久记录在规则内。审核人能回答"这条正则是哪个模型、哪个 prompt 版本提出的"。
3. **安全不变量内嵌** —— `allowedHosts`、transport、预算、下载禁用不是 Worker 配置，而是规则本体的一部分；导入规则必须重新过全部安全校验。
4. **资源预算（`budget`）** —— 页数、条数、字节数、时长四重上限写死在规则里， runaway collection 在机制上不可能，而不是靠监控告警。
5. **identity-fingerprint 数据契约** —— `identityFields` 决定"这是哪个实体"，`fingerprintFields` 决定"实体变没变"。上下游系统消费的不是"这次爬到了什么"，而是带稳定 entityKey 和 Revision 的状态流。

一句话总结：**别的工具回答"怎么爬"，GatherSpec 同时回答"爬到的东西凭什么可信、变了没有、出错了谁负责"。**

### 1.2 LLM 在哪里：编译期进、运行期出

Extrio 不排斥 LLM——它把 LLM 关进编译期的笼子：

- LLM 读取裁剪后的 DOM 证据，产出受约束的 [`RulePlan`](./contracts/rule-plan.md)（只能表达 selector、类型、transforms、分页、绑定）。
- 平台校验 RulePlan → 编译成完整 GatherSpec → 人工审核 → Ed25519 attestation → 发布。
- 运行期 Worker 只读 GatherSpec（`INV-001`），不读模型配置、不读 prompt、不允许"现场补救"。

因此规则作者可以放心：**你审核的那份 JSON 就是生产环境执行的每一步，一个字符都不会变。**

---

## 2. 一张图看懂 GatherSpec

```jsonc
{
  "schemaVersion": "extrio.gather.v1",   // 合同主版本，决定语法与语义
  "ruleVersionId": "rv_...",             // 不可变规则版本 ID
  "tenantId": "tenant_...",              // 租户边界（Worker 与 job envelope 交叉校验）
  "collectionVersionRef": { ... },       // 冻结的数据合同版本（CollectionVersion）
  "sourceRevisionRef": { ... },          // Source 边界快照 + configDigest
  "compiler": { ... },                   // 编译器与 Agent 血统（可选 agent）
  "runtimeCompatibility": { ... },       // 执行环境钉扎
  "sourceContext": { ... },              // ① 请求哪里、怎么请求、边界在哪
  "collect": { ... },                    // ② 提取什么：list/detail/分页/重试/预算
  "contract": { ... },                   // ③ 产出什么：身份、指纹、Schema、质量门
  "output": { ... },                     // ④ 交付什么：raw 保留 + Sink 绑定
  "integrity": { ... }                   // ⑤ 自证：canonical digest
}
```

一个最小但完整的可运行示例见
[`contracts/gather-spec.example.json`](./contracts/gather-spec.example.json)——
它同时演示了 `regex_extract` transform 与 `label` 字段，可直接复制后修改。

---

## 3. 逐块字段字典

以下每块给出：**设计意图 → 最小示例 → 作者须知**。
所有对象均为 `additionalProperties: false`：**写错字段名会被 Schema 直接拒绝**（这是 AC-012.4 的确定性设计，见第 5 节）。

### 3.1 `sourceContext` —— 请求边界

**设计意图**：把"允许请求什么"从 Worker 配置提升为规则本体。规则发布的那一刻，网络边界就被冻结。

```jsonc
"sourceContext": {
  "entrypoints": ["https://www.example.gov.cn/tender/list"],
  "allowedHosts": ["www.example.gov.cn"],
  "transport": "http",
  "accessProfileRef": { "accessProfileId": "access_...", "accessProfileVersionId": "access_version_..." },
  "rateLimit": { "rps": 2, "burst": 4, "maxConcurrency": 2 },
  "requestPolicy": {
    "userAgent": "Extrio/Collector 0.2",
    "timeoutMs": 30000,
    "maxResponseBytes": 20971520,
    "maxRedirects": 3
  }
}
```

作者须知：

- `entrypoints`：绝对 HTTP(S) URL，1–32 个，不允许 userinfo 和 fragment。有 `accessProfileRef` 时必须全部 HTTPS。
- `allowedHosts`：**精确小写 hostname，禁止 `*` 通配**。entrypoint 主机、detail URL、每一跳 redirect 都必须落在集合内。坚持最小化：能一个 host 就不要写两个。
- `transport`：`http`（确定性客户端，不执行 JS）或 `browser`（必须同时声明 `browserPolicy`：固定 engine/version/viewport/locale/timezoneId/waitUntil/postLoadDelayMs；下载永久禁用）。
- `rateLimit` 是规则允许的**上限**；平台/租户/Source 的动态更严格限制仍然生效。
- 认证 Header、Cookie、签名 material 一律不进规则——通过 `accessProfileRef` 引用，运行前由 Worker 注入（`INV-005`）。

### 3.2 `collect.list` / `collect.detail` —— 提取计划

**设计意图**：字段提取只有两种受控原语——CSS selector（HTML）与 JSONPath（JSON）——加上顺序执行的 transforms。没有脚本，没有回调。

```jsonc
"collect": {
  "list": {
    "request": { "entrypointIndex": 0, "method": "GET", "headers": { "Accept": "text/html" }, "query": {} },
    "responseType": "html",
    "itemsSelector": "css:article.tender-item",
    "fields": {
      "detailUrl": {
        "label": "详情链接",                    // 可选：1-64 字符任意 Unicode，给审核 UI 和 LLM prompt 用
        "selector": "css:a.detail::attr(href)",
        "valueType": "url",
        "required": true,
        "onError": "reject_item",
        "multipleMatchPolicy": "error",
        "transforms": ["trim", "absolute_url"]
      }
    },
    "pagination": { "type": "page", "parameter": "page", "location": "query", "start": 1, "step": 1, "maxPages": 100, "stopWhenNoItems": true }
  },
  "detail": {
    "request": { "urlTemplate": "{{detailUrl}}", "method": "GET", "headers": { "Accept": "text/html" } },
    "responseType": "html",
    "fields": {
      "title": { "selector": "css:h1.title::text", "valueType": "string", "required": true, "onError": "reject_item", "multipleMatchPolicy": "error", "transforms": ["trim", "collapse_whitespace"] },
      "budgetAmount": {
        "label": "预算金额（万元）",
        "selector": "css:.notice-budget .amount::text",
        "valueType": "number",
        "required": false,
        "onError": "null",
        "multipleMatchPolicy": "first",
        "transforms": ["trim", { "type": "regex_extract", "pattern": "[0-9]+(?:\\.[0-9]+)?", "group": 0 }]
      }
    }
  },
  "requestRetry": { "maxAttempts": 3, "initialDelayMs": 500, "maxDelayMs": 5000 },
  "budget": { "maxPages": 100, "maxItems": 10000, "maxDurationSeconds": 3600, "maxTotalBytes": 1073741824, "onExceeded": "partial" }
}
```

作者须知：

- `detail` 是可选阶段：省略 = 单页采集；存在时 `urlTemplate` 只允许 `{{page}}` / `{{<字段名>}}` 精确变量替换，缺失变量是错误，不允许替换为空串。
- 字段 selector 相对当前 list item 节点或 detail 文档求值，必须以 `::text`、`::html` 或 `::attr(name)` 结尾（`itemsSelector` 不带后缀）。
- `valueType` ∈ `string | integer | number | boolean | datetime | url | html | json`；`datetime` 必须同时给 `datetimeFormat` + `defaultTimezone`，其他类型给这两个键会被拒绝。
- `required=true` 时 `onError` 只能是 `fail_run`（整 Run 失败）或 `reject_item`（丢弃该条）；`required=false` 才允许 `null`。
- `multipleMatchPolicy=error`（多匹配视为缺失，最严格）或 `first`（按文档序取第一个并记录计数）。不要依赖库默认行为，必须显式声明。
- `label`（可选，1–64 字符，任意 Unicode）：纯展示用途——审核界面的列名、LLM prompt 中的字段语义。**不参与提取、指纹或任何 digest**。省略即完全省略键，编译器不会替你补一个假名字。
- 每字段最多 8 个 transform 且不可重复，按数组顺序执行，见第 4 节。

### 3.3 `collect.list.pagination` —— 三种形态

| 形态 | 适用场景 | 最小示例 | 设计意图 |
| --- | --- | --- | --- |
| `none` | 单页/详情列表一次抓完 | `{"type": "none"}` | 显式声明"只抓入口页"，不做隐式猜测 |
| `page` | 服务端页码（query 参数） | `{"type": "page", "parameter": "page", "location": "query", "start": 1, "step": 1, "maxPages": 100, "stopWhenNoItems": true}` | 页码由 runtime 注入 query；空页即停；`maxPages` 是硬上限 |
| `next_link` | "下一页"链接翻页 | `{"type": "next_link", "selector": "css:a[rel=next]", "maxPages": 50, "allowCrossHost": false}` | selector 从当前 list 文档提取下一页 URL；`allowCrossHost=true` 也只允许在 `allowedHosts` 集合内跨主机 |

**不支持**：路径模板、无限滚动、游标脚本、GraphQL 游标协商。模型提出未支持策略时，平台保留已样本验证的发现规则，而不是把不可执行建议写进规则。

### 3.4 `contract` —— 身份、指纹与质量门

**设计意图**：这一块把"数据是什么"变成机器可校验的合同。它是 GatherSpec 与一切"采集脚本"最本质的区别。

```jsonc
"contract": {
  "identityFields": ["externalId"],          // 1-16 个：决定 entityKey（"这是哪条记录"）
  "fingerprintFields": ["title", "contentHtml", "publishAt", "updatedAt", "budgetAmount"],  // 1-64 个：决定 Revision（"内容变了吗"）
  "outputContractDigest": "sha256:...",      // 规范化 Schema + 身份/指纹 + 事件语义的 canonical digest
  "normalizedItemSchema": {                  // Draft 2020-12 自包含 Schema，additionalProperties 必须为 false
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "externalId": { "type": "string", "minLength": 1 },
      "budgetAmount": { "type": ["number", "null"] }   // 可选字段用 onError=null 时必须显式允许 null
    },
    "required": ["externalId"],
    "additionalProperties": false
  },
  "quality": {
    "requiredFieldCompleteness": 0.95,       // 产品默认门槛；身份字段恒为 1.0
    "maxItemErrorRatio": 0.05,
    "emptyResultPolicy": "suspect"           // allow | suspect | fail
  },
  "fieldBindings": { "detailUrl": "list.detailUrl", "title": "detail.title" }   // 可选：平台兼容角色投影
}
```

作者须知：

- `identityFields` 只能引用 `normalizedItemSchema.properties` 与字段规则中真实存在的字段；身份字段经 transforms 后必须非空。**身份字段次序属于合同**——改变即需新 CollectionVersion。
- 指纹字段必须能反映业务内容变化，不要把 `observedAt`、Run ID 之类每次运行都变的元数据放进去；Revision 比较只看这些字段。
- `normalizedItemSchema` 必须自包含：所有 `$ref` 以 `#` 开头，禁止外部引用；单个 regex ≤ 512 bytes 且仅限 RE2 子集；Schema ≤ 256 KiB、深度 ≤ 32。
- 需要 tombstone（下架/撤销信号）时：sink 用 `eventMode: upsert_tombstone`，并在 `contract.tombstonePolicy` 指定字段与精确值集合；该字段必须包含在指纹字段里。

### 3.5 `output` —— 交付

**设计意图**：规则声明"结果去哪"，但不携带任何端点凭据。

```jsonc
"output": {
  "rawRetentionDays": 30,                    // 0-90；0 = 不保存成功 raw（失败证据仍按租户策略处理）
  "emitUnchanged": false,                    // v1 固定 false：内容未变不产生新 ItemEvent
  "sinks": [
    {
      "sinkId": "sink_tender_kafka",
      "sinkVersionId": "sink_version_kafka_001",
      "type": "kafka",                       // kafka | webhook
      "eventMode": "upsert",                 // upsert | upsert_tombstone（后者必须配 tombstonePolicy）
      "deliveryPolicy": { "maxAttempts": 8, "initialDelaySeconds": 5, "maxDelaySeconds": 21600, "timeoutSeconds": 30, "totalWindowSeconds": 172800 }
    }
  ]
}
```

作者须知：同一规则内 `sinkVersionId` 唯一；Endpoint/Topic 凭据/签名 secret 属于 SinkVersion，不属于规则。交付语义是 at-least-once（`INV-006`），消费端必须按幂等键去重。

### 3.6 `integrity` —— 自证

```jsonc
"integrity": { "digestAlgorithm": "sha256", "ruleDigest": "sha256:..." }
```

`ruleDigest` 的计算：深拷贝完整 GatherSpec → 删除 `/integrity/ruleDigest` → RFC 8785 JCS 规范化 → SHA-256。规则本体**不内嵌签名**（避免密钥轮换改动不可变载体）；发布证明由独立的 RuleAttestation 承载（[`rule-attestation.md`](./contracts/rule-attestation.md)）。Worker 在任何请求发出前重算 digest 并验证 attestation——篡改一个字符都会失败。

### 3.7 `compiler` 与 `runtimeCompatibility` —— 血统与钉扎

```jsonc
"compiler": {
  "name": "extrio-compiler", "version": "0.2.0", "compiledAt": "2026-08-30T08:00:00Z",
  "inputDigest": "sha256:...",              // 全部编译输入的 canonical digest
  "overrideRefs": [ { "overrideId": "override_...", "digest": "sha256:..." } ],
  "agent": { "provider": "...", "model": "...", "promptVersion": "2.0", "toolchainVersion": "2.0" }   // 不用 Agent 时必须省略，不得虚构
},
"runtimeCompatibility": {
  "runtimeName": "extrio-python",
  "minVersion": "0.2.0", "maxVersionExclusive": "0.3.0",
  "dialectVersion": "1.0", "parserVersion": "1.0", "tzdbVersion": "2026a", "unicodeVersion": "17.0"
}
```

作者须知：Worker 的 runtime 必须落在 `[minVersion, maxVersionExclusive)` 且**精确匹配**四个语义版本，否则在第一个 Source 请求前失败（`RULE_RUNTIME_UNSUPPORTED`）。这是"三年后重放"承诺的执行机制。

---

## 4. Transforms 完整参考

Transforms 按 `transforms` 数组顺序执行，位于 selector 求值之后、`valueType` 类型转换之前。每个 transform 每字段最多出现一次（`uniqueItems`）。类型不适用的 transform 在编译期拒绝（如对 `integer` 字段用 `strip_html`）。

### 4.1 字符串变换

| Transform | 语义 | 示例输入 → 输出 |
| --- | --- | --- |
| `trim` | 移除首尾 Unicode White_Space | `"  公告 A\n"` → `"公告 A"` |
| `collapse_whitespace` | 连续空白折叠为单个 U+0020 并 trim | `"公告\u00A0 A  B"` → `"公告 A B"` |
| `lowercase` | Unicode Default Case Conversion 小写（再次 NFC） | `"Notice-A"` → `"notice-a"` |
| `uppercase` | Unicode Default Case Conversion 大写（再次 NFC） | `"notice-a"` → `"NOTICE-A"` |
| `strip_html` | 剥离 HTML 标签取纯文本 | `"<b>公告</b>A"` → `"公告 A"` |

### 4.2 URL 变换

| Transform | 语义 | 示例输入 → 输出 |
| --- | --- | --- |
| `absolute_url` | 以最终响应 URL（或通过安全检查的 `<base>`）为 base 解析为绝对 URL | `/detail/42` → `https://host/detail/42` |

`valueType=url` 的字段在 `absolute_url` 之后仍须通过 allowedHosts 检查才可作为 detail URL。

### 4.3 `regex_extract` —— 从非结构文本中钉出结构值（v1.5 新增）

当 selector 只能取到"一段话"，而业务需要的是其中**一个数值/编号**时，用 `regex_extract` 把目标钉出来。它有两种书写形态：

```jsonc
// 形态一（既有）：纯字符串，所有旧规则继续有效
"transforms": ["trim"]

// 形态二（新增，仅 regex_extract 支持对象形态）
"transforms": [
  "trim",
  { "type": "regex_extract", "pattern": "[0-9]+(?:\\.[0-9]+)?", "group": 0 }
]
```

对象形态字段：

| 键 | 必填 | 约束 | 语义 |
| --- | --- | --- | --- |
| `type` | 是 | 恒为 `"regex_extract"` | 对象形态**只允许** regex_extract；`trim` 等永远写纯字符串 |
| `pattern` | 是 | 1–512 字节，**RE2 语法** | 见下方 RE2 边界 |
| `group` | 否 | 整数 0–8，默认 0 | 输出第 N 个捕获组；**0 = 整个匹配** |

**执行语义**（与 [`extraction-semantics.md`](./contracts/extraction-semantics.md) 第 9 节一致）：

1. 对 selector 求值得到的字符串执行 `RE2.search(pattern)`。
2. 命中 → 取第 `group` 个捕获组（0 = 整个匹配）作为新的字段值，随后继续执行数组中剩余 transforms，最后进入 valueType 转换。
3. 未命中 → **没有输出值**：字段按缺失处理。`required=true` 时走既有 `onError` 语义（`reject_item` 丢弃该条 / `fail_run` 终结 Run，由 Item 质量门呈现拒绝证据）；`required=false` 且 `onError=null` 时输出 `null`（此时 `normalizedItemSchema` 必须允许该字段为 null，如 `"type": ["number", "null"]`）。

**RE2 语法边界**（由 runtime 的 RE2 引擎强制执行；离线校验器 `re2_pattern_error` 会在审核前提前拒绝）：

- ✅ 支持：字面量、字符类 `[...]`、量词 `* + ? {n,m}`、非贪婪 `*?`、分组 `(...)`、非捕获组 `(?:...)`、锚点 `^ $`、Unicode 字面字符（如直接写中文）。
- ❌ 不支持：**前瞻** `(?=...)` `(?!...)`、**后顾** `(?<=...)` `(?<!...)`、**反向引用** `\1`–`\9`、`(?P=name)`。RE2 是无回溯引擎——这正是它线性时间、抗 ReDoS 的原因，与 GatherSpec 的确定性承诺同构。

**完整示例：从"预算金额：355.6万元"提取数字**

页面节点内容为 `预算金额：355.6万元`，目标是数值 `355.6`：

```jsonc
"budgetAmount": {
  "label": "预算金额（万元）",
  "selector": "css:.notice-budget .amount::text",   // 取到 "预算金额：355.6万元"
  "valueType": "number",
  "required": false,
  "onError": "null",
  "multipleMatchPolicy": "first",
  "transforms": [
    "trim",
    { "type": "regex_extract", "pattern": "预算金额：([0-9]+(?:\\.[0-9]+)?)万元", "group": 1 }
  ]
}
```

执行过程：`"预算金额：355.6万元"` → regex 命中，group 1 → `"355.6"` → `valueType: number` → `355.6`。
若节点写的是"预算金额未披露"，regex 未命中 → 可选字段输出 `null`；若该字段 `required=true`，则该条 item 被 `reject_item` 拒绝并携带拒绝证据。

**用法约束**：

- 每个字段最多一个 `regex_extract`；它解决"从一段文本里钉出一个值"，**不是**通用文本处理管道——能用 selector（`::text`/`::attr`）直接取到的值不要用正则。
- `pattern` 是规则的一部分，随 digest 冻结；修改 pattern = 新规则版本。
- JSONPath 字段同样可用（对序列化后的标量值执行）。

---

## 5. 演进政策

GatherSpec 的演进规则成文如下，对所有贡献者与集成方生效：

| 变更类型 | 兼容性 | 处理方式 |
| --- | --- | --- |
| **新增可选字段**（如 v1.5 的 `fieldRule.label`） | ✅ 兼容 minor | 直接加入当前 `extrio.gather.v1`；旧 Worker 继续正常执行 |
| **扩大值域**（如 v1.5 的 transforms 接受 `regex_extract` 对象形态） | ✅ 兼容 minor | 保持旧值合法（纯字符串 transforms 永远有效），新增值仅被声明支持的 runtime 消费 |
| 新增 enum 值（`valueType`、`onError` 等） | ⚠️ 受控 | 只有在 runtime 明确声明支持后才能发布；不支持的 Worker **拒绝**而非忽略 |
| 删除字段、改字段名、改变既有语义、改变规范化/digest/身份/指纹规则 | ❌ 不兼容 | 必须发布新主版本 `extrio.gather.v2`，新旧并存迁移 |
| `schemaVersion` | — | 兼容 minor 演进**不**升版本号；仍为 `extrio.gather.v1` |

**为什么旧 Worker 拒绝未知字段是特性而非缺陷（AC-012.4）**：
所有规则对象都是 `additionalProperties: false`。一个携带未知字段的规则要么来自更新的编译器，要么来自被篡改的载荷——旧 Worker 没有任何办法区分这两种情况，因此唯一确定性的行为就是**明确拒绝**（`RULE_SCHEMA_INVALID`），把决策交还给操作者，而不是带着静默忽略的字段继续跑。能力协商靠显式版本（`runtimeCompatibility` + `schemaVersion`），不靠静默降级。审核规则导入时，永远不要"放宽 Schema 让它先跑起来"。

---

## 6. 发布前审核清单

评审人点击"发布"前，逐项核对（前四项由平台强制，但审核人应能独立判断）：

**完备性**

- [ ] `identityFields` 指向的字段在所有样本中均非空、值稳定（同一实体两次采集 identity 不变）。
- [ ] `fingerprintFields` 至少包含一个真实反映业务内容变化的字段；不含采集时间等易变元数据。
- [ ] 每个 `required=true` 字段在全部采样详情页中都存在；样本缺失的字段应降级为 `required=false` + `onError=null` 并在 `normalizedItemSchema` 中允许 null。
- [ ] `datetime` 字段声明了 `datetimeFormat` 与 `defaultTimezone`；`onError=null` 的可选字段在 `normalizedItemSchema` 中显式允许 `null`。

**身份与合同**

- [ ] `normalizedItemSchema.properties` 与 `collect` 字段一一对应，`additionalProperties=false`；Schema 自包含、无外部 `$ref`、regex 均 RE2。
- [ ] `identityFields`/`fingerprintFields` 与字段 key 完全一致；身份字段次序与 CollectionVersion 合同一致。

**预算与安全**

- [ ] `budget.maxPages` ≥ 分页自身 `maxPages`；`maxItems`/`maxDurationSeconds`/`maxTotalBytes` 与业务规模匹配（宁小勿大）。
- [ ] `allowedHosts` 最小化：只列详情请求真正会访问的主机；`allowCrossHost` 是否必须开启？
- [ ] 无敏感 Header；凭据只经 `accessProfileRef` 引用；`userAgent` 如实标识。

**可解释性**

- [ ] 每个业务字段有可读 `label`（1–64 字符），审核界面列名与字段语义一致。
- [ ] `regex_extract` 的 pattern 逐字符复核：RE2 边界内、group 索引正确、对"未披露/占位文案"等非命中样本的表现符合预期（应拒绝或 null，而不是错值）。
- [ ] `compiler.agent` 存在时，provider/model/promptVersion 与探索记录一致。

**完整性**

- [ ] 重算 `ruleDigest` 与 `integrity.ruleDigest` 一致；RuleAttestation 签名可被当前信任密钥验证。

通过全部检查后，规则进入不可变发布：此后任何修改（哪怕一个字符）都是新的 RuleVersion + 新的审核 + 新的 attestation。

---

## 相关文档

- Schema：[`contracts/gather-spec.schema.json`](./contracts/gather-spec.schema.json) · 完整示例：[`contracts/gather-spec.example.json`](./contracts/gather-spec.example.json)
- 执行语义：[`contracts/extraction-semantics.md`](./contracts/extraction-semantics.md)
- LLM 编译中间表示：[`contracts/rule-plan.md`](./contracts/rule-plan.md) · [`contracts/rule-plan.schema.json`](./contracts/rule-plan.schema.json)
- 发布证明：[`contracts/rule-attestation.md`](./contracts/rule-attestation.md)
- 产品定位与不变量：[`SSOT.md`](./SSOT.md) · 设计决策：[`architecture/ADR-003-rule-integrity.md`](./architecture/ADR-003-rule-integrity.md)
