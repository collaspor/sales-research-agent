import io
import zipfile

import httpx
import pytest

from sales_research_agent.providers.mineru import MinerUPdfParser, MinerURetriableError
from tests.fakes import MemoryExternalCallRecorder


@pytest.mark.asyncio
async def test_mineru_url_task_returns_markdown_after_done_poll() -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("full.md", "# parsed\nRevenue 10%")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task-1"}})
        if request.url.path.endswith("/task/task-1"):
            return httpx.Response(200, json={"code": 0, "data": {"state": "done", "full_zip_url": "https://result.example/a.zip"}})
        return httpx.Response(200, content=archive.getvalue())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    recorder = MemoryExternalCallRecorder()
    parser = MinerUPdfParser(api_key="test-key", client=client, recorder=recorder)
    result = await parser.parse(b"%PDF", "https://public.example/a.pdf")
    await client.aclose()
    assert result.task_id == "task-1"
    assert result.text == "# parsed\nRevenue 10%"
    assert recorder.started_count("mineru") == 3
    assert recorder.finished_statuses("mineru") == ["SUCCESS", "SUCCESS", "SUCCESS"]


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
