"""Tavily 搜索 Provider 适配器。"""

import asyncio

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from sales_research_agent.infrastructure.telemetry import (
    ExternalCallRecorder,
    NullExternalCallRecorder,
)
from sales_research_agent.providers.base import SearchProvider, SearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_ATTEMPTS = 3
TAVILY_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=15.0)


class ProviderError(Exception):
    """不会包含上游响应、请求头或密钥的 Provider 基础错误。"""


class ProviderConfigurationError(ProviderError):
    """Provider 凭据或配置被远端拒绝。"""


class ProviderRetriableError(ProviderError):
    """调用可在受控重试预算内再次尝试。"""


class ProviderPermanentError(ProviderError):
    """请求本身不可通过重试修复。"""


class _TavilyResult(BaseModel):
    """仅接收 POC 所需的 Tavily 响应字段。"""

    model_config = ConfigDict(extra="ignore")

    title: str
    url: str
    content: str = ""
    score: float | None = None


class _TavilyPayload(BaseModel):
    """Tavily 响应的最小脱敏解析模型。"""

    model_config = ConfigDict(extra="ignore")

    results: list[_TavilyResult]


class TavilySearchProvider(SearchProvider):
    """将 Tavily 搜索结果转换为不可直接引用的来源候选。"""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        recorder: ExternalCallRecorder | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("provide either client or transport, not both")
        self._client = client or httpx.AsyncClient(transport=transport, timeout=TAVILY_TIMEOUT)
        self._owns_client = client is None
        self._api_key = api_key
        self._recorder = recorder or NullExternalCallRecorder()
        self.call_count = 0

    async def aclose(self) -> None:
        """仅关闭由适配器创建的 HTTP client。"""
        if self._owns_client:
            await self._client.aclose()

    async def search(
        self,
        query: str,
        max_results: int,
        *,
        related_entity_id: str | None = None,
    ) -> list[SearchResult]:
        """在三次尝试预算内查询 Tavily 并转换为候选来源。"""
        payload = {
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.call_count += 1
            call_id = await self._recorder.start(
                provider="tavily",
                operation="search",
                attempt=attempt,
                related_entity_id=related_entity_id,
            )
            try:
                response = await self._client.post(
                    TAVILY_SEARCH_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                self._raise_for_status(response.status_code)
            except httpx.TimeoutException as error:
                await self._recorder.finish(call_id, status="TIMEOUT")
                if attempt == MAX_ATTEMPTS:
                    raise ProviderRetriableError("tavily request timed out") from error
            except httpx.RequestError as error:
                await self._recorder.finish(call_id, status="NETWORK_ERROR")
                if attempt == MAX_ATTEMPTS:
                    raise ProviderRetriableError("tavily request failed") from error
            except ProviderRetriableError:
                await self._recorder.finish(call_id, status=f"HTTP_{response.status_code}")
                if attempt == MAX_ATTEMPTS:
                    raise
            except ProviderError:
                await self._recorder.finish(call_id, status=f"HTTP_{response.status_code}")
                raise
            else:
                try:
                    parsed = _TavilyPayload.model_validate(response.json())
                except (ValidationError, ValueError) as error:
                    await self._recorder.finish(call_id, status="SCHEMA_ERROR")
                    raise ProviderPermanentError("tavily returned an invalid response") from error
                await self._recorder.finish(call_id, status="SUCCESS")
                return [
                    SearchResult(
                        url=result.url,
                        title=result.title,
                        snippet=result.content,
                        score=result.score,
                        snippet_is_evidence=False,
                    )
                    for result in parsed.results
                ]
            await asyncio.sleep(0)
        raise RuntimeError("tavily retry loop did not complete")

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code in {401, 403}:
            raise ProviderConfigurationError("tavily rejected provider configuration")
        if status_code == 429 or status_code >= 500:
            raise ProviderRetriableError("tavily service is temporarily unavailable")
        if 400 <= status_code < 500:
            raise ProviderPermanentError("tavily rejected the request")
