# Presales Intelligence Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动检索、摄取、Evidence 审批和 Claim 核验链路的前提下，将输出重构为售前会前可读的 Intelligence Brief，并保持每一项面向客户的判断可回溯到已审批事实与证据。

**Architecture:** 在 `publish` 节点构造冻结的报告事实视图；可选的 DeepSeek 编排器仅从该视图选择、归纳和组织内容，不能新增事实；确定性校验器验证所有 Claim、Evidence、Source 与 Gap 血缘。校验或模型失败时退化为确定性视图。Markdown 与 HTML 只渲染同一个 `ReportModel`，正文仅显示可读内容，审计细节进入附录。

**Tech Stack:** Python 3.11、Pydantic、LangGraph、LangChain OpenAI-compatible client、Jinja2、pytest、ruff、mypy。

---

## Scope and invariants

- 保留现有 Tavily、Fetcher、MinerU、Evidence、Claim approval、SQLite 和主要 Graph 拓扑。
- 正文只输出绑定已审批事实的内容；模型不能创建 Source、Evidence、Claim 或将机会假设写成客户需求。
- 编排器失败、超时、结构不合法或血缘不合法时，报告仍应发布确定性回退版本。
- 正文不暴露 `NON_FACT_CLAIM`、HTTP 状态码、内部 Failure code、无关搜索结果或运行统计；这些仅进入 Research Appendix。
- 正式来源和 Evidence 附录只保留支撑正文结论的来源；审计库继续保留完整采集记录。

## Task 1: Build immutable report-view and trust contracts

**Files:**
- Modify: `src/sales_research_agent/reporting/models.py`
- Add: `src/sales_research_agent/reporting/trust.py`
- Add: `tests/unit/test_reporting_trust.py`

- [ ] **Step 1: Write failing tests for source labels, freshness and confidence.**

  Test a fact supported by a dated official source (`L1 · Current · High Confidence`), a dated secondary source (`L2 · Historical · Medium/Low` according to the documented rule), a date-less source (`Date Unknown`), and a future-oriented fact (`Forward-looking`). Test that the result retains its Claim/Evidence/Source IDs.

  Run: `uv run pytest tests/unit/test_reporting_trust.py -q`
  Expected: FAIL because the new view contracts and trust helpers do not exist.

- [ ] **Step 2: Add immutable presentation models and deterministic trust helpers.**

  Add `FactTrust`, `BriefHeader`, `KeyFinding`, `OpportunityHypothesis`, `DiscoveryQuestion`, `ReadableGap`, and `ResearchAppendix` to the existing frozen report model module. Extend `ReportModel` with default-empty view fields so older tests can construct it unchanged. In `trust.py`, calculate authority code, date state, confidence and display label from `ReportFact` plus linked `ReportSource`; preserve existing `eligible_for_summary` for outcome semantics.

  Required behavior:
  ```python
  assert build_fact_trust(fact, sources).label == "L1 · Current · High Confidence"
  assert build_fact_trust(forward_fact, sources).time_status == "Forward-looking"
  ```

- [ ] **Step 3: Run focused tests and static checks.**

  Run: `uv run pytest tests/unit/test_reporting_trust.py -q; uv run ruff check src/sales_research_agent/reporting tests/unit/test_reporting_trust.py`
  Expected: PASS.

## Task 2: Add constrained composition schema and deterministic fallback

**Files:**
- Add: `src/sales_research_agent/reporting/composer.py`
- Modify: `src/sales_research_agent/reporting/models.py`
- Add: `tests/unit/test_report_composer.py`

- [ ] **Step 1: Write failing lineage tests.**

  Cover an accepted composition with known Claim IDs, rejected unknown Claim/Evidence/Gap IDs, rejected empty lineage, rejected more-than-five key items, and a deterministic fallback whose items still point to known facts.

  Run: `uv run pytest tests/unit/test_report_composer.py -q`
  Expected: FAIL because the composer contracts do not exist.

- [ ] **Step 2: Implement schema, validator and fallback.**

  Define `ReportComposition` as a provider-safe Pydantic contract with structured fields: executive judgment, key findings, opportunity hypotheses, discovery questions and readable gaps. Define `validate_composition(base_report, composition)` that only accepts referenced IDs already present in `base_report`; enforce 1–5 key findings/opportunity hypotheses/discovery questions, and label all opportunities as hypotheses. Define `fallback_composition(base_report)` that derives concise cards, questions and readable gaps without model output.

  Required validation shape:
  ```python
  known_claim_ids = {fact.claim_id for fact in report.facts}
  if not set(item.claim_ids) <= known_claim_ids:
      raise ReportCompositionValidationError("unknown claim lineage")
  ```

- [ ] **Step 3: Run focused tests.**

  Run: `uv run pytest tests/unit/test_report_composer.py -q`
  Expected: PASS.

## Task 3: Add the optional DeepSeek report-composer port

**Files:**
- Modify: `src/sales_research_agent/providers/base.py`
- Modify: `src/sales_research_agent/providers/deepseek.py`
- Modify: `tests/fakes.py`
- Modify: `tests/unit/test_deepseek_provider.py`

- [ ] **Step 1: Write a failing adapter contract test.**

  Queue a valid `ReportComposition` JSON response. Assert the provider invokes operation `compose_report`, requests JSON object mode, records a DeepSeek audit event and sends only report-view input (not raw page contents).

  Run: `uv run pytest tests/unit/test_deepseek_provider.py -q`
  Expected: FAIL because `compose_report` is missing.

- [ ] **Step 2: Extend the stable provider interface without changing research methods.**

  Add `async compose_report(self, report_input: ReportCompositionInput) -> ReportComposition` to `ResearchModel`. Implement it through existing `_request_structured` under operation `compose_report`; use the run ID as related entity. Extend `FakeResearchModel` with an explicit response queue and call log. The system instruction must state that the model may only organize supplied IDs and must not create customer needs or ungrounded facts.

- [ ] **Step 3: Run adapter and fake-dependent tests.**

  Run: `uv run pytest tests/unit/test_deepseek_provider.py tests/integration -q`
  Expected: PASS.

## Task 4: Compose at publish time with a non-blocking fallback

**Files:**
- Modify: `src/sales_research_agent/graph/nodes.py`
- Modify: `tests/fakes.py`
- Add: `tests/integration/test_intelligence_brief_publish.py`

- [ ] **Step 1: Write failing publish-node tests.**

  Run an offline graph with one queued composition and assert the published model contains Brief header, composition view and only referenced sources. Run again with a composer exception and assert the graph finishes and publishes `composition_mode == "FALLBACK"`.

  Run: `uv run pytest tests/integration/test_intelligence_brief_publish.py -q`
  Expected: FAIL because publish never invokes a composer or fallback.

- [ ] **Step 2: Construct the report input only from persisted approved entities.**

  Update `_build_report` to include the persisted Brief and deterministic base view. In `publish`, call `services.model.compose_report(...)` after base construction; pass output through `validate_composition`, materialize it into immutable report view fields, and catch provider/schema/lineage errors to materialize `fallback_composition`. Do not swallow database or artifact publishing errors. Keep existing report outcome rules; update the current summary eligibility check to inspect rendered key facts rather than reintroducing old body semantics.

- [ ] **Step 3: Run graph and existing integration suites.**

  Run: `uv run pytest tests/integration/test_intelligence_brief_publish.py tests/integration/test_report_artifacts.py tests/integration/test_poc_flow.py -q`
  Expected: PASS.

## Task 5: Rewrite Markdown as the presales-readable report

**Files:**
- Modify: `src/sales_research_agent/reporting/compiler.py`
- Modify: `tests/unit/test_report_compiler.py`

- [ ] **Step 1: Replace legacy heading assertions with failing Intelligence Brief assertions.**

  Assert the body contains Executive Brief, key facts, opportunity hypotheses, Discovery Questions, readable gaps and judgment boundaries. Assert it excludes `NON_FACT_CLAIM`, raw failure codes and unrelated source titles. Assert cited facts expose `data-claim-id` and evidence links, while appendix keeps original source URL and evidence quote.

  Run: `uv run pytest tests/unit/test_report_compiler.py -q`
  Expected: FAIL because the legacy compiler uses old sections.

- [ ] **Step 2: Render the new body and filtered appendices from one model.**

  Replace the legacy section construction with these ordered sections:
  1. Executive Brief;
  2. 客户近期关键动态 / 售前相关技术信号;
  3. 售前机会假设;
  4. 首次交流建议问题;
  5. 当前判断边界与信息缺口;
  6. Appendix A — Evidence Index;
  7. Appendix B — Sources Used;
  8. Appendix C — Research Quality.

  Map only referenced source IDs into Appendix A/B. Translate gaps to readable text; keep raw Gap/Failure codes only in Appendix C. Use the deterministic trust label for every cited key fact. Keep `_claim_marker` and `_evidence_marker` unchanged so old audit/HTML-ID guarantees hold.

- [ ] **Step 3: Run Markdown and artifact tests.**

  Run: `uv run pytest tests/unit/test_report_compiler.py tests/integration/test_report_artifacts.py -q`
  Expected: PASS.

## Task 6: Render the same information architecture in HTML

**Files:**
- Modify: `src/sales_research_agent/reporting/templates/report.html.j2`
- Modify: `src/sales_research_agent/reporting/compiler.py`
- Modify: `tests/unit/test_report_compiler.py`

- [ ] **Step 1: Add failing HTML structural and safety tests.**

  Assert HTML contains the same key headings and data IDs as Markdown, escaped external text, clickable source links, and no raw code in the main `<section>` before Appendix C.

  Run: `uv run pytest tests/unit/test_report_compiler.py -q`
  Expected: FAIL until the template uses the new view context.

- [ ] **Step 2: Replace the template with readable semantic HTML.**

  Use UTF-8 semantic sections, tables only for opportunity hypotheses and source index, source/evidence anchors, and display labels emitted by deterministic compiler helpers. Preserve Jinja autoescaping. Do not add a new frontend framework or server dependency.

- [ ] **Step 3: Run all report rendering tests.**

  Run: `uv run pytest tests/unit/test_report_compiler.py tests/integration/test_report_artifacts.py -q`
  Expected: PASS.

## Task 7: Verify behavior, document the new report contract, and publish

**Files:**
- Modify: `README.md`
- Add: `docs/intelligence-brief-report-contract.md`
- Modify: relevant test fixtures only if required by the new frozen contract

- [ ] **Step 1: Add a concise report contract.**

  Document the front/body vs appendix split, lineage rules, labels, fallback semantics, and operator expectations. Update README’s MVP status accurately: the output layer is an Intelligence Brief; it remains a local MVP and does not claim production service readiness.

- [ ] **Step 2: Run the complete offline verification set.**

  Run: `uv run pytest -q; uv run ruff check .; uv run mypy src; git diff --check`
  Expected: all tests and checks pass, with no UTF-8 corruption and no secret changes.

- [ ] **Step 3: Run an offline end-to-end report inspection.**

  Run: `uv run pytest tests/integration/test_intelligence_brief_publish.py -q` and inspect the generated Markdown/HTML strings through the test assertions. If configured credentials and user authorization remain available, run one bounded live case only after offline suite succeeds; otherwise record that live verification is a follow-up, not silently simulated.

- [ ] **Step 4: Commit and push only project files.**

  Verify `git status --short`; do not stage `docs/interview-prep.html` or `tests/售前客户公网调研报告 Markdown 模板.md`. Commit implementation and documentation, then push `main` using the established SSH flow.

## Self-review

- [ ] Every body statement has Claim/Evidence/Source or Gap lineage.
- [ ] A composer cannot add an ID or bypass validation.
- [ ] Composer failure produces a valid deterministic report.
- [ ] Markdown and HTML remain same-model, escaped, linked and ID-consistent.
- [ ] Existing report publishing rollback and Graph outcome behavior remain covered.
- [ ] No unrelated untracked user files or secrets are included.
