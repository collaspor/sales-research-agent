# Risk Validation POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建并真实运行一个以海尔智家为固定案例的证据驱动调研 POC，验证 Tavily 搜索、静态 HTML 摄取、DeepSeek 结构化抽取、引用核验、LangGraph 恢复与双格式报告链路。

**Architecture:** 使用 Python 3.11 的 `src` 布局；顶层 LangGraph 只保存实体 ID 和控制字段，领域实体写入独立 SQLite，原始网页和报告写入本地 Artifact Store，Graph 执行位置写入独立 SQLite Checkpointer。所有外部能力通过小型 port 注入；默认测试完全离线，最后显式执行一次 live POC。

**Tech Stack:** Python 3.11、uv、Pydantic、pydantic-settings、LangGraph 1.2.x、langgraph-checkpoint-sqlite 3.1.x、langchain-openai 1.6.x、HTTPX、Trafilatura 2.2.x、aiosqlite、Typer、Jinja2、pytest、pytest-asyncio、Ruff、mypy。

---

## 0. 实施约束

- 严格按任务顺序执行；每个行为先写测试并确认因缺少实现而失败。
- 不读取或修改项目 A/B 的代码；只有 live 运行时可从旧项目本地 `.env` 向子进程注入现有密钥，不能打印密钥。
- 不创建或提交真实 `.env`；只提交 `.env.example`。
- `var/`、数据库、网页、模型响应和报告运行产物不得进入 Git。
- 每项任务独立提交；提交前运行本任务测试和 `uv run ruff check .`。
- 实现中发现官方 API 与计划不一致时，先用最小兼容性测试证明，再更新本计划和规格，不能静默绕过。

## 1. 文件结构

```text
pyproject.toml
uv.lock
.python-version
.env.example
src/sales_research_agent/
├── __init__.py
├── cli.py
├── config.py
├── runtime.py
├── domain/
│   ├── models.py
│   └── repository.py
├── infrastructure/
│   ├── artifacts.py
│   └── sqlite_repository.py
├── providers/
│   ├── base.py
│   ├── deepseek.py
│   └── tavily.py
├── ingestion/
│   ├── extractor.py
│   ├── fetcher.py
│   └── url_policy.py
├── verification/
│   ├── gate.py
│   ├── numeric_guard.py
│   └── quote_locator.py
├── reporting/
│   ├── compiler.py
│   ├── models.py
│   └── templates/report.html.j2
└── graph/
    ├── builder.py
    ├── nodes.py
    └── state.py
tests/
├── conftest.py
├── fakes.py
├── fixtures/
│   ├── deepseek/
│   ├── html/
│   └── tavily/
├── unit/
├── integration/
├── fault_injection/
└── live/
evals/cases/haier_first_meeting.json
docs/poc/
├── live-run-review-template.md
└── decision-record-template.md
```

职责边界：`domain` 不依赖 LangGraph、HTTP 或具体 Provider；`providers` 与 `ingestion` 返回领域层可理解的数据；`graph` 只编排服务；`reporting` 只能消费批准后的 ReportModel 输入。

### Task 1: 初始化可重建工程与安全配置

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.env.example`
- Create: `src/sales_research_agent/__init__.py`
- Create: `src/sales_research_agent/config.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/live/test_live_marker.py`
- Modify: `.gitignore`
- Modify: `README.md`
- 本阶段不注册命令入口；CLI 创建于 Task 9，避免在 `cli.py` 尚不存在时安装出必然崩溃的命令。

- [ ] **Step 1: 只创建工程元数据并安装锁定依赖**

先创建 `pyproject.toml`、`.python-version`、`.env.example`、`src/sales_research_agent/__init__.py`，并更新 `.gitignore` 与 README；此时不要创建 `config.py`。

`pyproject.toml` 使用：

```toml
[project]
name = "sales-research-agent"
version = "0.1.0"
description = "Evidence-driven presales research agent"
readme = "README.md"
requires-python = ">=3.11,<3.12"
dependencies = [
  "aiosqlite>=0.21,<1",
  "httpx>=0.28,<1",
  "jinja2>=3.1,<4",
  "langchain-openai>=1.6,<2",
  "langgraph>=1.2,<2",
  "langgraph-checkpoint-sqlite>=3.1,<4",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3",
  "trafilatura>=2.2,<3",
  "typer>=0.16,<1",
]

[dependency-groups]
dev = [
  "mypy>=1.17,<2",
  "pytest>=8.4,<9",
  "pytest-asyncio>=1.1,<2",
  "ruff>=0.12,<1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = '-m "not live"'
markers = ["live: requires real network and provider credentials"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["sales_research_agent"]
```

`.env.example` 只写变量名、无真实值；`.gitignore` 增加 `.env`、`.venv/`、`var/`；README 写清离线测试与 live 运行边界。

Run: `uv lock && uv sync --locked`
Expected: 生成 `uv.lock` 与项目内 `.venv`，依赖同步成功。

- [ ] **Step 2: 写配置失败测试**

```python
# tests/unit/test_config.py
import pytest
from pydantic import ValidationError

from sales_research_agent.config import Settings


def test_live_settings_require_provider_keys() -> None:
    with pytest.raises(ValidationError):
        Settings(tavily_api_key=None, deepseek_api_key=None, live_mode=True)


def test_offline_settings_do_not_require_provider_keys() -> None:
    settings = Settings(tavily_api_key=None, deepseek_api_key=None, live_mode=False)
    assert settings.live_mode is False
    assert settings.max_sources == 6
    assert settings.max_concurrency == 3
```

- [ ] **Step 3: 运行测试并确认 RED**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: FAIL，`sales_research_agent.config` 不存在。

- [ ] **Step 4: 创建最小配置实现**

`src/sales_research_agent/config.py` 使用：

```python
from pathlib import Path
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tavily_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    live_mode: bool = False
    run_root: Path = Path("var/runs")
    max_questions: int = 4
    max_sources: int = 6
    max_concurrency: int = 3
    deadline_minutes: int = 30
    langgraph_strict_msgpack: bool = True

    @model_validator(mode="after")
    def validate_live_keys(self) -> Self:
        if self.live_mode and (not self.tavily_api_key or not self.deepseek_api_key):
            raise ValueError("live mode requires Tavily and DeepSeek API keys")
        return self
```

- [ ] **Step 5: 运行 GREEN**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: 2 passed。

- [ ] **Step 6: 验证导入无副作用**

Run: `uv run python -c "import sales_research_agent; print('import-ok')"`
Expected: `import-ok`，且未创建 `var/`、未访问网络、未要求 Key。

- [ ] **Step 7: 质量检查并提交**

Run: `uv run ruff check . && uv run mypy src`
Expected: 两项均通过。

```powershell
git add pyproject.toml uv.lock .python-version .env.example .gitignore README.md src tests
git commit -m "build: initialize poc project"
```

### Task 2: 锁定 LangGraph SQLite Checkpointer 兼容行为

**Files:**
- Create: `src/sales_research_agent/graph/state.py`
- Create: `tests/integration/test_checkpoint_compatibility.py`

- [ ] **Step 1: 写最小持久化和 pending writes 测试**

```python
# tests/integration/test_checkpoint_compatibility.py
from pathlib import Path
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph


def append(values: list[str], update: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *update]))


class State(TypedDict):
    completed: Annotated[list[str], append]


@pytest.mark.asyncio
async def test_async_sqlite_saver_keeps_successful_pending_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    calls = {"successful": 0, "failing": 0, "join": 0}

    async def successful(_: State) -> dict[str, list[str]]:
        calls["successful"] += 1
        return {"completed": ["successful"]}

    async def failing(_: State) -> dict[str, list[str]]:
        calls["failing"] += 1
        if calls["failing"] == 1:
            raise RuntimeError("injected crash")
        return {"completed": ["failing"]}

    async def join(_: State) -> dict[str, list[str]]:
        calls["join"] += 1
        return {"completed": ["join"]}

    builder = StateGraph(State)
    builder.add_node("successful", successful)
    builder.add_node("failing", failing)
    builder.add_node("join", join)
    builder.add_edge(START, "successful")
    builder.add_edge(START, "failing")
    builder.add_edge(["successful", "failing"], "join")
    builder.add_edge("join", END)
    config = {"configurable": {"thread_id": "checkpoint-test"}}

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite3")) as saver:
        graph = builder.compile(checkpointer=saver)
        with pytest.raises(RuntimeError, match="injected crash"):
            await graph.ainvoke({"completed": []}, config=config)
        result = await graph.ainvoke(None, config=config)

    assert set(result["completed"]) == {"successful", "failing", "join"}
    assert calls == {"successful": 1, "failing": 2, "join": 1}
```

- [ ] **Step 2: 运行并确认实际兼容结果**

Run: `uv run pytest tests/integration/test_checkpoint_compatibility.py -q`
Expected: 测试在当前锁定依赖上通过。如果失败，只允许依据官方 API 调整 Saver 初始化或 resume 调用，并把差异记录在规格“决策门”中。

- [ ] **Step 3: 定义可序列化 POC State**

```python
# src/sales_research_agent/graph/state.py
from typing import Annotated, NotRequired, TypedDict


def merge_unique(current: list[str], update: list[str]) -> list[str]:
    return list(dict.fromkeys([*current, *update]))


class PocState(TypedDict):
    run_id: str
    thread_id: str
    brief_id: str
    research_question_ids: Annotated[list[str], merge_unique]
    source_ids: Annotated[list[str], merge_unique]
    successful_source_ids: Annotated[list[str], merge_unique]
    failed_source_ids: Annotated[list[str], merge_unique]
    evidence_ids: Annotated[list[str], merge_unique]
    claim_ids: Annotated[list[str], merge_unique]
    approved_claim_ids: Annotated[list[str], merge_unique]
    rejected_claim_ids: Annotated[list[str], merge_unique]
    gap_ids: Annotated[list[str], merge_unique]
    failure_ids: Annotated[list[str], merge_unique]
    report_version_id: NotRequired[str | None]
    execution_status: str
    report_outcome: str
    started_at: str
    deadline_at: str
    current_source_id: NotRequired[str]
```

- [ ] **Step 4: 运行测试、类型检查并提交**

Run: `uv run pytest tests/integration/test_checkpoint_compatibility.py -q && uv run mypy src`
Expected: PASS。

```powershell
git add src/sales_research_agent/graph tests/integration/test_checkpoint_compatibility.py
git commit -m "test: validate sqlite checkpoint recovery"
```

### Task 3: 实现最小领域模型、SQLite Repository 与 Artifact Store

**Files:**
- Create: `src/sales_research_agent/domain/models.py`
- Create: `src/sales_research_agent/domain/repository.py`
- Create: `src/sales_research_agent/infrastructure/sqlite_repository.py`
- Create: `src/sales_research_agent/infrastructure/artifacts.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_domain_models.py`
- Create: `tests/integration/test_sqlite_repository.py`
- Create: `tests/integration/test_artifact_store.py`

- [ ] **Step 1: 写 lineage 与幂等失败测试**

```python
def test_fact_requires_evidence_id() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="claim-1",
            run_id="run-1",
            kind="FACT",
            text="公开事实",
            evidence_ids=[],
            upstream_claim_ids=[],
            status="PROPOSED",
        )


@pytest.mark.asyncio
async def test_repository_upsert_is_idempotent(repository: SQLiteRepository) -> None:
    source = Source(
        id="src-1",
        run_id="run-1",
        url="https://example.com",
        canonical_url="https://example.com/",
        title="Example",
        source_type="OFFICIAL",
        discovered_by_question_ids=["question-1"],
    )
    await repository.upsert_source(source, operation_key="run-1:source:https://example.com")
    await repository.upsert_source(source, operation_key="run-1:source:https://example.com")
    assert len(await repository.list_sources("run-1")) == 1
```

- [ ] **Step 2: 运行并确认 RED**

Run: `uv run pytest tests/unit/test_domain_models.py tests/integration/test_sqlite_repository.py -q`
Expected: FAIL，领域类型和 Repository 尚不存在。

- [ ] **Step 3: 实现领域类型和 Repository port**

使用 Pydantic 定义以下最小字段，不增加 POC 未使用的可选字段：

```text
Brief: id, run_id, customer_name, scenario, known_context, research_goal
ResearchQuestion: id, run_id, text, purpose, preferred_source_types, completion_criteria
Source: id, run_id, url, canonical_url, title, source_type, discovered_by_question_ids
SourceRevision: id, run_id, source_id, fetched_at, final_url, status_code, raw_artifact_id, sha256
DocumentBlock: id, run_id, source_revision_id, ordinal, text, clean_start, clean_end
Evidence: id, run_id, block_id, quote, start, end, locator_method, numeric_ok, status
Claim: id, run_id, kind, text, evidence_ids, upstream_claim_ids, status
Verification: id, run_id, claim_id, evidence_id, located, numeric_ok, semantic_decision, reason
Gap: id, run_id, question_id, code, description, related_source_ids, related_claim_ids
Failure: id, run_id, operation, code, retryable, message, related_entity_id
RunStats: run_id, started_at, finished_at, search_calls, http_calls, model_calls,
          sources_succeeded, sources_failed, claims_approved, claims_rejected
ReportVersion: id, run_id, created_at, report_model_artifact_id, markdown_artifact_id,
               html_artifact_id, status, is_active
ArtifactRef: id, run_id, relative_path, sha256, media_type, size_bytes, created_at
```

所有 ID 为字符串，时间为 UTC aware datetime。枚举值严格采用规格中的大写值。FACT 的 `evidence_ids` 至少 1 个；INFERENCE 的 `upstream_claim_ids` 或 `evidence_ids` 至少一个；QUESTION 不要求证据但不能标为 APPROVED FACT。

`DomainRepository` 明确定义 `initialize()`；为 Source、SourceRevision、DocumentBlock、Evidence、Claim、Verification、Gap、Failure、ReportVersion、ArtifactRef 分别定义 `upsert_*`、`get_*` 和按 run 查询方法；另定义 `append_audit_event()`、`save_stats()`、`count_source_revisions()`、`has_duplicate_operation_keys()`。每个 `upsert_*` 都接收实体与 `operation_key`。测试 fixture 在 `tests/conftest.py` 为每个测试创建独立临时数据库并调用 `initialize()`；调用方不能执行裸 SQL。

- [ ] **Step 4: 实现最小 SQLite schema 和幂等写入**

Repository 初始化必须执行：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

每张表存储稳定 ID、`run_id`、JSON payload 和 `operation_key UNIQUE`。单次 upsert 使用短事务；重复 operation key 返回既有实体 ID。

- [ ] **Step 5: 写 Artifact 原子写入测试和实现**

```python
def test_artifact_store_writes_content_and_hash(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.write_text("run-1", "sources/src-1/clean.txt", "可信正文")
    assert store.read_text(ref) == "可信正文"
    assert ref.sha256 == hashlib.sha256("可信正文".encode()).hexdigest()
```

`ArtifactStore.write_bytes/write_text` 写入同目录临时文件，flush 后用 `Path.replace()` 原子替换，并返回包含相对路径、SHA-256、media type 和大小的 `ArtifactRef`。

- [ ] **Step 6: 运行测试并提交**

Run: `uv run pytest tests/unit/test_domain_models.py tests/integration/test_sqlite_repository.py tests/integration/test_artifact_store.py -q`
Expected: PASS。

```powershell
git add src/sales_research_agent/domain src/sales_research_agent/infrastructure tests
git commit -m "feat: add traceable domain persistence"
```

### Task 4: 实现确定性引用定位、关键 token 保护与质量门禁

**Files:**
- Create: `src/sales_research_agent/verification/quote_locator.py`
- Create: `src/sales_research_agent/verification/numeric_guard.py`
- Create: `src/sales_research_agent/verification/gate.py`
- Create: `tests/unit/test_quote_locator.py`
- Create: `tests/unit/test_numeric_guard.py`
- Create: `tests/unit/test_quality_gate.py`

- [ ] **Step 1: 写 exact/normalized 和数字改写失败测试**

```python
def test_normalized_locator_returns_original_offsets() -> None:
    text = "2025 年，营业收入增长 12.3%。"
    match = locate_quote(text, "2025年，营业收入增长12.3%。")
    assert match is not None
    assert text[match.start:match.end] == text


def test_numeric_guard_rejects_changed_percentage() -> None:
    result = compare_critical_tokens(
        source="营业收入同比增长 12.3%",
        quote="营业收入同比增长 21.3%",
    )
    assert result.ok is False
    assert result.reason == "NUMERIC_MISMATCH"
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/unit/test_quote_locator.py tests/unit/test_numeric_guard.py -q`
Expected: FAIL，定位与保护函数不存在。

- [ ] **Step 3: 实现最小算法**

`locate_quote` 先 exact `str.find`；再构建“删除 Unicode 空白并统一常见全角标点”的规范化字符流，同时保存规范化索引到原始索引的映射，返回原文 start/end。POC 不实现 fuzzy matching。

`compare_critical_tokens` 用编译正则提取百分比、金额、日期、四位年份及带单位数字，并要求候选 quote 的 token multiset 是定位原文对应 token 的相等集合。

- [ ] **Step 4: 写质量门禁测试和实现**

```python
@pytest.mark.parametrize("decision", ["UNSUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED"])
def test_external_fact_only_accepts_supported(decision: str) -> None:
    result = decide_claim(kind="FACT", located=True, numeric_ok=True, semantic=decision)
    assert result.approved is False


def test_fact_without_evidence_is_rejected() -> None:
    result = decide_claim(kind="FACT", located=False, numeric_ok=False, semantic=None)
    assert result.reason == "EVIDENCE_NOT_LOCATED"
```

`decide_claim` 的顺序固定为定位 → 数字 → 语义；只有 FACT 的三个条件全通过才批准。Inference 和 Question 使用单独分支，不能被误计入外部 Fact。

- [ ] **Step 5: 运行测试并提交**

Run: `uv run pytest tests/unit/test_quote_locator.py tests/unit/test_numeric_guard.py tests/unit/test_quality_gate.py -q`
Expected: PASS。

```powershell
git add src/sales_research_agent/verification tests/unit
git commit -m "feat: enforce deterministic citation gate"
```

### Task 5: 定义 Provider ports 并实现 Tavily 与 DeepSeek 适配器

**Files:**
- Create: `src/sales_research_agent/providers/base.py`
- Create: `src/sales_research_agent/providers/tavily.py`
- Create: `src/sales_research_agent/providers/deepseek.py`
- Create: `tests/fixtures/tavily/search_success.json`
- Create: `tests/fixtures/deepseek/plan_success.json`
- Create: `tests/unit/test_tavily_provider.py`
- Create: `tests/unit/test_deepseek_provider.py`
- Create: `tests/fakes.py`

- [ ] **Step 1: 写 Provider 契约失败测试**

```python
@pytest.mark.asyncio
async def test_tavily_maps_results_without_treating_snippet_as_evidence() -> None:
    provider = TavilySearchProvider(api_key="test", transport=fixture_transport("search_success.json"))
    results = await provider.search("海尔智家 官方 2025", max_results=3)
    assert results[0].url.startswith("https://")
    assert results[0].snippet_is_evidence is False


@pytest.mark.asyncio
async def test_deepseek_retries_one_empty_json_response() -> None:
    provider = DeepSeekProvider(client=sequence_client(["", PLAN_JSON]))
    plan = await provider.plan(HAIER_BRIEF)
    assert len(plan.questions) <= 4
    assert provider.call_count == 2
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/unit/test_tavily_provider.py tests/unit/test_deepseek_provider.py -q`
Expected: FAIL，Provider 类型不存在。

- [ ] **Step 3: 实现 ports**

`SearchProvider` 暴露 `search(query, max_results) -> list[SearchResult]`。`ResearchModel` 暴露 `plan`、`extract_evidence`、`synthesize_claims`、`verify_support`。所有返回值为 Pydantic 模型，不把 SDK/HTTP 原始对象泄露给 Graph。

`tests/fakes.py` 提供 `FixtureTransport`、`SequenceChatModel`、`FakeSearchProvider`、`FakeResearchModel` 和 `FakeFetcher`。Fake 按显式队列返回结果，并记录调用参数；不得根据生产实现内部细节生成结果。

- [ ] **Step 4: 实现 Tavily HTTP adapter**

使用注入的 `httpx.AsyncClient` POST `https://api.tavily.com/search`，请求固定：

```json
{
  "query": "海尔智家 2025 年报",
  "search_depth": "advanced",
  "max_results": 3,
  "include_answer": false,
  "include_raw_content": false
}
```

把 401/403 分类为配置错误，429/5xx/timeout 分类为可重试错误，其他 4xx 分类为永久请求错误。任何异常消息不得包含 header 或 key。

- [ ] **Step 5: 实现 DeepSeek adapter**

使用 `ChatOpenAI(model=settings.deepseek_model, base_url=settings.deepseek_base_url, api_key=SecretStr(settings.deepseek_api_key))`。请求加入 JSON system instruction、具体 Schema 示例和 `response_format={"type": "json_object"}`；用目标 Pydantic 模型执行 `model_validate_json`。空内容或 Schema 错误只修正 1 次，并保存脱敏调用统计。

- [ ] **Step 6: 运行测试并提交**

Run: `uv run pytest tests/unit/test_tavily_provider.py tests/unit/test_deepseek_provider.py -q`
Expected: PASS，测试不访问公网。

```powershell
git add src/sales_research_agent/providers tests/fixtures tests/unit
git commit -m "feat: add bounded search and model adapters"
```

### Task 6: 实现安全 URL 策略与静态 HTML 摄取

**Files:**
- Create: `src/sales_research_agent/ingestion/url_policy.py`
- Create: `src/sales_research_agent/ingestion/fetcher.py`
- Create: `src/sales_research_agent/ingestion/extractor.py`
- Create: `tests/fixtures/html/article.html`
- Create: `tests/unit/test_url_policy.py`
- Create: `tests/integration/test_html_ingestion.py`
- Create: `tests/fault_injection/test_network_failures.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: 写 URL 拒绝测试**

```python
@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a", "http://10.0.0.1/a"],
)
def test_url_policy_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)
```

- [ ] **Step 2: 运行 RED，随后实现 URL 策略**

Run: `uv run pytest tests/unit/test_url_policy.py -q`
Expected: FAIL。

实现仅允许 http/https，拒绝用户名密码、localhost 和 `ipaddress.ip_address(host)` 判定的非 global literal IP。域名解析后的每个地址也必须为 global；每次 redirect 都重新调用策略。

- [ ] **Step 3: 写摄取与局部失败测试**

```python
@pytest.mark.asyncio
async def test_ingestion_persists_raw_and_clean_artifacts(run_store) -> None:
    result = await run_store.ingestor.ingest("run-1", "src-1", "https://fixture.test/article")
    assert "可信段落" in run_store.artifacts.read_text(result.clean_ref)
    assert run_store.artifacts.read_bytes(result.raw_ref).startswith(b"<!doctype html>")


@pytest.mark.asyncio
async def test_one_404_returns_failure_instead_of_raising(run_store) -> None:
    result = await run_store.ingestor.ingest("run-1", "src-404", "https://fixture.test/missing")
    assert result.failure.code == "HTTP_404"
```

- [ ] **Step 4: 实现 Fetcher 与 Trafilatura Extractor**

Fetcher 构造函数注入 `httpx.AsyncClient` 与 `UrlPolicy`。测试中的 UrlPolicy 注入 resolver，把 `fixture.test` 解析为 global 地址 `93.184.216.34`，HTTP client 使用 `httpx.MockTransport`，生产代码不增加 `allow_test_host` 开关。`tests/conftest.py` 的 `run_store` fixture 组合临时 Artifact Store、SQLite Repository、MockTransport 和该 UrlPolicy。Fetcher 使用总重定向上限 5、连接/读取超时、8 MiB 响应上限和 HTML content-type allowlist。重试只覆盖 timeout、429 和 5xx，总尝试不超过 3。Extractor 调用 `trafilatura.extract(raw_html, url=final_url, output_format="txt", include_comments=False, include_tables=True)`；空文本返回 `EMPTY_CONTENT`。

- [ ] **Step 5: 运行测试并提交**

Run: `uv run pytest tests/unit/test_url_policy.py tests/integration/test_html_ingestion.py tests/fault_injection/test_network_failures.py -q`
Expected: PASS。

```powershell
git add src/sales_research_agent/ingestion tests
git commit -m "feat: add bounded html ingestion"
```

### Task 7: 实现 Evidence、Claim 与语义核验应用服务

**Files:**
- Create: `src/sales_research_agent/runtime.py`
- Modify: `tests/fakes.py`
- Create: `tests/integration/test_evidence_claim_pipeline.py`
- Create: `tests/fault_injection/test_model_failures.py`

- [ ] **Step 1: 写端到端领域链失败测试**

```python
@pytest.mark.asyncio
async def test_pipeline_only_approves_supported_located_fact(pipeline, repository) -> None:
    text = "2025 年公司发布年度报告。"
    block = DocumentBlock(
        id="block-1",
        run_id="run-1",
        source_revision_id="revision-1",
        ordinal=0,
        text=text,
        clean_start=0,
        clean_end=len(text),
    )
    await repository.upsert_document_block(block, operation_key="run-1:block:block-1")
    pipeline.model.queue_evidence(quote="2025年公司发布年度报告。", block_id=block.id)
    pipeline.model.queue_claim(kind="FACT", text="公司于2025年发布年度报告。")
    pipeline.model.queue_verification("SUPPORTED")
    result = await pipeline.run(block_ids=[block.id])
    assert len(result.approved_claim_ids) == 1


@pytest.mark.asyncio
async def test_pipeline_rejects_model_quote_not_present_in_source(pipeline) -> None:
    pipeline.model.queue_evidence(quote="2024 年收入增长 99%。", block_id="block-1")
    result = await pipeline.run(block_ids=["block-1"])
    assert result.approved_claim_ids == []
    assert result.gap_ids
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/integration/test_evidence_claim_pipeline.py -q`
Expected: FAIL，应用服务不存在。

- [ ] **Step 3: 实现 `ResearchPipeline`**

`tests/fakes.py` 为 `FakeResearchModel` 增加 `queue_evidence()`、`queue_claim()`、`queue_verification()`，并提供显式调用计数。`ResearchPipeline` 按以下固定顺序执行并逐步写 Repository：读取 DocumentBlock → 调模型提议 Evidence → 确定性定位与数字检查 → 保存 Evidence → 调模型生成 Claim → 对 Fact 调语义核验 → 保存 Verification → 调质量门禁 → 保存 Gap/批准状态。每次模型原始响应先经 secret redactor，再写 `model_responses/`。

- [ ] **Step 4: 增加模型失败收敛测试**

覆盖空响应后成功、连续两次 Schema 错误、核验 Provider 超时三种情况。连续失败产生结构化 Failure/Gap，不允许生成未经核验 Fact。

- [ ] **Step 5: 运行测试并提交**

Run: `uv run pytest tests/integration/test_evidence_claim_pipeline.py tests/fault_injection/test_model_failures.py -q`
Expected: PASS。

```powershell
git add src/sales_research_agent/runtime.py tests
git commit -m "feat: build evidence to claim pipeline"
```

### Task 8: 实现单一 ReportModel 与 Markdown/HTML 编译

**Files:**
- Create: `src/sales_research_agent/reporting/models.py`
- Create: `src/sales_research_agent/reporting/compiler.py`
- Create: `src/sales_research_agent/reporting/templates/report.html.j2`
- Create: `tests/unit/test_report_compiler.py`
- Create: `tests/integration/test_report_artifacts.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: 写同源一致性和 HTML 转义测试**

```python
def extract_ids(payload: str, kind: str) -> set[str]:
    return set(re.findall(rf'data-{kind}-id="([^"]+)"', payload))


def test_markdown_and_html_contain_same_claim_and_citation_ids(report_model) -> None:
    markdown = compile_markdown(report_model)
    html = compile_html(report_model)
    assert extract_ids(markdown, "claim") == extract_ids(html, "claim")
    assert extract_ids(markdown, "evidence") == extract_ids(html, "evidence")


def test_html_escapes_untrusted_source_text(malicious_report_model) -> None:
    html = compile_html(malicious_report_model)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/unit/test_report_compiler.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 ReportModel 和确定性编译器**

ReportModel 固定字段为声明、摘要、facts、recent_changes、inferences、questions、gaps、failures、sources、evidence_index、stats，并对 ReportModel 及其嵌套模型设置 `ConfigDict(frozen=True)`。编译器不调用模型，只排序、分组、编号、转义和渲染。`tests/conftest.py` 创建含一个批准 Fact、一个 Evidence 和一个 Source 的最小 `report_model` fixture，以及 Fact 文本为 `<script>alert(1)</script>` 的 `malicious_report_model` fixture；Markdown 与 HTML 均输出不可见或可见的 `data-claim-id`、`data-evidence-id` 标记供一致性检查。

- [ ] **Step 4: 实现原子报告发布**

先写 `report-model.json`、临时 Markdown 和临时 HTML；三者均成功后原子替换正式路径并创建 ReportVersion。新版本失败不能覆盖既有 active version。

- [ ] **Step 5: 运行测试并提交**

Run: `uv run pytest tests/unit/test_report_compiler.py tests/integration/test_report_artifacts.py -q`
Expected: PASS。

```powershell
git add src/sales_research_agent/reporting tests
git commit -m "feat: compile traceable dual format reports"
```

### Task 9: 组装 LangGraph、CLI、局部失败和恢复

**Files:**
- Create: `src/sales_research_agent/graph/nodes.py`
- Create: `src/sales_research_agent/graph/builder.py`
- Create: `src/sales_research_agent/cli.py`
- Create: `tests/integration/test_poc_graph.py`
- Create: `tests/fault_injection/test_graph_recovery.py`
- Create: `tests/unit/test_cli.py`
- Modify: `tests/fakes.py`
- Modify: `tests/conftest.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 写正常 Graph 路由测试**

```python
@pytest.mark.asyncio
async def test_graph_builds_report_from_approved_claims(poc_harness) -> None:
    result = await poc_harness.run()
    assert result["execution_status"] == "FINISHED"
    assert result["approved_claim_ids"]
    assert result["report_version_id"]
```

- [ ] **Step 2: 写 fan-out 局部失败测试**

```python
@pytest.mark.asyncio
async def test_one_source_failure_yields_partial_report(poc_harness) -> None:
    poc_harness.fetcher.fail_for("https://example.com/fail")
    result = await poc_harness.run()
    assert len(result["successful_source_ids"]) >= 1
    assert len(result["failed_source_ids"]) == 1
    assert result["report_outcome"] == "PARTIAL"


@pytest.mark.asyncio
async def test_source_fanout_respects_configured_concurrency(poc_harness) -> None:
    poc_harness.fetcher.track_concurrency()
    await poc_harness.run(max_concurrency=3)
    assert poc_harness.fetcher.peak_concurrency <= 3
```

- [ ] **Step 3: 运行 RED 并实现 Graph**

Run: `uv run pytest tests/integration/test_poc_graph.py -q`
Expected: FAIL。

Builder 使用 `StateGraph(PocState)`，顺序与规格一致。`discover_sources` 后的路由函数对每个来源准确返回：

```python
return [
    Send(
        "ingest_source",
        {
            "run_id": state["run_id"],
            "current_source_id": source_id,
            "deadline_at": state["deadline_at"],
        },
    )
    for source_id in state["source_ids"]
]
```

`ingest_source` 只读取这三个字段并返回父 State 已声明的 reducer 字段。来源列表 reducer 稳定去重；Graph 通过 closure 注入 `Services(repository, artifacts, search, model, fetcher, clock)`，不把 client 放进 State。`PocHarness.run(max_concurrency=3)` 和 CLI 都把 `RunnableConfig(configurable={"thread_id": run_id}, max_concurrency=settings.max_concurrency)` 传入 `ainvoke`，从运行时限制 fan-out 并发。`tests/fakes.py` 定义 `PocHarness`，负责创建临时 run 目录、Fake Providers、真实 SQLite Repository、真实 Artifact Store 和真实 Checkpointer；可追踪 Fetcher 记录活动请求数与峰值并发。`tests/conftest.py` 暴露 `poc_harness` 与 `crash_harness` fixture。创建 Checkpointer 前，runtime 根据 `Settings.langgraph_strict_msgpack` 设置 `LANGGRAPH_STRICT_MSGPACK=true`，并用测试确认 State 只包含允许的基础类型。

- [ ] **Step 4: 写并实现恢复测试**

```python
@pytest.mark.asyncio
async def test_resume_does_not_duplicate_completed_source_revision(crash_harness) -> None:
    with pytest.raises(InjectedCrash):
        await crash_harness.run()
    before = await crash_harness.repository.count_source_revisions()
    result = await crash_harness.resume()
    after = await crash_harness.repository.count_source_revisions()
    assert result["execution_status"] == "FINISHED"
    assert after == before + 1
    assert await crash_harness.repository.has_duplicate_operation_keys() is False
```

使用真实 `AsyncSqliteSaver`，在部分 ingest 分支成功后让一个分支抛出一次硬失败；同一 `thread_id` 以 `ainvoke(None, config)` 恢复，并检查 pending writes 与领域幂等。

- [ ] **Step 5: 实现 CLI 行为**

Typer 命令：

```text
sales-research run --case evals/cases/haier_first_meeting.json [--live]
sales-research resume --run-id RUN_ID_FROM_RUN_COMMAND
sales-research inspect --run-id RUN_ID_FROM_RUN_COMMAND
```

`run` 默认离线拒绝真实 Provider；`--live` 触发 Settings Key 校验。`resume` 不接收新的 Brief。`inspect` 只读取状态与安全统计，不输出 Key 和完整模型请求。

CLI 创建完成后，在 `pyproject.toml` 增加 `[project.scripts]`，注册 `sales-research = "sales_research_agent.cli:app"` 入口。

- [ ] **Step 6: 运行测试并提交**

Run: `uv run pytest tests/integration/test_poc_graph.py tests/fault_injection/test_graph_recovery.py tests/unit/test_cli.py -q`
Expected: PASS。

```powershell
git add src/sales_research_agent/graph src/sales_research_agent/cli.py tests
git commit -m "feat: orchestrate recoverable poc graph"
```

### Task 10: 建立固定案例、离线总回归与密钥泄漏门禁

**Files:**
- Create: `evals/cases/haier_first_meeting.json`
- Create: `tests/integration/test_offline_end_to_end.py`
- Create: `tests/unit/test_secret_redaction.py`
- Modify: `tests/fakes.py`
- Create: `docs/poc/live-run-review-template.md`
- Create: `docs/poc/decision-record-template.md`
- Modify: `README.md`

- [ ] **Step 1: 创建不含预置答案的案例**

```json
{
  "customer_name": "海尔智家",
  "scenario": "模拟首次客户技术交流",
  "known_context": "仅使用公开互联网信息；不代表客户存在任何模拟需求。",
  "research_goal": "形成客户公开背景、近期变化、需求假设和会议验证问题",
  "max_questions": 4,
  "max_sources": 6,
  "deadline_minutes": 30
}
```

- [ ] **Step 2: 写离线全链测试**

离线端到端使用固定 Provider fixture 和本地 HTML，断言产生 domain/checkpoint 两个数据库、raw/clean artifact、ReportModel、Markdown、HTML、统计，并验证报告只包含批准 Claim。

- [ ] **Step 3: 写密钥泄漏测试**

```python
@pytest.mark.asyncio
async def test_run_tree_does_not_contain_provider_keys(run_tree: Path, monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-secret-sentinel")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret-sentinel")
    await execute_offline_run(run_tree)
    payload = b"".join(path.read_bytes() for path in run_tree.rglob("*") if path.is_file())
    assert b"tavily-secret-sentinel" not in payload
    assert b"deepseek-secret-sentinel" not in payload
```

`tests/fakes.py` 的异步 `execute_offline_run(run_tree)` 使用 Task 9 的 PocHarness 执行完整 Fake Graph；`run_tree` fixture 指向该测试独立的临时目录。它不能读取开发机环境中的真实 Provider Key。

- [ ] **Step 4: 运行完整离线回归**

Run: `uv run pytest -m "not live" -q && uv run ruff check . && uv run mypy src`
Expected: 全部通过，零 warning/traceback。

- [ ] **Step 5: 扫描 Git 跟踪内容**

Run: `git status --short && git grep -n -E "tvly-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{16,}" -- ':!uv.lock'`
Expected: 第一条只显示本任务预期文件；第二条无输出。

- [ ] **Step 6: 提交**

```powershell
git add evals tests docs/poc README.md
git commit -m "test: add offline poc acceptance suite"
```

### Task 11: 执行真实海尔智家 POC 与人工事实审阅

**Files:**
- Create at runtime, ignored: `var/runs/{generated_run_id}/**`
- Create after review, using the actual execution date: `docs/poc/YYYY-MM-DD-haier-live-run-review.md`
- Create after review, using the actual execution date: `docs/poc/YYYY-MM-DD-poc-decision-record.md`
- Modify: `README.md`

- [ ] **Step 1: 先执行 Provider 冒烟测试**

从现有本地环境安全注入 `TAVILY_API_KEY` 与 `DEEPSEEK_API_KEY`，命令不得回显值。

Run: `uv run sales-research run --case evals/cases/haier_first_meeting.json --live`
Expected: 启动时输出 run_id；在 30 分钟内进入终态或输出可诊断的 Provider 决策失败。不得使用旧项目代码执行流程。

- [ ] **Step 2: 检查运行结构**

Run: `uv run sales-research inspect --run-id $RUN_ID`，其中 `$RUN_ID` 是 Step 1 命令输出后由执行者显式赋值的 PowerShell 变量。
Expected: 显示状态、耗时、搜索/HTTP/模型次数、来源成功失败数、Claim 决策数和报告路径，不显示密钥。

- [ ] **Step 3: 人工逐条审阅全部外部 Fact**

在 review 文档为每条 Fact 记录：Claim ID、报告文本、Source URL、Evidence quote、原文是否可定位、是否完整支持、关键数字是否一致、人工结论和备注。POC Fact 数量小，必须全量审阅，不抽样。

- [ ] **Step 4: 执行 live 后回归与泄漏扫描**

Run: `uv run pytest -m "not live" -q`
Expected: PASS。

Run: `git status --short`
Expected: `var/` 不出现；只出现准备提交的审阅文档与 README 更新。

Run: `git grep -n -E "tvly-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{16,}" -- ':!uv.lock'`
Expected: 无输出。

- [ ] **Step 5: 填写逐项决策记录**

对 Tavily、静态 HTML、DeepSeek 抽取、DeepSeek 核验、引用定位、LangGraph fan-out、SQLite Checkpointer、30 分钟预算和 HTML 报告分别给出 `KEEP/CHANGE/DEFER`，每项引用运行证据，不写笼统“POC 成功”。

- [ ] **Step 6: 更新 README 并提交 POC 证据**

README 只写实际运行日期、案例、终态、测试命令和可证明指标。未经通过的能力继续标为设计或待验证。

```powershell
git add docs/poc README.md
git commit -m "docs: record live poc findings"
```

- [ ] **Step 7: 密钥轮换提醒**

在交付说明中提醒用户轮换曾粘贴到对话中的 Tavily Key。轮换是用户账户操作，不由测试或应用代码自动执行。

## 2. 完成验收

全部任务完成后执行：

```powershell
uv lock --check
uv sync --locked
uv run pytest -m "not live" -q
uv run ruff check .
uv run mypy src
git status --short --branch
```

预期：锁文件未漂移；离线测试、Lint、类型检查全部通过；工作树只包含明确准备提交的 POC 结论文件或完全干净；`main` 不包含运行 Artifact 与密钥。

POC 是否通过，以设计规格第 19 节十项条件和第 20 节逐项决策门为准。即使某个 Provider 结论为 `CHANGE`，也要保留失败证据并提出下一候选，不得为了得到“成功”结论修改标准。

## 3. 技术基线依据

- LangGraph 持久化与 pending writes：[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- LangGraph SQLite Saver 及 strict msgpack 提示：[langgraph-checkpoint-sqlite](https://pypi.org/project/langgraph-checkpoint-sqlite/)
- LangGraph 测试建议：[Test](https://docs.langchain.com/oss/python/langgraph/test)
- Tavily Search API：[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- DeepSeek JSON Output：[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- Trafilatura Python 抽取：[Python usage](https://trafilatura.readthedocs.io/en/latest/usage-python.html)
- uv 锁定与同步：[Locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
