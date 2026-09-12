import httpx
import pytest

from sales_research_agent.ingestion.fetcher import Fetcher
from sales_research_agent.ingestion.url_policy import UrlPolicy
from tests.fakes import MemoryExternalCallRecorder


@pytest.mark.asyncio
async def test_fetcher_retries_rate_limit_at_most_three_times(run_store) -> None:
    run_store.transport.queue_response(httpx.Response(429, headers={"retry-after": "0"}))
    run_store.transport.queue_response(httpx.Response(429, headers={"retry-after": "0"}))
    run_store.transport.queue_response(httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>ok</p>"))

    fetched = await run_store.fetcher.fetch(
        "https://fixture.test/article", related_entity_id="source-1"
    )

    assert fetched.failure is None
    assert fetched.body == b"<p>ok</p>"
    assert len(run_store.transport.calls) == 3


@pytest.mark.asyncio
async def test_fetcher_retries_timeout_at_most_three_times(run_store) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>ok</p>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    recorder = MemoryExternalCallRecorder()
    policy = UrlPolicy(
        resolver=lambda host: ["93.184.216.34"] if host == "fixture.test" else []
    )
    run_store.fetcher = Fetcher(client, policy, recorder=recorder)

    fetched = await run_store.fetcher.fetch(
        "https://fixture.test/article", related_entity_id="source-1"
    )

    assert fetched.failure is None
    assert calls == 3
    assert recorder.started_count("fetcher") == 3
    assert recorder.finished_statuses("fetcher") == ["TIMEOUT", "TIMEOUT", "SUCCESS"]
    started = [event for event in recorder.events if event["event_type"] == "CALL_STARTED"]
    assert [event["attempt"] for event in started] == [1, 2, 3]
    assert {event["related_entity_id"] for event in started} == {"source-1"}
    await client.aclose()


@pytest.mark.asyncio
async def test_pdf_is_accepted_but_unknown_binary_and_oversize_are_rejected(run_store) -> None:
    run_store.transport.queue_response(httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    pdf = await run_store.fetcher.fetch("https://fixture.test/document.pdf")
    run_store.transport.queue_response(httpx.Response(200, headers={"content-type": "image/png"}, content=b"png"))
    non_html = await run_store.fetcher.fetch("https://fixture.test/image")
    run_store.transport.queue_response(
        httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": str(8 * 1024 * 1024 + 1)},
            content=b"x",
        )
    )
    too_large = await run_store.fetcher.fetch("https://fixture.test/large")

    assert pdf.failure is None
    assert pdf.content_kind == "PDF"
    assert pdf.body == b"%PDF"
    assert non_html.failure is not None
    assert non_html.failure.code == "UNSUPPORTED_CONTENT_TYPE"
    assert too_large.failure is not None
    assert too_large.failure.code == "RESPONSE_TOO_LARGE"
