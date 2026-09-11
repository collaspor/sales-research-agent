"""Tavily 搜索适配器的离线契约测试。"""

import json
from pathlib import Path

import httpx
import pytest

from sales_research_agent.providers.tavily import (
    ProviderConfigurationError,
    ProviderPermanentError,
    ProviderRetriableError,
    TavilySearchProvider,
)


def _fixture_payload() -> dict[str, object]:
    fixture = Path(__file__).parents[1] / "fixtures" / "tavily" / "search_success.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_tavily_maps_results_without_treating_snippet_as_evidence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_fixture_payload())

    provider = TavilySearchProvider(api_key="test-key", transport=httpx.MockTransport(handler))

    results = await provider.search("海尔智家 官方 2025", max_results=3)

    assert results[0].url.startswith("https://")
    assert results[0].snippet_is_evidence is False
    assert json.loads(requests[0].content) == {
        "query": "海尔智家 官方 2025",
        "search_depth": "advanced",
        "max_results": 3,
        "include_answer": False,
        "include_raw_content": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, ProviderConfigurationError),
        (403, ProviderConfigurationError),
        (429, ProviderRetriableError),
        (500, ProviderRetriableError),
        (400, ProviderPermanentError),
    ],
)
async def test_tavily_classifies_http_errors_without_exposing_secret(
    status_code: int, error_type: type[Exception]
) -> None:
    provider = TavilySearchProvider(
        api_key="test-key-that-must-not-leak",
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code)),
    )

    with pytest.raises(error_type) as raised:
        await provider.search("query", max_results=1)

    assert "test-key-that-must-not-leak" not in str(raised.value)
    assert "authorization" not in str(raised.value).lower()


@pytest.mark.asyncio
async def test_tavily_classifies_timeout_as_retriable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    provider = TavilySearchProvider(api_key="test-key", transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderRetriableError):
        await provider.search("query", max_results=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "rate_limit", "server_error"])
async def test_tavily_retries_transient_failures_within_three_attempts(failure: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            if failure == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            if failure == "rate_limit":
                return httpx.Response(429)
            return httpx.Response(503)
        return httpx.Response(200, json=_fixture_payload())

    provider = TavilySearchProvider(api_key="test-key", transport=httpx.MockTransport(handler))

    results = await provider.search("query", max_results=1)

    assert len(results) == 1
    assert calls == 3
    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_tavily_stops_retrying_after_three_transient_failures() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    provider = TavilySearchProvider(api_key="test-key", transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderRetriableError):
        await provider.search("query", max_results=1)

    assert calls == 3
    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_tavily_uses_bounded_connect_and_read_timeouts() -> None:
    timeouts: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]
        assert isinstance(timeout, dict)
        timeouts.append(timeout)
        return httpx.Response(200, json=_fixture_payload())

    provider = TavilySearchProvider(api_key="test-key", transport=httpx.MockTransport(handler))

    await provider.search("query", max_results=1)

    assert timeouts == [{"connect": 5.0, "read": 15.0, "write": 15.0, "pool": 15.0}]
