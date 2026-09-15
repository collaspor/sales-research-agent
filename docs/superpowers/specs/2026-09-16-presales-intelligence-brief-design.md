# 售前 Intelligence Brief 报告层设计

## 1. 目标与边界

将现有“研究结果导出器”改造成“前 20% 支持售前会前判断、后 80% 支持逐项追溯”的报告。第一主场景仍是陌生客户首次交流前的公网调研。

本次只改报告层：保留 Tavily 搜索、网页/PDF 摄取、MinerU 解析、Evidence 提取、Claim 质量门禁、SQLite Repository 和 LangGraph 主流程。允许发布节点在原有 Fact、Evidence、Gap、Source、Brief 上增加一次受约束的 DeepSeek 结构化报告编排调用。

## 2. 不可突破的可信度规则

1. Composer 不得搜索、不得读取原始网页、不得创建 Source、Evidence 或 Claim。
2. 一句话判断、关键发现和机会假设必须引用已有 APPROVED Fact 的 `claim_id`；验证器拒绝未知 ID。
3. 机会假设必须含“待确认事项”，并在正文明确标为假设，不能表述为客户需求。
4. Discovery Question 必须关联至少一个 Fact 或 Gap；没有血缘的问句被拒绝。
5. 来源等级、发布时间、时效状态和置信度由代码计算，模型不能声明它们。
6. Composer 超时、Schema 错误、血缘校验失败或返回空结果时，报告退回确定性简版，不能影响既有报告发布。
7. 只有实际支撑正文 Fact 的 Source 才能出现在正式来源清单；无关搜索结果只留在审计日志。

## 3. 输出模型

在现有 `ReportModel` 外新增不可变的报告视图数据：

- `BriefHeader`：客户名称、场景、研究目标、生成日期；
- `KeyFinding`：标题、事实摘要、售前意义、`claim_ids`、`evidence_ids`；
- `OpportunityHypothesis`：公开信号、可能关联能力、待确认事项、`upstream_claim_ids`；
- `DiscoveryQuestion`：分类、面客问法、提问原因、`upstream_claim_ids`、`gap_codes`；
- `JudgmentBoundary`：已确认公开事实、合理假设、尚未确认事项；
- `ReadableGap`：面向人的缺口说明、风险提示、建议确认问题、内部 Gap code；
- `FactTrust`：来源等级、时效状态、置信度、发布日期和来源数量。

`ReportModel` 保留原来的 `facts`、`evidence_index`、`gaps`、`failures` 和 `stats`，以保障已有制品及审计能力兼容。

## 4. 编排输入与输出

发布节点把以下最小且已验证的内容交给 Composer：

- `Brief` 的客户名称、场景、已知背景和研究目标；
- 已批准 Fact：ID、正文、Evidence ID、Source ID；
- Evidence：ID、原文、Source ID；
- Source：标题、URL、来源等级、发布日期；
- 研究问题与结构化 Gap。

Composer 输出 JSON，只能返回已有 ID：

```text
executive_judgment { text, claim_ids }
key_findings[] { title, fact_summary, presales_significance, claim_ids }
opportunity_hypotheses[] { public_signal, related_capability, validation_needed, claim_ids }
discovery_questions[] { category, question, rationale, claim_ids, gap_codes }
readable_gaps[] { title, description, risk_note, suggested_question, gap_codes }
```

最多输出 5 条关键发现、5 条机会假设、5 条 Discovery Questions。模型输出先经 Pydantic Schema 校验，再由纯函数验证所有 ID、数量、血缘和必填字段。

## 5. 代码计算的标签

来源等级沿用现有映射：`OFFICIAL_PRIMARY -> L1`、`TRUSTED_SECONDARY -> L2`、其他为 `LU`。

时效状态：

- `Current`：所有关联来源均有发布日期且距生成日不超过 365 天；
- `Historical`：存在已知发布日期且至少一条超过 365 天；
- `Date Unknown`：没有发布日期；
- `Forward-looking`：Fact 或 Evidence 含计划、预计、即将等前瞻词，优先覆盖其他时效标签。

置信度：

- `High`：至少一条近期 L1 来源，且不是前瞻性表述；
- `Medium`：至少一条 L1 历史来源，或至少两条独立 L2 来源；
- `Low`：其余情况。

标签仅描述当前证据支撑强度；正文不得把它表述为真实性保证。

## 6. 报告目录

正文：

1. Executive Brief：客户、目标、一句话判断、3--5 条关键发现和会前重点；
2. 客户近期关键动态：按已验证 Fact 聚类，显示时间、来源等级与时效；
3. 售前相关技术信号：Data、AI、Cloud、Infrastructure 四类中有证据的项；
4. 机会假设：公开信号、可能关联能力、待确认事项；
5. Discovery Questions：业务、架构、痛点、规模、计划等分类；
6. 信息缺口与风险提示：人类可读的缺口、历史资料和二手来源提示；
7. 当前判断边界：已知、假设、未知。

附录：

8. Evidence Appendix：正文中的 `[E001]` 对应原文、来源、发布日期、来源等级和时效；
9. Research Appendix：仅正文相关来源、失败来源、运行统计、内部 Gap/Failure 代码。

正文不展示 `NON_FACT_CLAIM`、`SEMANTIC_NOT_SUPPORTED`、无关搜索结果、HTTP 状态码或运行计数。

## 7. 确定性回退

当 Composer 不可用时：

- Executive Brief 仅展示客户、研究目标和“已生成证据驱动调研结果，请审阅关键事实”；
- 关键事实由代码按 FactTrust、来源覆盖和 Claim ID 稳定排序挑选至多 5 条；
- 机会假设和 Discovery Questions 为空时分别显示“未生成，建议人工确认”；
- Gap 使用“尚未获得足够公开证据：<现有 description>”的可读回退；
- 全部 Evidence、Source、Failure 和 Stats 仍进入附录。

## 8. 验收标准

1. HTML 与 Markdown 正文目录一致，且 Claim/Evidence ID 集合不丢失；
2. 正文没有内部 Gap code、Failure code、无关来源和运行统计；
3. 每个关键发现、机会假设和 Discovery Question 都能反查到 Claim 或 Gap；
4. 所有正文 Fact 显示 L1/L2/LU、时效和置信度；
5. 来源清单只包含正文 Fact 的支撑来源；
6. Composer 返回伪造 ID、超量条目、无验证问题的假设时被拒绝；
7. Composer 失败时仍能生成可追溯双格式报告；
8. 现有离线、集成、故障注入、Ruff 和 mypy 检查继续通过；
9. 使用现有比亚迪真实案例验证报告中不再出现技术内部标签，且至少一条机会假设明确标注为假设。
