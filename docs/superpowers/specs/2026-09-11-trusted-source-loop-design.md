# 可信来源闭环设计

> 日期：2026-09-11  
> 状态：已确认，待实施计划  
> 范围：阶段 0 POC 的 P0 整改

## 1. 目标与边界

解决真实海尔案例暴露的四个 P0 问题：官方来源无法摄取、PDF 被拒绝、第一个研究问题耗尽来源预算、报告无法表达来源可信等级。

本阶段只扩展现有 LangGraph POC 的“来源发现 → 内容摄取 → 证据门禁 → 报告”闭环。继续只使用公网信息、SQLite、本地 Artifact Store 和 CLI；不增加 Web 服务、多用户、Playwright、反爬绕过、异步任务队列或跨 run 缓存。

PDF 使用 MinerU API。密钥只从环境变量读取；原始 PDF、解析结果和脱敏任务元数据保存在当前 run 的本地 Artifact Store。任何 PDF、网页或模型输出都不会因本设计写入 Git。

## 2. 已确认的产品规则

1. 每个外部 Fact 必须有可定位 Evidence；没有 Evidence 的内容只能成为 Gap，不得进入 Fact。
2. 官方/一手来源优先。`OFFICIAL_PRIMARY` 是“官方来源覆盖”通过条件的唯一满足者。
3. `TRUSTED_SECONDARY` 可以支撑 Fact，但报告必须显示“二手来源，待官方验证”。它不能被表述为官方结论，也不能使官方来源覆盖通过。
4. `UNCLASSIFIED` 只作为候选或信息缺口，不得支撑最终 Fact。
5. 全局来源上限仍为 6。每个研究问题先获得 1 个去重来源的机会；余下来源按可信等级、相关性、搜索顺序稳定排序补齐。
6. HTML 403、PDF 解析失败、MinerU 超时或无效输出只能形成结构化 Failure，不得阻断其他来源或迫使报告虚构替代事实。

## 3. 方案选择

选择同步的“内容类型路由 + 来源选择器”方案：LangGraph 仍用有限 fan-out 摄取已选 Source；`discover_sources` 负责每题保底与全局补齐；`ingest_source` 根据响应内容类型路由至 HTML 或 PDF Adapter。

未选择异步 PDF 队列：它会引入轮询、回调、任务租约与恢复状态，超过当前单用户 POC 所需复杂度。未选择 Playwright：官网 403 的绕过并不等于合规可持续获取，且增加浏览器运行成本和反爬风险。

## 4. 领域模型与端口

### 4.1 来源等级

新增严格枚举 `SourceAuthority`：

| 值 | 含义 | 能否支撑 Fact | 是否计入官方覆盖 |
| --- | --- | --- | --- |
| `OFFICIAL_PRIMARY` | 官网、交易所/监管披露、公司正式财报或公告 | 是 | 是 |
| `TRUSTED_SECONDARY` | 可识别的主流财经、行业或政府媒体 | 是，但降级标记 | 否 |
| `UNCLASSIFIED` | 归属无法识别或不在白名单中的网页 | 否 | 否 |

`Source` 新增 `authority` 和 `content_kind`。`content_kind` 只能为 `HTML`、`PDF` 或 `UNKNOWN`；它来自 HTTP 响应的媒体类型与 URL 后缀的保守组合，不能仅依赖搜索摘要。

来源等级由纯函数 `classify_source(url)` 在本地决定，不由模型决定。第一版只维护明确、可测试的域名集合：案例配置传入的官方域名、交易所/监管域名和可信媒体域名。未命中即为 `UNCLASSIFIED`，不猜测域名归属。

### 4.2 PDF 端口

新增 `PdfParser` 异步端口：`parse(pdf_bytes, source_url) -> ParsedDocument`。`MinerUPdfParser` 是唯一生产实现，通过 MinerU API 上传/提交公开 PDF，轮询到完成或明确失败，并返回纯文本与脱敏任务标识。

适配器责任边界：认证、请求超时、响应 Schema、最多 3 次瞬态重试、任务轮询上限、失败分类。它不负责事实提取或来源评级。单文件大小、允许媒体类型、下载重定向和 URL 安全检查继续由现有 Fetcher/URL Policy 执行。

MinerU 请求仅发送来源 URL 指向的公开 PDF 内容。解析返回的文本须与原 PDF 的 Artifact Ref 和内容哈希关联；没有成功解析文本的 PDF 不得进入 DocumentBlock。

## 5. 数据流与状态

```text
ResearchQuestion[1..4]
  -> Tavily 每题搜索候选
  -> URL 规范化、去重、来源等级分类
  -> 每题保底一条 + 全局补齐至最多 6 条
  -> Source(authority, content_kind)
  -> 安全下载
       HTML -> HtmlExtractor -> DocumentBlock
       PDF  -> MinerU API -> DocumentBlock
  -> 既有 Evidence / Claim / Verification / Quality Gate
  -> ReportModel（来源等级、官方覆盖、Failure）
  -> Markdown / HTML
```

Graph State 继续仅保存 ID 与结果摘要。`source_ids` 保持稳定去重顺序；来源等级、内容类型、Artifact Ref、MinerU 任务元数据、原文与解析文本都保存到 Domain Store 或 Artifact Store，不写入 State。

`discover_sources` 不再在单题获得 6 个结果后停止后续搜索。它先对每题候选选择第一个尚未选中的 URL；若某题没有候选，记录来源发现 Failure 或 Gap；再统一对剩余候选排序并补满全局上限。

## 6. 摄取与失败策略

1. 安全 Fetcher 返回媒体类型、状态码、字节内容和最终 URL；仍拒绝非 HTTP(S)、私网地址、超限响应与不允许的重定向。
2. 成功 HTML 响应进入已有 `HtmlExtractor`；成功 PDF 响应进入 `PdfParser`。
3. HTTP 403 记录 `HTTP_403`，不重试为浏览器绕过；该来源不产生 DocumentBlock。
4. MinerU 的 401/403 是配置错误，4xx 请求错误是永久失败，429/5xx/网络超时最多重试 3 次；所有失败都包含来源 ID、操作和脱敏说明。
5. PDF 解析完成但没有可用正文时记录 `PDF_PARSE_EMPTY`；不得用模型摘要替代原文。
6. 任意来源失败后，其他来源照常进入 fan-out；报告必须列出失败来源和信息缺口。

## 7. 报告与质量门禁

`ReportSource` 与每个 `ReportFact` 均带 `authority`。Markdown/HTML 中：

- `OFFICIAL_PRIMARY` 显示“官方/一手来源”；
- `TRUSTED_SECONDARY` 显示“二手来源，待官方验证”；
- `UNCLASSIFIED` 不得作为 Fact 的 source ID。

`ReportStats` 新增官方来源成功数、二手来源成功数、按问题的来源覆盖和 `official_coverage`。当报告存在 Fact 但官方成功数为 0 时，`report_outcome` 必须为 `PARTIAL`，并生成 `OFFICIAL_SOURCE_MISSING` Gap。现有 Evidence 定位、数字保护、语义核验和“只允许 APPROVED FACT 入报告”的规则不变。

## 8. 验收标准

离线测试必须证明：

1. 4 个问题都有搜索调用机会，且每题先保留一个唯一来源；总数不超过 6。
2. 相同 URL 不会因不同问题产生重复 Source，`discovered_by_question_ids` 会合并。
3. 官方来源在补齐排序中优先于二手来源；未识别来源不能支撑最终 Fact。
4. Fake MinerU API 的成功 PDF 产生原始制品、解析文本、DocumentBlock 和可定位 Evidence。
5. PDF 的解析超时、空正文、配置错误及 HTTP 403 被记录，且其他来源仍可结报。
6. 可信媒体 Fact 在 Markdown 和 HTML 都带二手警示；官方 Fact 带官方标记。
7. 没有成功官方来源时，即使二手 Fact 通过验证，`report_outcome` 为 `PARTIAL` 且出现官方来源缺口。
8. 现有离线测试、Ruff、mypy、锁文件校验、密钥泄漏扫描继续通过。

真实验收使用海尔智家和第二个行业案例。每个案例至少有一条成功摄取的 `OFFICIAL_PRIMARY` 来源、一个成功解析的公开 PDF，并由人工全量审阅所有 Fact 后才可解除 POC 的 MVP 阻断。

## 9. 非目标与风险

- 不承诺所有官网都可抓取；403 仍是可审计失败，不绕过访问控制。
- 不在本阶段自动判断所有媒体可信度；域名白名单之外统一降为 `UNCLASSIFIED`。
- 不实现本地 MinerU、GPU 部署、企业私有文件或非公开 PDF。
- MinerU API 的具体认证/异步任务字段应以用户账户对应的官方 API 文档为准；实现前在 Provider Adapter 层做一次最小连通性 POC，不把未验证字段写死进核心图。
