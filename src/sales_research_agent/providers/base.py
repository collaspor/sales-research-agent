"""Provider 对 Graph 暴露的稳定数据契约。"""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sales_research_agent.domain.models import Brief, DocumentBlock, Evidence, ResearchQuestion


class ProviderModel(BaseModel):
    """Provider 边界上的结构化数据不接受未声明字段。"""

    model_config = ConfigDict(extra="forbid")


class SearchResult(ProviderModel):
    """搜索 Provider 发现的来源候选，而非可引用证据。"""

    url: str
    title: str
    snippet: str
    score: float | None = None
    snippet_is_evidence: bool = False


class PlannedQuestion(ProviderModel):
    """研究计划中的单个待回答问题。"""

    text: str
    purpose: str
    preferred_source_types: list[str]
    completion_criteria: str


class ResearchPlan(ProviderModel):
    """有硬上限的研究问题计划。"""

    questions: list[PlannedQuestion] = Field(max_length=4)


class EvidenceCandidate(ProviderModel):
    """模型提议、尚未经过确定性定位的证据候选。"""

    document_block_id: str
    quote: str
    rationale: str


class EvidenceExtraction(ProviderModel):
    """证据提取操作的结构化结果。"""

    candidates: list[EvidenceCandidate]


class ClaimCandidate(ProviderModel):
    """模型提议、尚未通过质量门禁的 Claim。"""

    kind: Literal["FACT", "INFERENCE", "QUESTION"]
    text: str
    evidence_ids: list[str]
    upstream_claim_ids: list[str]


class ClaimSynthesis(ProviderModel):
    """Claim 综合操作的结构化结果。"""

    claims: list[ClaimCandidate]


class SupportVerification(ProviderModel):
    """单条 Claim 的语义支持判断。"""

    decision: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
    reason: str


class ProviderCallStats(ProviderModel):
    """不含请求内容与密钥的调用统计。"""

    model_calls: int = 0
    schema_retries: int = 0
    failed_calls: int = 0


class SearchProvider(ABC):
    """公开搜索的异步端口。"""

    @abstractmethod
    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """返回来源候选；摘要绝不能被当作 Evidence。"""


class ResearchModel(ABC):
    """研究链路所需的结构化模型能力。"""

    @abstractmethod
    async def plan(self, brief: Brief) -> ResearchPlan:
        """根据 Brief 生成有上限的研究问题。"""

    @abstractmethod
    async def extract_evidence(
        self, question: ResearchQuestion, blocks: list[DocumentBlock]
    ) -> EvidenceExtraction:
        """针对正文块提出尚未验证的证据候选。"""

    @abstractmethod
    async def synthesize_claims(self, brief: Brief, evidence: list[Evidence]) -> ClaimSynthesis:
        """从已定位证据提出尚未审批的 Claim 候选。"""

    @abstractmethod
    async def verify_support(
        self, claim: ClaimCandidate, evidence: list[Evidence]
    ) -> SupportVerification:
        """独立判断证据是否支持一条 Claim。"""
