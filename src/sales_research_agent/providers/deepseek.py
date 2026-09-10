"""DeepSeek OpenAI-compatible 结构化研究模型适配器。"""

from typing import Any, Protocol, TypeVar, cast

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr, ValidationError

from sales_research_agent.config import Settings
from sales_research_agent.domain.models import Brief, DocumentBlock, Evidence, ResearchQuestion
from sales_research_agent.providers.base import (
    ClaimCandidate,
    ClaimSynthesis,
    EvidenceExtraction,
    ProviderCallStats,
    ResearchModel,
    ResearchPlan,
    SupportVerification,
)
from sales_research_agent.providers.tavily import ProviderConfigurationError, ProviderPermanentError

ModelOutput = TypeVar("ModelOutput", bound=BaseModel)


class AsyncChatClient(Protocol):
    """适配器所需的最小异步聊天客户端能力。"""

    async def ainvoke(self, input: object, **kwargs: object) -> object:
        """返回含 content 属性的响应对象。"""


class ProviderSchemaError(ProviderPermanentError):
    """模型在一次格式修正后仍未给出可验证 JSON。"""


class DeepSeekProvider(ResearchModel):
    """以 JSON object 模式调用 DeepSeek，并限制格式修正次数。"""

    def __init__(self, *, client: AsyncChatClient | None = None, settings: Settings | None = None) -> None:
        if client is None:
            resolved_settings = settings or Settings()
            if not resolved_settings.deepseek_api_key:
                raise ProviderConfigurationError("deepseek API key is not configured")
            client = cast(
                AsyncChatClient,
                ChatOpenAI(
                    model=resolved_settings.deepseek_model,
                    base_url=resolved_settings.deepseek_base_url,
                    api_key=SecretStr(resolved_settings.deepseek_api_key),
                ),
            )
        self._client = client
        self.call_count = 0
        self.call_stats = ProviderCallStats()

    async def plan(self, brief: Brief) -> ResearchPlan:
        """生成最多四条、可由后续节点持久化的问题计划。"""
        return await self._request_structured("plan", brief.model_dump(mode="json"), ResearchPlan)

    async def extract_evidence(
        self, question: ResearchQuestion, blocks: list[DocumentBlock]
    ) -> EvidenceExtraction:
        """从指定正文块提出尚未验证的引文候选。"""
        payload = {
            "question": question.model_dump(mode="json"),
            "blocks": [block.model_dump(mode="json") for block in blocks],
        }
        return await self._request_structured("extract_evidence", payload, EvidenceExtraction)

    async def synthesize_claims(self, brief: Brief, evidence: list[Evidence]) -> ClaimSynthesis:
        """仅基于已定位 Evidence 提出 Claim 候选。"""
        payload = {
            "brief": brief.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return await self._request_structured("synthesize_claims", payload, ClaimSynthesis)

    async def verify_support(
        self, claim: ClaimCandidate, evidence: list[Evidence]
    ) -> SupportVerification:
        """在隔离输入中输出单条 Claim 的语义支持判断。"""
        payload = {
            "claim": claim.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return await self._request_structured("verify_support", payload, SupportVerification)

    async def _request_structured(
        self, operation: str, payload: dict[str, Any], output_type: type[ModelOutput]
    ) -> ModelOutput:
        system_message = self._system_message(operation, output_type)
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": str(payload)},
        ]
        for attempt in range(2):
            self.call_count += 1
            self.call_stats = self.call_stats.model_copy(update={"model_calls": self.call_count})
            response = await self._client.ainvoke(
                messages,
                response_format={"type": "json_object"},
            )
            content = getattr(response, "content", None)
            if isinstance(content, str) and content.strip():
                try:
                    return output_type.model_validate_json(content)
                except ValidationError:
                    pass
            if attempt == 0:
                self.call_stats = self.call_stats.model_copy(
                    update={"schema_retries": self.call_stats.schema_retries + 1}
                )
        self.call_stats = self.call_stats.model_copy(
            update={"failed_calls": self.call_stats.failed_calls + 1}
        )
        raise ProviderSchemaError("deepseek returned invalid structured output")

    @staticmethod
    def _system_message(operation: str, output_type: type[BaseModel]) -> str:
        schema = output_type.model_json_schema()
        example = output_type.model_construct().model_dump(mode="json")
        return (
            "Return only a JSON object that matches the required schema. "
            f"Operation: {operation}. Schema: {schema}. Example shape: {example}."
        )
