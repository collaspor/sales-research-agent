"""MinerU 远程 PDF 解析适配器。"""

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from sales_research_agent.providers.base import ParsedPdf, PdfParser

MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=15.0)


class MinerUError(Exception):
    """MinerU 解析失败的脱敏基类。"""


class MinerUConfigurationError(MinerUError):
    """MinerU 凭证或请求配置无效。"""


class MinerURetriableError(MinerUError):
    """可通过有限重试恢复的 MinerU 故障。"""


class _SubmitData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str


class _SubmitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: int
    data: _SubmitData


class _StatusData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    state: str
    markdown_url: str | None = None
    err_msg: str | None = None


class _StatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: int
    data: _StatusData


class MinerUPdfParser(PdfParser):
    """通过 MinerU 异步 URL 解析接口获取 Markdown。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://mineru.net/api/v4",
        poll_interval: float = 0.0,
        poll_timeout: float = 300.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise MinerUConfigurationError("MINERU_API_KEY is required for PDF parsing")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._owns_client = client is None
        self.call_count = 0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def parse(self, pdf_bytes: bytes, source_url: str) -> ParsedPdf:
        """提交来源 URL；bytes 由上层保留为本地原始制品。"""
        del pdf_bytes
        submit = await self._request_json(
            "POST", f"{self._base_url}/extract/task", {"url": source_url, "model_version": "vlm"}
        )
        try:
            task = _SubmitResponse.model_validate(submit)
        except ValidationError as error:
            raise MinerUError("mineru returned an invalid submit response") from error
        if task.code != 0:
            raise MinerUError("mineru rejected the parse task")
        task_id = task.data.task_id
        deadline = asyncio.get_running_loop().time() + self._poll_timeout
        while True:
            status_payload = await self._request_json("GET", f"{self._base_url}/extract/task/{task_id}")
            try:
                status = _StatusResponse.model_validate(status_payload)
            except ValidationError as error:
                raise MinerUError("mineru returned an invalid task response") from error
            if status.code != 0 or status.data.state == "failed":
                raise MinerUError("mineru failed to parse the PDF")
            if status.data.state == "done" and status.data.markdown_url:
                response = await self._request("GET", status.data.markdown_url)
                return ParsedPdf(task_id=task_id, text=response.text)
            if asyncio.get_running_loop().time() >= deadline:
                raise MinerURetriableError("mineru parsing timed out")
            await asyncio.sleep(self._poll_interval)

    async def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
        return (await self._request(method, url, payload)).json()

    async def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.call_count += 1
            try:
                response = await self._client.request(
                    method, url, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                )
            except httpx.TimeoutException as error:
                if attempt == MAX_ATTEMPTS:
                    raise MinerURetriableError("mineru request timed out") from error
                continue
            except httpx.RequestError as error:
                if attempt == MAX_ATTEMPTS:
                    raise MinerURetriableError("mineru request failed") from error
                continue
            if response.status_code in {401, 403}:
                raise MinerUConfigurationError("mineru rejected provider configuration")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == MAX_ATTEMPTS:
                    raise MinerURetriableError("mineru service is temporarily unavailable")
                continue
            if response.status_code >= 400:
                raise MinerUError("mineru rejected the request")
            return response
        raise MinerURetriableError("mineru request failed")
