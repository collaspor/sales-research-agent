import httpx
import pytest


@pytest.mark.asyncio
async def test_fetcher_retries_rate_limit_at_most_three_times(run_store) -> None:
    run_store.transport.queue_response(httpx.Response(429, headers={"retry-after": "0"}))
    run_store.transport.queue_response(httpx.Response(429, headers={"retry-after": "0"}))
    run_store.transport.queue_response(httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>ok</p>"))

    fetched = await run_store.fetcher.fetch("https://fixture.test/article")

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
    run_store.fetcher.client = client

    fetched = await run_store.fetcher.fetch("https://fixture.test/article")

    assert fetched.failure is None
    assert calls == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_non_html_and_oversize_responses_are_structured_failures(run_store) -> None:
    run_store.transport.queue_response(httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    non_html = await run_store.fetcher.fetch("https://fixture.test/document")
    run_store.transport.queue_response(
        httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": str(8 * 1024 * 1024 + 1)},
            content=b"x",
        )
    )
    too_large = await run_store.fetcher.fetch("https://fixture.test/large")

    assert non_html.failure is not None
    assert non_html.failure.code == "UNSUPPORTED_CONTENT_TYPE"
    assert too_large.failure is not None
    assert too_large.failure.code == "RESPONSE_TOO_LARGE"
