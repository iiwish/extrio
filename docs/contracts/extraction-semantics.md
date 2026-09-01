# Extrio v0.2 提取与规范化语义

## 1. 元数据

| 字段 | 内容 |
| --- | --- |
| 文档版本 | `v1.1.1` |
| 状态 | `Ready_For_User_Review` |
| 适用规则 | `extrio.gather.v1` |
| 权威来源 | [`../SSOT.md`](../SSOT.md) 中的 `INV-001`、`INV-002`、`INV-003` |
| 最后更新 | `2026-08-30` |
| 审批责任 | 技术负责人 |

## 2. 目标

本合同定义 HTTP parser、Browser DOM、编译校验器和 Worker 对同一响应的字段提取、类型转换与规范化行为。第三方库默认值不得覆盖本文语义。

v0.2 只支持标量字段提取。数组和嵌套对象可以通过 `valueType=json` 接收 JSONPath 返回的单个 JSON value，但 CSS selector 不支持隐式聚合多个节点。

## 3. 输入文档

### 3.1 HTML

- HTTP transport 使用 WHATWG HTML Living Standard 的 tree-construction 行为构建 DOM。
- 编码按有效 HTTP `Content-Type` charset、BOM、HTML meta charset、UTF-8 的顺序确定；冲突时采用最前面的有效来源并记录诊断。
- 解码错误使用 U+FFFD，不采用平台默认 locale。
- `base URL` 是最终响应 URL；页面 `<base>` 只有在解析后仍属于 allowedHosts 时才用于相对 URL 解析。
- Browser transport 使用导航完成后的 DOM snapshot；snapshot 时点由 `browserPolicy.waitUntil` 和 `browserPolicy.postLoadDelayMs` 共同决定，engine/version、viewport、deviceScaleFactor、locale 和 timezoneId 由 RuleVersion 固定。
- HTTP 与 Browser transport 的 DOM 不保证相同，因此 transport 属于 RuleVersion 行为和 output lineage。
- Browser live render 不承诺仅凭初始响应 bytes 可重复；确定性提取与证据等价回放以持久化 canonical DOM snapshot 为输入，不重新执行 JavaScript。

### 3.2 JSON

- JSON 必须符合 RFC 8259，不允许重复 object key、NaN 或 Infinity。
- 输入解码固定为 UTF-8；错误编码或重复 key 产生 `EXTRACT_DOCUMENT_INVALID`。
- JSON number 在转换前保持十进制词法值；不得先转为平台浮点再生成 identity 或 fingerprint。

## 4. Selector 方言

### 4.1 CSS

- CSS selector 使用 Selectors Level 4 的静态结构子集。
- 支持类型、ID、class、attribute、组合器、`:first-child`、`:last-child`、`:nth-child()`、`:not()`、`:is()` 和 `:where()`。
- 禁止伪元素、动态状态、`:has()`、供应商扩展和需要布局/视觉状态的 selector。
- 字段 selector 必须以 `::text`、`::html` 或 `::attr(name)` 结束。
- `itemsSelector` 不带提取后缀，返回 DOM 顺序的节点集合。

### 4.2 JSONPath

- JSONPath 使用 RFC 9535 语义。
- v0.2 支持 name、index、wildcard、array slice 和 filter selector。
- 禁止实现自定义函数、脚本表达式、递归执行或网络访问。
- 结果顺序遵循 RFC 9535；实现不得按 object hash 顺序重排。

### 4.3 Selector 解析

- Selector 必须由结构化 parser 解析，禁止 `eval`、字符串替换执行或把 selector 转为源代码。
- Selector 最大长度 4096 bytes，嵌套深度最大 32。
- 编译时和运行时必须使用相同的 dialectVersion；RuleVersion 通过 runtimeCompatibility 固定该版本。

## 5. 节点数量语义

每个 FieldRule 必须声明 `multipleMatchPolicy`：

| 值 | 0 个匹配 | 1 个匹配 | 多个匹配 |
| --- | --- | --- | --- |
| `error` | 进入缺失值处理 | 使用唯一结果 | 产生 `EXTRACT_MULTIPLE_MATCHES` |
| `first` | 进入缺失值处理 | 使用唯一结果 | 按文档顺序使用第一个并记录计数 |

- `required=true` 时，0 个匹配按 onError 处理，且 onError 只能是 `reject_item` 或 `fail_run`。
- `required=false` 时，0 个匹配产生 null；运行时再按 onError 和 normalizedItemSchema 判断是否合法。
- `::text` 返回节点及后代的 text content，不插入实现特有分隔符。
- `::html` 返回按 8.7 节生成的 Extrio canonical HTML；属性顺序不参与业务比较。
- `::attr(name)` 在属性不存在时视为 0 个值，空属性值仍是合法空字符串。
- JSONPath 返回单个 JSON value；多个结果遵循 multipleMatchPolicy。

## 6. 缺失、null 与空值

- 缺失表示 selector 没有结果；JSON `null` 是一个明确结果，两者不得混同。
- 空字符串在执行 trim 后仍为空时，对 identity 字段等同无效缺失；其他字段保留空字符串，除非 normalizedItemSchema 禁止。
- 空数组和空 object 是合法 JSON value，不等同 null。
- `onError=null` 只适用于 `required=false`；输出 null 必须被 normalizedItemSchema 允许。
- 任何隐式默认值必须写入 CollectionVersion 和 RuleVersion，v0.2 FieldRule 不提供未声明默认值。

## 7. 字符串与 Unicode

- 字符串在类型转换后、transforms 前执行 Unicode NFC normalization。
- identity 和 fingerprint 使用 NFC 后的 UTF-8 字符串。
- `trim` 只移除 Unicode White_Space 属性定义的首尾字符。
- `collapse_whitespace` 把一个或多个 Unicode White_Space 转为单个 U+0020，并执行 trim。
- `lowercase` 与 `uppercase` 使用 Unicode Default Case Conversion，不使用租户或主机 locale。
- 大小写转换可能改变字符数量，转换结果再次执行 NFC。

## 8. 类型转换

### 8.1 string

只接受字符串或 HTML text/attribute 结果。JSON number、boolean 和 object 不自动转字符串。

### 8.2 integer

- 接受十进制字符串或 JSON integer。
- 语法为可选 `-` 加数字，不允许千位符、指数、小数、`+`、locale 数字或前后空白。
- 规范值是无前导零的十进制整数；`-0` 规范为 `0`。
- 范围限制为有符号 64-bit；超出产生类型错误。

### 8.3 number

- 接受 JSON number 或 ASCII 十进制字符串。
- 不允许千位符、货币符号、百分号、NaN、Infinity 或 locale 小数点。
- 使用任意精度十进制解析；identity/fingerprint 使用无无意义尾零的规范十进制字符串。
- 输出为 JSON number 时必须能被 RFC 8785/JCS 安全表达，否则产生类型错误。

### 8.4 boolean

只接受 JSON boolean，以及大小写不敏感的字符串 `true`、`false`、`1`、`0`。规范输出为 JSON boolean。

### 8.5 datetime

`datetimeFormat` 只允许：

- `RFC3339`
- `ISO8601_DATE`
- `UNIX_SECONDS`
- `UNIX_MILLISECONDS`

无 offset 的输入使用 `defaultTimezone`。`defaultTimezone` 必须是 IANA time zone ID；runtimeCompatibility 必须固定 `tzdbVersion`。DST 模糊时间默认拒绝，DST 不存在时间拒绝，不自动偏移。规范输出统一为 UTC RFC 3339，保留输入能够证明的最高精度。

### 8.6 url

- 采用 WHATWG URL parser，以最终响应 URL 或合法 `<base>` 为 base。
- 规范化 scheme/host 小写、IDN 使用 ASCII punycode、移除默认端口和 fragment。
- 保留 path 与 query 参数顺序；不移除业务参数，不自行排序 query。
- 禁止 userinfo；detail URL 必须在解析、DNS 和 redirect 每一步通过 Source 安全检查。

### 8.7 html

- 输入必须来自 `::html`。
- 规范值由 DOM fragment 递归生成：保留节点与子节点顺序；文本节点执行 NFC；元素和属性名使用 parser 规范名；属性按 `(namespace URI 或空字符串, local name)` 的 UTF-8 字节序排序；属性值统一双引号并按 HTML serializer 转义；comment、void element 与字符引用遵循 WHATWG fragment serialization。
- normalized payload 与 fingerprint 使用同一 canonical HTML UTF-8 值，不保留仅由原始属性顺序造成的差异。
- 存储与展示继续受安全合同的 sanitizer 约束；sanitized 展示内容不是 payloadFingerprint 输入。

### 8.8 json

- 输入必须是一个 JSON value。
- 规范化使用 RFC 8785 JCS；不允许外部引用、可执行表达式或非 JSON 类型。

## 9. Transform 顺序

1. Selector 求值。
2. 节点数量策略。
3. 原始值读取。
4. Unicode NFC。
5. transforms 按规则数组顺序执行。
6. valueType 转换；`absolute_url` 是 url 转换的预处理步骤。
7. normalizedItemSchema 校验。
8. identity、outputContractDigest 和 payloadFingerprint 计算。

同一个 transform 在一个字段中最多出现一次。类型不适用的 transform 在编译时拒绝，例如对 integer 使用 `strip_html`。

## 10. Output contract 与 fingerprint

- outputContractDigest 对 `{normalizedItemSchema, identityFields, fingerprintFields, eventSemantics}` 使用 JCS 和 SHA-256 计算。`eventSemantics` 精确为 `{emitUnchanged, eventTypes, tombstonePolicy}`；无 tombstonePolicy 时 eventTypes 为 `["upsert"]`，存在时为按 UTF-8 字节序排序的 `["tombstone","upsert"]`，缺少 tombstonePolicy 时使用 JSON `null`。Sink 绑定和交付策略不进入该摘要。
- identity 和 payload fingerprint 输入必须是包含字段名与规范类型值的 JCS object，不能只拼接值数组。
- fingerprintFields 缺失或类型错误时，不得产生 Revision。
- 字段描述、UI label、质量阈值和 Schedule 不属于 outputContractDigest。
- normalizedItemSchema 或事件含义变化必须产生新的 outputContractDigest。

## 11. 错误分类

| 错误码 | 含义 |
| --- | --- |
| `EXTRACT_DOCUMENT_INVALID` | HTML/JSON 无法按固定语义解析 |
| `EXTRACT_SELECTOR_INVALID` | Selector 不符合允许方言 |
| `EXTRACT_NO_MATCH` | 必填字段无匹配 |
| `EXTRACT_MULTIPLE_MATCHES` | multipleMatchPolicy=error 且结果超过一个 |
| `EXTRACT_TYPE_INVALID` | 值不能按 valueType 严格转换 |
| `EXTRACT_TIME_AMBIGUOUS` | DST 或时区输入存在歧义 |
| `EXTRACT_URL_FORBIDDEN` | URL 越过 origin 或网络边界 |
| `EXTRACT_SCHEMA_INVALID` | 规范化结果不满足 Item Schema |

错误必须包含字段名、stage、selector 摘要、error code 和 requestId；不得回显包含 secret 或敏感 query 的完整值。

## 12. 兼容与验收

- 共享机器向量见 [`canonicalization-fixtures.json`](./canonicalization-fixtures.json)；所有 inputVariants 必须产生相同 expected canonical UTF-8 bytes 与 SHA-256。
- dialect、HTML parser、Unicode、decimal、URL、datetime 或 transform 语义改变属于行为变化，必须提升 runtime 兼容版本；不兼容变化使用新的 GatherSpec 主版本。
- Python 编译/控制面校验器、执行 runtime 与 TypeScript 合同测试必须共享正例、反例和 golden output fixtures。
- fixtures 必须覆盖多节点、缺失/null/空值、Unicode 版本、DST、decimal、URL、HTML 属性重排、Browser DOM snapshot 和 JSONPath 顺序。
- 同一 fixture 在所有受支持 runtime 上必须产生相同规范化 JSON、entityKey、outputContractDigest、payloadFingerprint、revisionKey 和 eventId。
