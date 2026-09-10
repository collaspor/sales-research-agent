"""带边界和重试规则的静态 HTML 获取器。"""

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from sales_research_agent.ingestion.url_policy import UnsafeUrlError, UrlPolicy

MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """HTTP 获取失败的结构化结果，不携带请求敏感信息。"""

    code: str
    retryable: bool
    message: str
    status_code: int | None = None
    final_url: str | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    """静态网页获取的成功或失败结果。"""

    final_url: str | None = None
    status_code: int | None = None
    body: bytes | None = None
    content_type: str | None = None
    failure: FetchFailure | None = None


class Fetcher:
    """只获取经 URL 策略验证的、有界 HTML 响应。"""

    def __init__(self, client: httpx.AsyncClient, url_policy: UrlPolicy) -> None:
        self.client = client
        self._url_policy = url_policy
        self._timeout = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=15.0)

    async def fetch(self, url: str) -> FetchResult:
        """获取页面，并在每个重定向目标再次执行 URL 安全校验。"""
        current_url = url
        redirects = 0
        while True:
            try:
                self._url_policy.validate(current_url)
            except UnsafeUrlError:
                return self._failure("URL_BLOCKED", False, "URL is not a public target", current_url)

            result, redirect_to = await self._fetch_url(current_url)
            if result is not None:
                return result
            if redirect_to is None:
                return self._failure("FETCH_FAILED", False, "fetch did not produce a result", current_url)
            if redirects >= MAX_REDIRECTS:
                return self._failure(
                    "TOO_MANY_REDIRECTS", False, "redirect limit exceeded", current_url
                )
            redirects += 1
            current_url = urljoin(current_url, redirect_to)

    async def _fetch_url(self, url: str) -> tuple[FetchResult | None, str | None]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with self.client.stream(
                    "GET", url, follow_redirects=False, timeout=self._timeout
                ) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < MAX_ATTEMPTS:
                            await asyncio.sleep(0)
                            continue
                        return (
                            self._failure(
                                f"HTTP_{response.status_code}",
                                True,
                                "remote server did not complete the request",
                                url,
                                response.status_code,
                            ),
                            None,
                        )
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if location:
                            return None, location
                        return (
                            self._failure(
                                f"HTTP_{response.status_code}",
                                False,
                                "redirect response has no location",
                                url,
                                response.status_code,
                            ),
                            None,
                        )
                    if response.status_code >= 400:
                        return (
                            self._failure(
                                f"HTTP_{response.status_code}",
                                False,
                                "remote server rejected the request",
                                url,
                                response.status_code,
                            ),
                            None,
                        )

                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in HTML_CONTENT_TYPES:
                        return (
                            self._failure(
                                "UNSUPPORTED_CONTENT_TYPE",
                                False,
                                "response is not an allowed HTML content type",
                                url,
                                response.status_code,
                            ),
                            None,
                        )
                    if _is_too_large(response.headers.get("content-length")):
                        return (
                            self._failure(
                                "RESPONSE_TOO_LARGE",
                                False,
                                "response exceeds the size limit",
                                url,
                                response.status_code,
                            ),
                            None,
                        )
                    body = await self._read_bounded_body(response)
                    if body is None:
                        return (
                            self._failure(
                                "RESPONSE_TOO_LARGE",
                                False,
                                "response exceeds the size limit",
                                url,
                                response.status_code,
                            ),
                            None,
                        )
                    return (
                        FetchResult(
                            final_url=str(response.url),
                            status_code=response.status_code,
                            body=body,
                            content_type=content_type,
                        ),
                        None,
                    )
            except httpx.TimeoutException:
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(0)
                    continue
                return self._failure("FETCH_TIMEOUT", True, "request timed out", url), None
            except httpx.HTTPError:
                return self._failure("FETCH_NETWORK_ERROR", False, "network request failed", url), None
        return self._failure("FETCH_FAILED", False, "fetch did not complete", url), None

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes | None:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _failure(
        code: str,
        retryable: bool,
        message: str,
        final_url: str,
        status_code: int | None = None,
    ) -> FetchResult:
        return FetchResult(
            final_url=final_url,
            status_code=status_code,
            failure=FetchFailure(
                code=code,
                retryable=retryable,
                message=message,
                status_code=status_code,
                final_url=final_url,
            ),
        )


def _is_too_large(content_length: str | None) -> bool:
    """仅在声明长度有效且越界时提前拒绝响应。"""
    if content_length is None:
        return False
    try:
        return int(content_length) > MAX_RESPONSE_BYTES
    except ValueError:
        return False
