"""Provider 离线测试使用的显式队列 Fake。"""

from collections import deque
from dataclasses import dataclass
from typing import TypeVar

import httpx

from sales_research_agent.domain.models import Brief, DocumentBlock, Evidence, ResearchQuestion
from sales_research_agent.providers.base import (
    ClaimCandidate,
    ClaimSynthesis,
    EvidenceExtraction,
    ResearchModel,
    ResearchPlan,
    SearchProvider,
    SearchResult,
    SupportVerification,
)

QueueValue = TypeVar("QueueValue")

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

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        if not self._responses:
            raise AssertionError("FakeSearchProvider response queue is empty")
        return self._responses.popleft()


class FakeResearchModel(ResearchModel):
    """每项研究操作均由独立显式队列控制的模型 Fake。"""

    def __init__(self) -> None:
        self.plan_responses: deque[ResearchPlan] = deque()
        self.evidence_responses: deque[EvidenceExtraction] = deque()
        self.claim_responses: deque[ClaimSynthesis] = deque()
        self.verification_responses: deque[SupportVerification] = deque()
        self.plan_calls: list[Brief] = []
        self.evidence_calls: list[tuple[ResearchQuestion, list[DocumentBlock]]] = []
        self.claim_calls: list[tuple[Brief, list[Evidence]]] = []
        self.verification_calls: list[tuple[ClaimCandidate, list[Evidence]]] = []

    def queue_plan(self, response: ResearchPlan) -> None:
        self.plan_responses.append(response)

    def queue_evidence(self, response: EvidenceExtraction) -> None:
        self.evidence_responses.append(response)

    def queue_claims(self, response: ClaimSynthesis) -> None:
        self.claim_responses.append(response)

    def queue_verification(self, response: SupportVerification) -> None:
        self.verification_responses.append(response)

    async def plan(self, brief: Brief) -> ResearchPlan:
        self.plan_calls.append(brief)
        return self._pop(self.plan_responses, "plan")

    async def extract_evidence(
        self, question: ResearchQuestion, blocks: list[DocumentBlock]
    ) -> EvidenceExtraction:
        self.evidence_calls.append((question, blocks))
        return self._pop(self.evidence_responses, "extract_evidence")

    async def synthesize_claims(self, brief: Brief, evidence: list[Evidence]) -> ClaimSynthesis:
        self.claim_calls.append((brief, evidence))
        return self._pop(self.claim_responses, "synthesize_claims")

    async def verify_support(
        self, claim: ClaimCandidate, evidence: list[Evidence]
    ) -> SupportVerification:
        self.verification_calls.append((claim, evidence))
        return self._pop(self.verification_responses, "verify_support")

    @staticmethod
    def _pop(queue: deque[QueueValue], operation: str) -> QueueValue:
        if not queue:
            raise AssertionError(f"FakeResearchModel {operation} queue is empty")
        return queue.popleft()


class FakeFetcher:
    """摄取测试可用的显式响应队列，不模拟网络细节。"""

    def __init__(self, responses: list[object] | None = None) -> None:
        self._responses = deque(responses or [])
        self.calls: list[str] = []

    def queue_response(self, response: object) -> None:
        self._responses.append(response)

    async def fetch(self, url: str) -> object:
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("FakeFetcher response queue is empty")
        return self._responses.popleft()
