from pathlib import Path

import httpx
import pytest


@pytest.fixture
def article_html() -> bytes:
    return (Path(__file__).parents[1] / "fixtures" / "html" / "article.html").read_bytes()


@pytest.mark.asyncio
async def test_ingestion_persists_raw_and_clean_artifacts(run_store, article_html: bytes) -> None:
    run_store.transport.queue_response(
        httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html,
        )
    )

    result = await run_store.ingestor.ingest("run-1", "src-1", "https://fixture.test/article")

    assert result.failure is None
    assert result.clean_ref is not None
    assert result.raw_ref is not None
    assert "可信段落" in run_store.artifacts.read_text(result.clean_ref)
    assert run_store.artifacts.read_bytes(result.raw_ref).startswith(b"<!doctype html>")
    assert len(await run_store.repository.list_artifact_refs("run-1")) == 2


@pytest.mark.asyncio
async def test_one_404_returns_failure_instead_of_raising(run_store) -> None:
    run_store.transport.queue_response(httpx.Response(404, content=b"not found"))

    result = await run_store.ingestor.ingest("run-1", "src-404", "https://fixture.test/missing")

    assert result.failure is not None
    assert result.failure.code == "HTTP_404"
    assert result.raw_ref is None
    assert result.clean_ref is None


@pytest.mark.asyncio
async def test_unreadable_html_is_saved_raw_but_not_as_clean_content(run_store):
    body = '<html><body><article><p>' + '损坏\ufffd正文。' * 30 + '</p></article></body></html>'
    run_store.transport.queue_response(httpx.Response(
        200, headers={"content-type": "text/html"}, content=body.encode(),
    ))
    result = await run_store.ingestor.ingest("run-1", "src-bad", "https://fixture.test/article")
    assert result.failure.code == "TEXT_UNREADABLE"
    assert result.clean_ref is None
    assert await run_store.repository.list_source_revisions("run-1") == []
    assert len(await run_store.repository.list_artifact_refs("run-1")) == 1


@pytest.mark.asyncio
async def test_redirect_target_is_revalidated_before_it_is_requested(run_store, article_html: bytes) -> None:
    run_store.transport.queue_response(httpx.Response(302, headers={"location": "http://127.0.0.1/"}))

    result = await run_store.ingestor.ingest("run-1", "src-redirect", "https://fixture.test/article")

    assert result.failure is not None
    assert result.failure.code == "URL_BLOCKED"
    assert len(run_store.transport.calls) == 1


@pytest.mark.asyncio
async def test_repeated_ingestion_returns_artifact_reference_persisted_by_operation_key(
    run_store, article_html: bytes
) -> None:
    for _ in range(2):
        run_store.transport.queue_response(
            httpx.Response(200, headers={"content-type": "text/html"}, content=article_html)
        )

    first = await run_store.ingestor.ingest("run-1", "src-repeat", "https://fixture.test/article")
    second = await run_store.ingestor.ingest("run-1", "src-repeat", "https://fixture.test/article")
    references = await run_store.repository.list_artifact_refs("run-1")

    assert first.raw_ref is not None
    assert second.raw_ref is not None
    assert second.raw_ref.id in {reference.id for reference in references}
