"""MinerU 远程 PDF 解析适配器。"""

import asyncio
import io
import zipfile
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from sales_research_agent.infrastructure.telemetry import (
    ExternalCallRecorder,
    NullExternalCallRecorder,
)
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
    full_zip_url: str | None = None
    err_msg: str | None = None


class _StatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: int
    data: _StatusData


ModelT = TypeVar("ModelT", bound=BaseModel)


class MinerUPdfParser(PdfParser):
    """通过 MinerU 异步 URL 解析接口获取 Markdown。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://mineru.net/api/v4",
        poll_interval: float = 0.0,
        poll_timeout: float = 300.0,
        client: httpx.AsyncClient | None = None,
        recorder: ExternalCallRecorder | None = None,
    ) -> None:
        if not api_key:
            raise MinerUConfigurationError("MINERU_API_KEY is required for PDF parsing")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._owns_client = client is None
        self._recorder = recorder or NullExternalCallRecorder()
        self.call_count = 0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def parse(
        self,
        pdf_bytes: bytes,
        source_url: str,
        *,
        related_entity_id: str | None = None,
    ) -> ParsedPdf:
        """提交来源 URL；bytes 由上层保留为本地原始制品。"""
        del pdf_bytes
        task = await self._request_model(
            "POST",
            f"{self._base_url}/extract/task",
            _SubmitResponse,
            "mineru returned an invalid submit response",
            {"url": source_url, "model_version": "vlm"},
            related_entity_id=related_entity_id,
        )
        if task.code != 0:
            raise MinerUError("mineru rejected the parse task")
        task_id = task.data.task_id
        deadline = asyncio.get_running_loop().time() + self._poll_timeout
        while True:
            status = await self._request_model(
                "GET",
                f"{self._base_url}/extract/task/{task_id}",
                _StatusResponse,
                "mineru returned an invalid task response",
                related_entity_id=related_entity_id,
            )
            if status.code != 0 or status.data.state == "failed":
                raise MinerUError("mineru failed to parse the PDF")
            if status.data.state == "done" and (status.data.markdown_url or status.data.full_zip_url):
                result_url = status.data.markdown_url or status.data.full_zip_url
                assert result_url is not None
                response, call_id = await self._request(
                    "GET", result_url, related_entity_id=related_entity_id
                )
                try:
                    if status.data.markdown_url:
                        text = response.text
                    else:
                        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                            text = archive.read("full.md").decode("utf-8")
                except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as error:
                    await self._recorder.finish(call_id, status="SCHEMA_ERROR")
                    raise MinerUError("mineru result archive is invalid") from error
                await self._recorder.finish(call_id, status="SUCCESS")
                return ParsedPdf(task_id=task_id, text=text)
            if asyncio.get_running_loop().time() >= deadline:
                raise MinerURetriableError("mineru parsing timed out")
            await asyncio.sleep(self._poll_interval)

    async def _request_model(
        self,
        method: str,
        url: str,
        model_type: type[ModelT],
        error_message: str,
        payload: dict[str, Any] | None = None,
        *,
        related_entity_id: str | None = None,
    ) -> ModelT:
        response, call_id = await self._request(
            method,
            url,
            payload,
            related_entity_id=related_entity_id,
        )
        try:
            result = model_type.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            await self._recorder.finish(call_id, status="SCHEMA_ERROR")
            raise MinerUError(error_message) from error
        await self._recorder.finish(call_id, status="SUCCESS")
        return result

    async def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        related_entity_id: str | None = None,
    ) -> tuple[httpx.Response, str]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.call_count += 1
            operation = "submit" if method == "POST" else (
                "poll" if "/extract/task/" in url else "download"
            )
            call_id = await self._recorder.start(
                provider="mineru",
                operation=operation,
                attempt=attempt,
                related_entity_id=related_entity_id,
            )
            try:
                response = await self._client.request(
                    method, url, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                )
            except httpx.TimeoutException as error:
                await self._recorder.finish(call_id, status="TIMEOUT")
                if attempt == MAX_ATTEMPTS:
                    raise MinerURetriableError("mineru request timed out") from error
                continue
            except httpx.RequestError as error:
                await self._recorder.finish(call_id, status="NETWORK_ERROR")
                if attempt == MAX_ATTEMPTS:
                    raise MinerURetriableError("mineru request failed") from error
                continue
            if response.status_code in {401, 403}:
                await self._recorder.finish(call_id, status=f"HTTP_{response.status_code}")
                raise MinerUConfigurationError("mineru rejected provider configuration")
            if response.status_code == 429 or response.status_code >= 500:
                await self._recorder.finish(call_id, status=f"HTTP_{response.status_code}")
                if attempt == MAX_ATTEMPTS:
                    raise MinerURetriableError("mineru service is temporarily unavailable")
                continue
            if response.status_code >= 400:
                await self._recorder.finish(call_id, status=f"HTTP_{response.status_code}")
                raise MinerUError("mineru rejected the request")
            return response, call_id
        raise MinerURetriableError("mineru request failed")
