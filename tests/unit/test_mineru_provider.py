import httpx
import pytest

from sales_research_agent.providers.mineru import MinerUPdfParser, MinerURetriableError


@pytest.mark.asyncio
async def test_mineru_url_task_returns_markdown_after_done_poll() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task-1"}})
        if request.url.path.endswith("/task/task-1"):
            return httpx.Response(200, json={"code": 0, "data": {"state": "done", "markdown_url": "https://result.example/a.md"}})
        return httpx.Response(200, text="# parsed\nRevenue 10%")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    parser = MinerUPdfParser(api_key="test-key", client=client)
    result = await parser.parse(b"%PDF", "https://public.example/a.pdf")
    await client.aclose()
    assert result.task_id == "task-1"
    assert result.text == "# parsed\nRevenue 10%"


@pytest.mark.asyncio
async def test_mineru_timeout_is_redacted_and_bounded() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    parser = MinerUPdfParser(api_key="secret-never-output", client=client)
    with pytest.raises(MinerURetriableError) as raised:
        await parser.parse(b"%PDF", "https://public.example/a.pdf")
    await client.aclose()
    assert calls == 3
    assert "secret-never-output" not in str(raised.value)
