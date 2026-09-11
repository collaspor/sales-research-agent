# Trusted Source Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every research question receive source-discovery coverage, route public PDFs through MinerU API, and expose deterministic source authority in the evidence-gated report.

**Architecture:** Keep the current LangGraph topology and SQLite generic entity store. Add pure source classification/selection before Source persistence, generalize the safe Fetcher to admit bounded PDFs, and dispatch the existing ingestion branch to HTML or a narrow MinerU-backed PDF parser. ReportModel remains the sole Markdown/HTML input and gains authority labels plus official-coverage status.

**Tech Stack:** Python 3.11, LangGraph, Pydantic v2, httpx, SQLite/aiosqlite, MinerU HTTP API, pytest, Ruff, mypy.

---

## File map

- Create `src/sales_research_agent/sources/authority.py`: URL-host allowlist configuration, deterministic authority and content-kind classification.
- Create `src/sales_research_agent/sources/selection.py`: per-question reservation, URL de-duplication and stable global ranking.
- Create `src/sales_research_agent/providers/mineru.py`: MinerU remote-URL task adapter; no domain or graph behavior.
- Create `src/sales_research_agent/ingestion/pdf_ingestor.py`: persist raw PDF and parsed text, then return the existing `IngestionResult` shape.
- Modify `src/sales_research_agent/config.py`: MinerU settings and explicit trusted-domain lists.
- Modify `src/sales_research_agent/domain/models.py`: authority/content-kind fields and expanded run statistics.
- Modify `src/sales_research_agent/ingestion/fetcher.py`: bounded HTML/PDF fetch without weakening URL checks.
- Modify `src/sales_research_agent/graph/builder.py` and `src/sales_research_agent/graph/nodes.py`: inject parser/classifier, select sources, route ingest, persist official-coverage outcome.
- Modify `src/sales_research_agent/reporting/models.py`, `compiler.py`, and `templates/report.html.j2`: authority labels and coverage/gap output from one ReportModel.
- Modify `src/sales_research_agent/cli.py`: only construct MinerU adapter in `--live` mode; require its token when PDF routing is enabled.
- Add focused unit/integration tests under `tests/unit/` and `tests/integration/`; extend `tests/fakes.py` with a `FakePdfParser`.

### Task 1: Add deterministic source authority and selection

**Files:**
- Create: `src/sales_research_agent/sources/__init__.py`
- Create: `src/sales_research_agent/sources/authority.py`
- Create: `src/sales_research_agent/sources/selection.py`
- Modify: `src/sales_research_agent/domain/models.py`
- Test: `tests/unit/test_source_authority.py`
- Test: `tests/unit/test_source_selection.py`

- [ ] **Step 1: Write failing authority/selection tests**

```python
def test_classify_source_uses_only_explicit_host_sets() -> None:
    policy = SourceAuthorityPolicy(
        official_hosts=frozenset({"haier.com"}),
        trusted_secondary_hosts=frozenset({"stcn.com"}),
    )
    assert policy.classify("https://www.haier.com/report.pdf") == SourceAuthority.OFFICIAL_PRIMARY
    assert policy.classify("https://www.stcn.com/article/1") == SourceAuthority.TRUSTED_SECONDARY
    assert policy.classify("https://unknown.example/a") == SourceAuthority.UNCLASSIFIED


def test_select_sources_reserves_one_unique_url_per_question_then_prefers_authority() -> None:
    selected = select_sources(
        {
            "q1": [candidate("https://media.example/a", "TRUSTED_SECONDARY")],
            "q2": [candidate("https://official.example/b", "OFFICIAL_PRIMARY")],
            "q3": [candidate("https://media.example/a", "TRUSTED_SECONDARY"), candidate("https://official.example/c", "OFFICIAL_PRIMARY")],
            "q4": [candidate("https://other.example/d", "UNCLASSIFIED")],
        },
        max_sources=6,
    )
    assert [item.url for item in selected] == [
        "https://media.example/a", "https://official.example/b",
        "https://official.example/c", "https://other.example/d",
    ]
    assert selected[0].question_ids == ("q1", "q3")
```

- [ ] **Step 2: Run the two tests and verify RED**

Run: `uv run pytest tests/unit/test_source_authority.py tests/unit/test_source_selection.py -q`  
Expected: import errors because the authority and selection modules do not exist.

- [ ] **Step 3: Implement strict models and pure functions**

Add `SourceAuthority = Literal["OFFICIAL_PRIMARY", "TRUSTED_SECONDARY", "UNCLASSIFIED"]` and `ContentKind = Literal["HTML", "PDF", "UNKNOWN"]` in `domain/models.py`; require both on `Source`. `SourceAuthorityPolicy` must normalize host names, match exact host or subdomain only, and default to `UNCLASSIFIED`. `select_sources` must:

1. canonicalize candidates by URL;
2. reserve the first new candidate for each question in question order;
3. merge question IDs when a URL recurs;
4. fill remaining slots with stable sort key `(-authority_rank, -score, original_order)`;
5. never exceed `max_sources`.

Do not call a model or the network in these functions.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/unit/test_source_authority.py tests/unit/test_source_selection.py -q`  
Expected: all pass.

- [ ] **Step 5: Commit the isolated behavior**

```powershell
git add src/sales_research_agent/sources src/sales_research_agent/domain/models.py tests/unit/test_source_authority.py tests/unit/test_source_selection.py
git commit -m "feat: select ranked sources per research question"
```

### Task 2: Generalize safe fetch results to bounded PDF input

**Files:**
- Modify: `src/sales_research_agent/ingestion/fetcher.py`
- Test: `tests/unit/test_fetcher.py`

- [ ] **Step 1: Write failing fetcher tests**

```python
@pytest.mark.asyncio
async def test_fetcher_accepts_bounded_pdf_without_relaxing_url_policy() -> None:
    response = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    fetcher = make_fetcher(response)
    result = await fetcher.fetch("https://public.example/report.pdf")
    assert result.failure is None
    assert result.content_kind == "PDF"
    assert result.body == b"%PDF"


@pytest.mark.asyncio
async def test_fetcher_rejects_other_binary_content() -> None:
    result = await make_fetcher(httpx.Response(200, headers={"content-type": "image/png"})).fetch(URL)
    assert result.failure is not None
    assert result.failure.code == "UNSUPPORTED_CONTENT_TYPE"
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/unit/test_fetcher.py -q`  
Expected: `FetchResult` has no `content_kind`, and PDFs are rejected.

- [ ] **Step 3: Implement the minimal safe extension**

Keep all redirect, DNS, timeout, byte-limit and status handling unchanged. Add `application/pdf` to an explicit allowlist and return `content_kind="PDF"`; HTML responses return `"HTML"`. No extension-only acceptance, no new redirect behavior, and no increase to `MAX_RESPONSE_BYTES`.

- [ ] **Step 4: Run focused tests and existing fetcher tests**

Run: `uv run pytest tests/unit/test_fetcher.py -q`  
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/sales_research_agent/ingestion/fetcher.py tests/unit/test_fetcher.py
git commit -m "feat: admit bounded public pdf responses"
```

### Task 3: Add a narrow, retry-bounded MinerU PDF adapter

**Files:**
- Create: `src/sales_research_agent/providers/mineru.py`
- Modify: `src/sales_research_agent/providers/base.py`
- Modify: `src/sales_research_agent/config.py`
- Test: `tests/unit/test_mineru_provider.py`

- [ ] **Step 1: Write failing adapter contract tests**

```python
@pytest.mark.asyncio
async def test_mineru_url_task_returns_markdown_after_done_poll() -> None:
    parser = MinerUPdfParser(api_key="test-key", client=sequence_client(
        submit={"code": 0, "data": {"task_id": "task-1"}},
        status={"code": 0, "data": {"state": "done", "markdown_url": "https://result.example/a.md"}},
        markdown="# parsed\nRevenue 10%",
    ))
    result = await parser.parse(b"%PDF", "https://public.example/a.pdf")
    assert result.task_id == "task-1"
    assert result.text == "# parsed\nRevenue 10%"


@pytest.mark.asyncio
async def test_mineru_timeout_is_a_redacted_failure_after_three_transient_attempts() -> None:
    parser = MinerUPdfParser(api_key="secret-never-output", client=always_timeout_client())
    with pytest.raises(MinerURetriableError) as raised:
        await parser.parse(b"%PDF", "https://public.example/a.pdf")
    assert "secret-never-output" not in str(raised.value)
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/unit/test_mineru_provider.py -q`  
Expected: import error for `MinerUPdfParser`.

- [ ] **Step 3: Implement against the documented asynchronous URL protocol**

Define `PdfParser.parse(pdf_bytes: bytes, source_url: str) -> ParsedPdf`. The first production adapter submits the already safety-validated public `source_url` to MinerU's authenticated `/api/v4/extract/task` endpoint, polls the documented task-result endpoint until `done`/`failed`, then downloads the returned Markdown with the same bounded client. Preserve the locally downloaded `pdf_bytes` for artifacts; do not upload it a second time in this first implementation.

The adapter must validate Pydantic response models, retry only timeout/network/429/5xx up to three attempts, bound polling by a configurable 300-second deadline, and surface only typed/redacted errors. Add `MINERU_API_KEY`, `MINERU_BASE_URL`, `MINERU_POLL_SECONDS`, and `MINERU_TIMEOUT_SECONDS` settings; `live_mode` requires MinerU credentials only when a PDF source is selected, not at CLI startup.

- [ ] **Step 4: Run focused adapter/config tests**

Run: `uv run pytest tests/unit/test_mineru_provider.py tests/unit/test_config.py -q`  
Expected: all pass; no token appears in output.

- [ ] **Step 5: Commit**

```powershell
git add src/sales_research_agent/providers src/sales_research_agent/config.py tests/unit/test_mineru_provider.py tests/unit/test_config.py
git commit -m "feat: add bounded mineru pdf parser"
```

### Task 4: Route HTML/PDF ingestion and preserve traceability

**Files:**
- Create: `src/sales_research_agent/ingestion/pdf_ingestor.py`
- Modify: `src/sales_research_agent/ingestion/ingestor.py`
- Modify: `src/sales_research_agent/graph/builder.py`
- Modify: `src/sales_research_agent/graph/nodes.py`
- Modify: `tests/fakes.py`
- Test: `tests/integration/test_pdf_ingestion.py`
- Test: `tests/integration/test_poc_graph.py`

- [ ] **Step 1: Write failing integration tests**

```python
@pytest.mark.asyncio
async def test_pdf_ingestion_persists_original_and_mineru_text_then_creates_block(pdf_harness) -> None:
    result = await pdf_harness.run()
    assert result["successful_source_ids"] == ["source-pdf"]
    refs = await pdf_harness.repository.list_artifact_refs(pdf_harness.run_id)
    assert {ref.media_type for ref in refs} >= {"application/pdf", "text/markdown"}
    blocks = await pdf_harness.repository.list_document_blocks(pdf_harness.run_id)
    assert blocks[0].text == "# 2025 年报\n营收 100 亿元"


@pytest.mark.asyncio
async def test_pdf_parser_failure_keeps_other_html_source_reportable(mixed_harness) -> None:
    state = await mixed_harness.run()
    assert "source-pdf" in state["failed_source_ids"]
    assert "source-html" in state["successful_source_ids"]
    assert await mixed_harness.repository.list_failures(mixed_harness.run_id)
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/integration/test_pdf_ingestion.py -q`  
Expected: missing `FakePdfParser`/PDF routing behavior.

- [ ] **Step 3: Implement the route without duplicating evidence logic**

Introduce one `SourceIngestor` that calls the safe Fetcher exactly once, persists the returned raw bytes, and dispatches the already-fetched body by `FetchResult.content_kind`. Keep `HtmlIngestor` and `PdfIngestor` responsible only for HTML extraction and MinerU parsing respectively. `PdfIngestor` writes returned Markdown as `text/markdown` and returns the existing `IngestionResult`. The graph node consumes that result, creates `DocumentBlock`, and runs the existing `ResearchPipeline` exactly once for either successful route.

Use `Failure.operation="PDF_INGESTION"` for parser outcomes, preserve `HTML_INGESTION` for HTML, and store MinerU task ID only in an audit event/artifact metadata—never State, report output, or logs containing secrets.

- [ ] **Step 4: Run focused integration regression**

Run: `uv run pytest tests/integration/test_pdf_ingestion.py tests/integration/test_poc_graph.py -q`  
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/sales_research_agent/ingestion src/sales_research_agent/graph tests/fakes.py tests/integration/test_pdf_ingestion.py tests/integration/test_poc_graph.py
git commit -m "feat: route public pdf sources through mineru"
```

### Task 5: Apply per-question source reservation and report source authority

**Files:**
- Modify: `src/sales_research_agent/graph/nodes.py`
- Modify: `src/sales_research_agent/reporting/models.py`
- Modify: `src/sales_research_agent/reporting/compiler.py`
- Modify: `src/sales_research_agent/reporting/templates/report.html.j2`
- Test: `tests/integration/test_source_discovery.py`
- Test: `tests/unit/test_report_compiler.py`

- [ ] **Step 1: Write failing source/disclosure tests**

```python
@pytest.mark.asyncio
async def test_discovery_searches_each_question_and_merges_duplicate_source_lineage(harness) -> None:
    await harness.run_until("discover_sources")
    assert [query for query, _ in harness.search.calls] == ["q1", "q2", "q3", "q4"]
    source = await harness.repository.get_source("source-0")
    assert source.discovered_by_question_ids == ["question-0", "question-2"]


def test_secondary_fact_is_labeled_in_both_report_formats(secondary_report_model) -> None:
    assert "二手来源，待官方验证" in compile_markdown(secondary_report_model)
    assert "二手来源，待官方验证" in compile_html(secondary_report_model)
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/integration/test_source_discovery.py tests/unit/test_report_compiler.py -q`  
Expected: old discovery stops source selection after the first question reaches six; report has no authority label.

- [ ] **Step 3: Implement selection and ReportModel disclosure**

In `discover_sources`, collect candidates for every persisted question before calling `select_sources`; construct one `Source` per selected URL with merged `discovered_by_question_ids`, deterministic authority and an initial `UNKNOWN` content kind. In `_build_report`, exclude `UNCLASSIFIED` sources from Fact source IDs; if an otherwise approved Fact loses all allowed sources, add an `UNCLASSIFIED_SOURCE_ONLY` Gap and omit that Fact.

Extend `ReportSource`, `ReportFact`, and `ReportStats` with authority/official coverage fields. Compiler output must use fixed Chinese labels, retain `data-claim-id` and `data-evidence-id`, and leave existing escaping intact. `publish` sets `PARTIAL` and adds one idempotent `OFFICIAL_SOURCE_MISSING` Gap when approved Facts exist but no successful `OFFICIAL_PRIMARY` source exists.

- [ ] **Step 4: Run report and discovery regression**

Run: `uv run pytest tests/integration/test_source_discovery.py tests/unit/test_report_compiler.py tests/integration/test_offline_end_to_end.py -q`  
Expected: all pass, with Markdown/HTML Claim and Evidence ID sets still equal.

- [ ] **Step 5: Commit**

```powershell
git add src/sales_research_agent/graph/nodes.py src/sales_research_agent/reporting tests/integration/test_source_discovery.py tests/unit/test_report_compiler.py tests/integration/test_offline_end_to_end.py
git commit -m "feat: disclose authority and official coverage"
```

### Task 6: Wire live CLI, audit usage, and verify the P0 acceptance suite

**Files:**
- Modify: `src/sales_research_agent/cli.py`
- Modify: `src/sales_research_agent/domain/models.py`
- Modify: `src/sales_research_agent/graph/nodes.py`
- Modify: `README.md`
- Create: `docs/poc/2026-09-11-trusted-source-loop-review.md`
- Test: `tests/unit/test_cli.py`
- Test: `tests/integration/test_offline_end_to_end.py`

- [ ] **Step 1: Write failing CLI/statistics tests**

```python
def test_live_settings_allow_html_only_run_without_mineru_credential(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
    monkeypatch.delenv("MINERU_API_KEY", raising=False)
    settings = Settings(live_mode=True)
    assert settings.mineru_api_key is None


@pytest.mark.asyncio
async def test_stats_records_search_calls_and_authority_counts(offline_run) -> None:
    stats = await offline_run.repository.get_stats(offline_run.run_id)
    assert stats is not None
    assert stats.search_calls == 4
    assert stats.official_sources_succeeded >= 0
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/unit/test_cli.py tests/integration/test_offline_end_to_end.py -q`  
Expected: statistics fields and optional MinerU settings do not exist.

- [ ] **Step 3: Implement minimal wiring and audit fields**

Pass the configured `SourceAuthorityPolicy` and lazy `MinerUPdfParser` into `Services`. Do not fail a fully HTML run merely because MinerU credentials are absent; when a selected PDF is encountered, record `MINERU_CONFIGURATION_MISSING` as a source failure. Persist start/end time, search call count, official/secondary success counts, and each successful Tavily response's redacted request ID/credit count when `include_usage=true`; make `inspect` print these numeric fields only.

Document required environment variables and the fact that live MinerU requests send public PDFs/URLs to a third party. Do not add real keys to `.env.example`, docs, test fixtures, artifacts, or Git.

- [ ] **Step 4: Run complete offline acceptance suite**

Run: `uv lock --check; uv sync --locked; uv run pytest -m "not live" -q; uv run ruff check .; uv run mypy src`  
Expected: all pass with no warnings.

- [ ] **Step 5: Run explicit live acceptance only after the user supplies `MINERU_API_KEY`**

Run: `uv run sales-research run --case evals/cases/haier_first_meeting.json --live`  
Expected: all four questions call Tavily, at least one official source and one PDF are successfully ingested, Markdown/HTML show authority labels, and `inspect` reports duration/call/authority statistics without keys.

If any public site returns 403 or MinerU cannot parse a selected file, record the actual failure in the review document; do not claim the acceptance condition passed.

- [ ] **Step 6: Commit and push the verified outcome**

```powershell
git add src tests README.md docs/poc
git commit -m "feat: complete trusted source loop"
git push origin feat/risk-validation-poc
```

## Final verification and rollback

Run after Task 6: `uv lock --check; uv run pytest -m "not live" -q; uv run ruff check .; uv run mypy src; git status --short --branch`.

Rollback is commit-level: revert the most recent task commit only, then run its focused test command. Never delete `var/runs`; live run artifacts are ignored evidence and can be retained for audit.
