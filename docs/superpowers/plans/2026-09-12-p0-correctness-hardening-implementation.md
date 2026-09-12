# P0 Correctness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复并行实体覆盖、多问题来源漏处理、真实调用统计失真和 CLI 测试读取本地 `.env` 四类 P0 问题，同时保持本地 CLI MVP 的现有边界。

**Architecture:** 保留当前 LangGraph、SQLite Repository 和 Provider 分层；领域实体改用 Source—Question 作用域的确定性 ID，来源正文摄取一次后逐关联问题执行研究管线。新增窄的外部调用 recorder，以 SQLite 追加审计事件作为统计权威来源，并使用独立运行元数据阻止旧 checkpoint 被新版恢复。

**Tech Stack:** Python 3.11、LangGraph、Pydantic v2、aiosqlite、httpx、Typer、pytest、Ruff、Mypy

---

## 文件结构

- 新建 `src/sales_research_agent/infrastructure/telemetry.py`：两阶段调用事件 recorder 和聚合逻辑。
- 修改 `domain/models.py`、`domain/repository.py`、`sqlite_repository.py`：运行元数据、RunStats 扩展和审计事件读取。
- 修改 `runtime.py`：Source—Question 作用域 ID、Failure/Gap 作用域和模型制品路径。
- 修改 `graph/nodes.py`：多问题执行、终态规则和持久化统计。
- 修改 `cli.py`：运行版本、旧恢复拒绝、扩展 inspect、recorder 注入。
- 修改 `deepseek.py`、`tavily.py`、`mineru.py`、`fetcher.py`：真实请求边界遥测。
- 修改 `tests/fakes.py` 及相关单元、集成、故障注入测试：提供 RED/GREEN 验证。
- 修改 `README.md`、`docs/mvp-acceptance-checklist.md`：只同步本轮可证明结果。

### Task 1: 建立运行元数据和两阶段遥测存储

**Files:**
- Create: `src/sales_research_agent/infrastructure/telemetry.py`
- Modify: `src/sales_research_agent/domain/models.py`
- Modify: `src/sales_research_agent/domain/repository.py`
- Modify: `src/sales_research_agent/infrastructure/sqlite_repository.py`
- Test: `tests/integration/test_sqlite_repository.py`
- Create: `tests/unit/test_telemetry.py`

- [ ] **Step 1: 写运行元数据和审计事件读取失败测试**

新增测试，要求 `RunMetadata(runtime_version=2)` 可保存读取，且 `list_audit_events(run_id)` 按插入顺序返回 JSON 对象。

```python
metadata = RunMetadata(
    run_id="run-1",
    runtime_version=2,
    execution_status="RUNNING",
    report_outcome=None,
    started_at=datetime.now(UTC),
    finished_at=None,
)
await repository.save_run_metadata(metadata)
assert await repository.get_run_metadata("run-1") == metadata
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_sqlite_repository.py tests/unit/test_telemetry.py -q`

Expected: 因 `RunMetadata`、`ExternalCallRecorder` 和 Repository 方法不存在而失败。

- [ ] **Step 3: 实现严格模型与 Repository 窄接口**

`RunMetadata` 固定运行版本与状态；`RunStats` 增加 `pdf_calls`。Repository 增加：

```python
async def save_run_metadata(self, metadata: RunMetadata) -> None: ...
async def get_run_metadata(self, run_id: str) -> RunMetadata | None: ...
async def list_audit_events(self, run_id: str) -> list[dict[str, object]]: ...
```

SQLite 初始化增加单行 `run_metadata` 表；旧数据库初始化后该表为空，因此自然识别为版本 1。

- [ ] **Step 4: 实现 recorder 和聚合器**

`ExternalCallRecorder.start()` 生成 `call_id` 并写入 `CALL_STARTED`；`finish()` 写入配对的 `CALL_FINISHED`。`summarize_external_calls()` 按 started 的不同 call_id 统计 Provider 请求，并返回 interrupted 数。

```python
call_id = await recorder.start(provider="deepseek", operation="plan")
await recorder.finish(call_id, status="SUCCESS", duration_ms=12)
summary = summarize_external_calls(await repository.list_audit_events("run-1"))
assert summary.model_calls == 1
```

- [ ] **Step 5: 运行针对性测试确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_sqlite_repository.py tests/unit/test_telemetry.py -q`

Expected: 全部通过。

- [ ] **Step 6: 提交基础设施改动**

```powershell
git add src/sales_research_agent/domain src/sales_research_agent/infrastructure tests/integration/test_sqlite_repository.py tests/unit/test_telemetry.py
git commit -m "feat: persist run metadata and call telemetry"
```

### Task 2: 隔离并行研究实体和模型制品

**Files:**
- Modify: `src/sales_research_agent/runtime.py`
- Modify: `tests/integration/test_evidence_claim_pipeline.py`
- Modify: `tests/fault_injection/test_model_failures.py`
- Create: `tests/integration/test_parallel_entity_identity.py`

- [ ] **Step 1: 写并行身份冲突回归测试**

使用同一 Repository 创建两个 `ResearchPipeline`，分别传入 `question-0/source-0` 和 `question-1/source-1`。两个模型都只返回局部候选 0，断言最终存在两个 Claim、两个 Verification，ID 和 Evidence 血缘互不相同。

```python
assert {claim.id for claim in claims} == {
    "claim-question-0-source-0-0",
    "claim-question-1-source-1-0",
}
assert len(await repository.list_verifications("run-1")) == 2
```

再断言模型制品分别位于两个作用域目录。

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_parallel_entity_identity.py -q`

Expected: 当前 `claim-0` 和固定模型响应路径发生覆盖，断言失败。

- [ ] **Step 3: 给 ResearchPipeline 增加 source_id 作用域**

构造器增加 `source_id: str`。Evidence、Claim、Verification、Gap、Failure 依照设计规格生成确定性 ID；operation key 直接包含完整实体 ID。

```python
claim_id = f"claim-{self._question.id}-{self._source_id}-{index}"
evidence_id = f"evidence-{self._question.id}-{self._source_id}-{index}"
```

模型响应路径改为：

```python
base = f"model_responses/{self._question.id}/{self._source_id}"
path = f"{base}/{operation}-{object_id}-attempt-{attempt}.json"
```

- [ ] **Step 4: 更新现有管线测试的期望 ID**

所有直接构造 `ResearchPipeline` 的测试显式传入 `source_id`，Fake ClaimCandidate 引用新的 Evidence ID。不得降低原有定位、数字和语义门禁断言。

- [ ] **Step 5: 运行相关测试确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_parallel_entity_identity.py tests/integration/test_evidence_claim_pipeline.py tests/fault_injection/test_model_failures.py -q`

Expected: 全部通过。

- [ ] **Step 6: 提交身份隔离改动**

```powershell
git add src/sales_research_agent/runtime.py tests/integration/test_parallel_entity_identity.py tests/integration/test_evidence_claim_pipeline.py tests/fault_injection/test_model_failures.py
git commit -m "fix: isolate parallel research entity identities"
```

### Task 3: 覆盖来源关联的全部研究问题

**Files:**
- Modify: `src/sales_research_agent/graph/nodes.py`
- Modify: `tests/fakes.py`
- Modify: `tests/integration/test_poc_graph.py`
- Modify: `tests/fault_injection/test_graph_recovery.py`

- [ ] **Step 1: 写共享来源多问题失败测试**

配置两个研究问题都搜索到相同 URL，为两个问题分别排队 Evidence、Claim 和 Verification。断言 Fetcher 只调用一次，模型 Evidence 提取调用两次，两个问题各自留下批准 Claim。

```python
assert poc_harness.fetcher.calls == ["https://example.com/shared"]
assert [call[0].id for call in poc_harness.model.evidence_calls] == ["question-0", "question-1"]
assert len(await poc_harness.repository.list_claims(poc_harness.run_id)) == 2
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_poc_graph.py::test_shared_source_researches_every_linked_question -q`

Expected: 当前只处理 `discovered_by_question_ids[0]`，第二个问题没有模型调用。

- [ ] **Step 3: 最小修改 ingest_source 节点**

正文块只创建一次，随后按 `source.discovered_by_question_ids` 稳定顺序逐个加载问题并执行带 `source_id` 的 ResearchPipeline。合并所有 PipelineResult 列表后一次返回 LangGraph 分支更新。

- [ ] **Step 4: 增加恢复与失败隔离断言**

扩展故障注入测试，确保已完成来源不会重复摄取；若恢复后确实重跑某个未完成关联，领域实体仍按确定性 ID 去重。

- [ ] **Step 5: 运行 Graph 测试确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_poc_graph.py tests/fault_injection/test_graph_recovery.py -q`

Expected: 全部通过，正文摄取次数仍按 Source 计数。

- [ ] **Step 6: 提交多问题覆盖改动**

```powershell
git add src/sales_research_agent/graph/nodes.py tests/fakes.py tests/integration/test_poc_graph.py tests/fault_injection/test_graph_recovery.py
git commit -m "fix: research every question linked to a source"
```

### Task 4: 在真实外部请求边界记录遥测

**Files:**
- Modify: `src/sales_research_agent/providers/deepseek.py`
- Modify: `src/sales_research_agent/providers/tavily.py`
- Modify: `src/sales_research_agent/providers/mineru.py`
- Modify: `src/sales_research_agent/ingestion/fetcher.py`
- Modify: `tests/unit/test_deepseek_provider.py`
- Modify: `tests/unit/test_tavily_provider.py`
- Modify: `tests/unit/test_mineru_provider.py`
- Modify: `tests/unit/test_telemetry.py`
- Modify: `tests/unit/test_url_policy.py`

- [ ] **Step 1: 为四类请求写 recorder 契约测试**

向 Provider/Fetcher 注入内存 recorder，覆盖成功、重试和超时。每次 `client` 请求对应一个 started/finished 配对；三次重试必须记录三次调用。

```python
assert recorder.started_count(provider="tavily") == 3
assert recorder.finished_statuses(provider="tavily") == ["HTTP_503", "HTTP_503", "SUCCESS"]
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_deepseek_provider.py tests/unit/test_tavily_provider.py tests/unit/test_mineru_provider.py tests/unit/test_web.py tests/unit/test_telemetry.py -q`

Expected: 构造器尚不接受 recorder 或没有事件，新增断言失败。

- [ ] **Step 3: 给适配器注入可选 recorder**

四个适配器构造器接受 `recorder: ExternalCallRecorder | None = None`，默认使用 no-op recorder，保证现有调用者兼容。每次实际网络请求紧邻 I/O 写 started，并在所有成功和异常分支写 finished；不得记录请求正文和鉴权头。

- [ ] **Step 4: 运行 Provider 测试确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_deepseek_provider.py tests/unit/test_tavily_provider.py tests/unit/test_mineru_provider.py tests/fault_injection/test_network_failures.py tests/unit/test_telemetry.py -q`

Expected: 全部通过，原有 retry 和脱敏断言保持有效。

- [ ] **Step 5: 提交请求遥测改动**

```powershell
git add src/sales_research_agent/providers src/sales_research_agent/ingestion/fetcher.py tests/unit/test_deepseek_provider.py tests/unit/test_tavily_provider.py tests/unit/test_mineru_provider.py tests/fault_injection/test_network_failures.py tests/unit/test_telemetry.py
git commit -m "feat: record persistent external call telemetry"
```

### Task 5: 装配运行版本、统计和扩展 inspect

**Files:**
- Modify: `src/sales_research_agent/cli.py`
- Modify: `src/sales_research_agent/graph/nodes.py`
- Modify: `tests/fakes.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/unit/test_graph_nodes.py`
- Modify: `tests/integration/test_offline_end_to_end.py`

- [ ] **Step 1: 写 inspect 和旧版本恢复失败测试**

新运行必须保存版本 2 元数据。缺少元数据的旧运行调用 resume 时，在构建 Provider 前失败；inspect 对旧运行返回 `runtime_version: 1`。新运行 inspect 返回终态、耗时、四类调用数及来源/Claim 统计。

```python
summary = await _inspect_run(run_directory, "run-1")
assert summary["runtime_version"] == 2
assert summary["model_calls"] == 1
assert summary["duration_seconds"] >= 0
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_cli.py tests/unit/test_graph_nodes.py tests/integration/test_offline_end_to_end.py -q`

Expected: 新字段、版本检查和持久化聚合尚不存在而失败。

- [ ] **Step 3: 在 CLI 装配 recorder 与运行元数据**

创建运行时先保存 RUNNING/version 2 元数据，再构造一个 Repository recorder 并注入 Tavily、DeepSeek、MinerU 和 Fetcher。resume 在实例化任何真实 Provider 前读取元数据并拒绝版本 1。

- [ ] **Step 4: 在发布节点聚合 RunStats 和终态**

从审计事件聚合外部调用数。没有批准 Fact 为 `FAILED`；存在失败来源或没有批准 Fact 覆盖的研究问题为 `PARTIAL`；其余为 `COMPLETED`。同时更新 `RunMetadata(execution_status="FINISHED")`。

- [ ] **Step 5: 扩展 inspect 且保持旧字段**

inspect 输出设计规格中的 JSON 字段；运行未结束时以当前 UTC 计算 duration，started 无 finished 的调用计入对应 calls 并额外披露 interrupted 数。

- [ ] **Step 6: 运行相关测试确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_cli.py tests/unit/test_graph_nodes.py tests/integration/test_offline_end_to_end.py -q`

Expected: 全部通过。

- [ ] **Step 7: 提交装配和 inspect 改动**

```powershell
git add src/sales_research_agent/cli.py src/sales_research_agent/graph/nodes.py tests/fakes.py tests/unit/test_cli.py tests/unit/test_graph_nodes.py tests/integration/test_offline_end_to_end.py
git commit -m "feat: expose trustworthy run inspection"
```

### Task 6: 隔离 CLI `.env` 并完成全量验收

**Files:**
- Modify: `tests/unit/test_cli.py`
- Modify: `README.md`
- Modify: `docs/mvp-acceptance-checklist.md`

- [ ] **Step 1: 固化 `.env` 污染回归测试**

测试创建一个包含假密钥的项目目录，再把 CLI 运行切换到不含 `.env` 的临时目录，显式删除环境变量，断言 live 模式在网络调用前报告缺少密钥。断言只检查稳定错误文本，不依赖 Rich 边框。

- [ ] **Step 2: 运行单测确认问题已被测试隔离**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_cli.py -q`

Expected: 全部通过，测试不读取真实 `.env`。

- [ ] **Step 3: 运行全量离线验证**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
```

Expected: pytest 0 failed、Ruff 0 errors、Mypy 0 issues。

- [ ] **Step 4: 更新可证明文档**

README 和 MVP 验收清单只写入本次命令的实际测试数量、运行版本、inspect 字段和未执行真实公网验收的说明。历史 POC 文档保留原结论。

- [ ] **Step 5: 检查中文编码与工作区边界**

Run: `rg -n "�" src tests docs README.md`

Expected: 本轮修改文件无替换字符；已有无关文件不进入 staged diff。

- [ ] **Step 6: 提交测试和文档**

```powershell
git add tests/unit/test_cli.py README.md docs/mvp-acceptance-checklist.md docs/superpowers/plans/2026-09-12-p0-correctness-hardening-implementation.md
git commit -m "docs: record P0 hardening verification"
```

- [ ] **Step 7: 最终验收审计**

Run: `git status --short --branch; git log -6 --oneline; git diff HEAD~5..HEAD --check`

Expected: 只剩用户原有两个未跟踪文件；提交历史按改造包拆分；diff 无空白错误。
