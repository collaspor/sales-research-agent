import httpx
import pytest

from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.ingestion.fetcher import Fetcher
from sales_research_agent.ingestion.pdf_ingestor import PdfIngestor
from sales_research_agent.ingestion.url_policy import UrlPolicy
from sales_research_agent.providers.base import ParsedPdf, PdfParser


class FakePdfParser(PdfParser):
    async def parse(
        self,
        pdf_bytes: bytes,
        source_url: str,
        *,
        related_entity_id: str | None = None,
    ) -> ParsedPdf:
        del related_entity_id
        return ParsedPdf(task_id="task-1", text="# 2025 年报\n营收 100 亿元")


@pytest.mark.asyncio
async def test_pdf_ingestion_persists_original_and_mineru_text(repository, tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(client, UrlPolicy(resolver=lambda host: ["93.184.216.34"]))
    ingestor = PdfIngestor(fetcher, FakePdfParser(), ArtifactStore(tmp_path / "artifacts"), repository)
    result = await ingestor.ingest("run-1", "source-pdf", "https://public.example/report.pdf")
    await client.aclose()
    assert result.failure is None
    assert result.clean_ref is not None
    refs = await repository.list_artifact_refs("run-1")
    assert {ref.media_type for ref in refs} == {"application/pdf", "text/markdown"}
    blocks = await repository.list_source_revisions("run-1")
    assert len(blocks) == 1


@pytest.mark.asyncio
async def test_pdf_parser_failure_is_structured(repository, tmp_path) -> None:
    class FailingParser(PdfParser):
        async def parse(
            self,
            pdf_bytes: bytes,
            source_url: str,
            *,
            related_entity_id: str | None = None,
        ) -> ParsedPdf:
            del related_entity_id
            raise RuntimeError("mineru unavailable")

    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    client = httpx.AsyncClient(transport=transport)
    ingestor = PdfIngestor(Fetcher(client, UrlPolicy(resolver=lambda host: ["93.184.216.34"])), FailingParser(), ArtifactStore(tmp_path / "artifacts"), repository)
    result = await ingestor.ingest("run-1", "source-pdf", "https://public.example/report.pdf")
    await client.aclose()
    assert result.failure is not None
    assert result.failure.code == "PDF_PARSE_FAILED"
