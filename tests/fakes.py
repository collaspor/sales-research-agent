"""Provider 离线测试使用的显式队列 Fake。"""

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import httpx
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from sales_research_agent.domain.models import (
    CURRENT_RUNTIME_VERSION,
    Brief,
    DocumentBlock,
    Evidence,
    ResearchQuestion,
    RunMetadata,
)
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository
from sales_research_agent.ingestion.fetcher import FetchFailure, FetchResult
from sales_research_agent.providers.base import (
    ClaimCandidate,
    ClaimSynthesis,
    EvidenceCandidate,
    EvidenceExtraction,
    PlannedQuestion,
    ResearchModel,
    ResearchPlan,
    SearchProvider,
    SearchResult,
    SupportVerification,
)

QueueValue = TypeVar("QueueValue")


class MemoryExternalCallRecorder:
    """在内存中保留 Provider 调用事件，供离线契约测试断言。"""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def start(
        self,
        *,
        provider: str,
        operation: str,
        attempt: int = 1,
        related_entity_id: str | None = None,
    ) -> str:
        call_id = str(uuid4())
        self.events.append(
            {
                "event_type": "CALL_STARTED",
                "call_id": call_id,
                "provider": provider,
                "operation": operation,
                "attempt": attempt,
                "related_entity_id": related_entity_id,
            }
        )
        return call_id

    async def finish(self, call_id: str, *, status: str) -> None:
        self.events.append(
            {"event_type": "CALL_FINISHED", "call_id": call_id, "status": status}
        )

    def started_count(self, provider: str) -> int:
        return sum(
            event.get("event_type") == "CALL_STARTED" and event.get("provider") == provider
            for event in self.events
        )

    def finished_statuses(self, provider: str) -> list[str]:
        call_ids = {
            event["call_id"]
            for event in self.events
            if event.get("event_type") == "CALL_STARTED" and event.get("provider") == provider
        }
        return [
            str(event["status"])
            for event in self.events
            if event.get("event_type") == "CALL_FINISHED" and event.get("call_id") in call_ids
        ]

@dataclass(frozen=True, slots=True)
class FakeChatResponse:
    """仅模拟模型响应中适配器需要读取的内容字段。"""

    content: str


class SequenceChatModel:
    """按入队顺序返回响应，并保留每次调用参数。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, input: object, **kwargs: object) -> FakeChatResponse:
        self.calls.append({"input": input, "kwargs": kwargs})
        if not self._responses:
            raise AssertionError("SequenceChatModel response queue is empty")
        return FakeChatResponse(content=self._responses.popleft())


class FixtureTransport(httpx.MockTransport):
    """按入队顺序返回 HTTP 响应，并保留所有请求。"""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = deque(responses)
        self.calls: list[httpx.Request] = []
        super().__init__(self._handle)

    def queue_response(self, response: httpx.Response) -> None:
        """向受控传输追加一个按顺序返回的响应。"""
        self._responses.append(response)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("FixtureTransport response queue is empty")
        return self._responses.popleft()


class FakeSearchProvider(SearchProvider):
    """由测试显式入队来源候选的搜索端口实现。"""

    def __init__(self, responses: list[list[SearchResult]] | None = None) -> None:
        self._responses = deque(responses or [])
        self.calls: list[tuple[str, int]] = []

    def queue_results(self, results: list[SearchResult]) -> None:
        self._responses.append(results)

    async def search(
        self,
        query: str,
        max_results: int,
        *,
        related_entity_id: str | None = None,
    ) -> list[SearchResult]:
        del related_entity_id
        self.calls.append((query, max_results))
        if not self._responses:
            raise AssertionError("FakeSearchProvider response queue is empty")
        return self._responses.popleft()


class FakeResearchModel(ResearchModel):
    """每项研究操作均由独立显式队列控制的模型 Fake。"""

    def __init__(self) -> None:
        self.plan_responses: deque[ResearchPlan] = deque()
        self.evidence_responses: deque[EvidenceExtraction | Exception] = deque()
        self.claim_responses: deque[ClaimSynthesis | Exception] = deque()
        self.verification_responses: deque[SupportVerification | Exception] = deque()
        self.plan_calls: list[Brief] = []
        self.evidence_calls: list[tuple[ResearchQuestion, list[DocumentBlock]]] = []
        self.claim_calls: list[tuple[Brief, list[Evidence]]] = []
        self.verification_calls: list[tuple[ClaimCandidate, list[Evidence]]] = []

    def queue_plan(self, response: ResearchPlan) -> None:
        self.plan_responses.append(response)

    def queue_evidence(self, response: EvidenceExtraction | Exception) -> None:
        self.evidence_responses.append(response)

    def queue_claims(self, response: ClaimSynthesis | Exception) -> None:
        self.claim_responses.append(response)

    def queue_verification(self, response: SupportVerification | Exception) -> None:
        self.verification_responses.append(response)

    def queue_claim(self, response: ClaimSynthesis | Exception) -> None:
        """兼容单数命名，便于管线测试表达单次综合。"""
        self.queue_claims(response)

    async def plan(self, brief: Brief) -> ResearchPlan:
        self.plan_calls.append(brief)
        return self._pop(self.plan_responses, "plan")

    async def extract_evidence(
        self, question: ResearchQuestion, blocks: list[DocumentBlock]
    ) -> EvidenceExtraction:
        self.evidence_calls.append((question, blocks))
        return self._pop_or_raise(self.evidence_responses, "extract_evidence")

    async def synthesize_claims(self, brief: Brief, evidence: list[Evidence]) -> ClaimSynthesis:
        self.claim_calls.append((brief, evidence))
        return self._pop_or_raise(self.claim_responses, "synthesize_claims")

    async def verify_support(
        self, claim: ClaimCandidate, evidence: list[Evidence]
    ) -> SupportVerification:
        self.verification_calls.append((claim, evidence))
        return self._pop_or_raise(self.verification_responses, "verify_support")

    @staticmethod
    def _pop(queue: deque[QueueValue], operation: str) -> QueueValue:
        if not queue:
            raise AssertionError(f"FakeResearchModel {operation} queue is empty")
        return queue.popleft()

    @classmethod
    def _pop_or_raise(cls, queue: deque[QueueValue | Exception], operation: str) -> QueueValue:
        response = cls._pop(queue, operation)
        if isinstance(response, Exception):
            raise response
        return response


class FakeFetcher:
    """摄取测试可用的显式响应队列，不模拟网络细节。"""

    def __init__(self, responses: list[object] | None = None) -> None:
        self._responses = deque(responses or [])
        self.calls: list[str] = []

    def queue_response(self, response: object) -> None:
        self._responses.append(response)

    async def fetch(self, url: str, *, related_entity_id: str | None = None) -> object:
        del related_entity_id
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("FakeFetcher response queue is empty")
        return self._responses.popleft()


class TrackedFetcher:
    """提供可控 HTML 响应，并记录 Graph fan-out 的实际并发度。"""

    def __init__(self, local_html: bytes) -> None:
        self._failed_urls: set[str] = set()
        self._local_html = local_html
        self.failure_source_callback: Callable[[str], None] | None = None
        self.calls: list[str] = []
        self.active = 0
        self.peak_concurrency = 0
        self._track_concurrency = False

    def fail_for(self, url: str) -> None:
        self._failed_urls.add(url)
        if self.failure_source_callback is not None:
            self.failure_source_callback(url)

    def track_concurrency(self) -> None:
        self._track_concurrency = True

    async def fetch(self, url: str, *, related_entity_id: str | None = None) -> FetchResult:
        del related_entity_id
        self.calls.append(url)
        self.active += 1
        self.peak_concurrency = max(self.peak_concurrency, self.active)
        try:
            if self._track_concurrency:
                await asyncio.sleep(0.01)
            if url in self._failed_urls:
                return FetchResult(
                    final_url=url,
                    failure=FetchFailure("FETCH_NETWORK_ERROR", False, "controlled failure"),
                )
            return FetchResult(
                final_url=url,
                status_code=200,
                body=self._local_html,
                content_type="text/html",
            )
        finally:
            self.active -= 1


@dataclass(frozen=True, slots=True)
class OfflineRun:
    """完整离线运行后的可审计测试句柄。"""

    run_id: str
    repository: SQLiteRepository
    artifacts: ArtifactStore
    state: dict[str, object]


class PocHarness:
    """以真实本地持久化设施运行离线 Graph 的测试夹具。"""

    def __init__(self, root: Path, *, crash_once: bool = False) -> None:
        self.root = root
        self.run_id = "run-poc"
        self.repository = SQLiteRepository(root / "domain.sqlite3")
        self.artifacts = ArtifactStore(root / "artifacts")
        self.search = FakeSearchProvider()
        self.model = FakeResearchModel()
        local_html = (Path(__file__).parent / "fixtures" / "html" / "article.html").read_bytes()
        self.fetcher = TrackedFetcher(local_html)
        self.fetcher.failure_source_callback = self._include_failure_source
        self.crash_once = crash_once
        self.brief = Brief(
            id="brief-poc", run_id=self.run_id, customer_name="Example Corp", scenario="presales",
            known_context="public only", research_goal="verify public facts",
        )
        self._saver_context = AsyncSqliteSaver.from_conn_string(str(root / "checkpoint.sqlite3"))
        self._saver: AsyncSqliteSaver | None = None

    async def initialize(self) -> None:
        await self.repository.initialize()
        now = datetime.now(UTC)
        await self.repository.save_run_metadata(
            RunMetadata(
                run_id=self.run_id,
                runtime_version=CURRENT_RUNTIME_VERSION,
                execution_status="RUNNING",
                report_outcome=None,
                started_at=now,
                finished_at=None,
            )
        )
        await self.repository.upsert_brief(self.brief, f"{self.run_id}:brief:{self.brief.id}")
        self._saver = await self._saver_context.__aenter__()
        self.search.queue_results(
            [
                SearchResult(url="https://example.com/ok", title="OK", snippet=""),
            ]
        )
        if self.crash_once:
            self._include_failure_source("https://example.com/fail")
        self.model.queue_plan(
            ResearchPlan(
                questions=[
                    PlannedQuestion(
                        text="When was the annual report published?",
                        purpose="verify public fact",
                        preferred_source_types=["WEB"],
                        completion_criteria="one approved fact",
                    )
                ]
            )
        )
        self.model.queue_evidence(
            EvidenceExtraction(
                candidates=[
                    EvidenceCandidate(
                        document_block_id="source-0-block-0",
                        quote="2025 year company published annual report.",
                        rationale="direct quote",
                    )
                ]
            )
        )
        self.model.queue_claims(
            ClaimSynthesis(
                claims=[
                    ClaimCandidate(
                        kind="FACT",
                        text="The company published an annual report in 2025.",
                        evidence_ids=["evidence-question-0-source-0-0"],
                        upstream_claim_ids=[],
                    ),
                    ClaimCandidate(
                        kind="FACT",
                        text="The company announced an unverified acquisition.",
                        evidence_ids=["evidence-question-0-source-0-0"],
                        upstream_claim_ids=[],
                    ),
                ]
            )
        )
        self.model.queue_verification(SupportVerification(decision="SUPPORTED", reason="direct"))
        self.model.queue_verification(
            SupportVerification(decision="UNSUPPORTED", reason="not stated")
        )

    def _include_failure_source(self, url: str) -> None:
        """仅在失败用例中向尚未消费的搜索结果追加第二个来源。"""
        if self.search._responses:
            self.search._responses[0].append(SearchResult(url=url, title="Fail", snippet=""))

    def configure_shared_source_questions(self) -> None:
        """配置两个研究问题共享同一来源的离线场景。"""
        self.search._responses.clear()
        self.model.plan_responses.clear()
        self.model.evidence_responses.clear()
        self.model.claim_responses.clear()
        self.model.verification_responses.clear()
        shared = SearchResult(url="https://example.com/shared", title="Shared", snippet="")
        self.search.queue_results([shared])
        self.search.queue_results([shared])
        self.model.queue_plan(
            ResearchPlan(
                questions=[
                    PlannedQuestion(
                        text="问题一",
                        purpose="核验事实一",
                        preferred_source_types=["WEB"],
                        completion_criteria="一条事实",
                    ),
                    PlannedQuestion(
                        text="问题二",
                        purpose="核验事实二",
                        preferred_source_types=["WEB"],
                        completion_criteria="一条事实",
                    ),
                ]
            )
        )
        for question_id in ("question-0", "question-1"):
            evidence_id = f"evidence-{question_id}-source-0-0"
            self.model.queue_evidence(
                EvidenceExtraction(
                    candidates=[
                        EvidenceCandidate(
                            document_block_id="source-0-block-0",
                            quote="2025 year company published annual report.",
                            rationale="direct quote",
                        )
                    ]
                )
            )
            self.model.queue_claims(
                ClaimSynthesis(
                    claims=[
                        ClaimCandidate(
                            kind="FACT",
                            text=f"{question_id} received a supported fact.",
                            evidence_ids=[evidence_id],
                            upstream_claim_ids=[],
                        )
                    ]
                )
            )
            self.model.queue_verification(
                SupportVerification(decision="SUPPORTED", reason="direct")
            )

    async def close(self) -> None:
        await self._saver_context.__aexit__(None, None, None)

    async def run(self, *, max_concurrency: int = 3) -> dict[str, object]:
        from sales_research_agent.graph.builder import Services, build_poc_graph

        assert self._saver is not None
        graph = build_poc_graph(
            Services(
                repository=self.repository,
                artifacts=self.artifacts,
                search=self.search,
                model=self.model,
                fetcher=self.fetcher,
                clock=lambda: datetime.now(UTC),
                max_sources=2,
                crash_once=self.crash_once,
            ),
            self._saver,
        )
        state = {
            "run_id": self.run_id,
            "thread_id": self.run_id,
            "brief_id": "brief-poc",
            "research_question_ids": [], "source_ids": [], "successful_source_ids": [],
            "failed_source_ids": [], "evidence_ids": [], "claim_ids": [],
            "approved_claim_ids": [], "rejected_claim_ids": [], "gap_ids": [], "failure_ids": [],
            "execution_status": "RUNNING", "started_at": datetime.now(UTC).isoformat(),
            "deadline_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        }
        effective_concurrency = 1 if self.crash_once else max_concurrency
        return await graph.ainvoke(
            state,
            {"configurable": {"thread_id": self.run_id}, "max_concurrency": effective_concurrency},
        )

    async def resume(self, *, max_concurrency: int = 3) -> dict[str, object]:
        from sales_research_agent.graph.builder import Services, build_poc_graph

        assert self._saver is not None
        graph = build_poc_graph(
            Services(
                repository=self.repository, artifacts=self.artifacts, search=self.search,
                model=self.model, fetcher=self.fetcher, clock=lambda: datetime.now(UTC),
                max_sources=2, crash_once=False,
            ), self._saver,
        )
        return await graph.ainvoke(
            None, {"configurable": {"thread_id": self.run_id}, "max_concurrency": max_concurrency}
        )


async def execute_offline_run(run_tree: Path) -> OfflineRun:
    """以 Fake Provider 和本地 HTML 执行完整 POC，不读取环境密钥。"""
    harness = PocHarness(run_tree)
    await harness.initialize()
    try:
        state = await harness.run()
        return OfflineRun(
            run_id=harness.run_id,
            repository=harness.repository,
            artifacts=harness.artifacts,
            state=state,
        )
    finally:
        await harness.close()
