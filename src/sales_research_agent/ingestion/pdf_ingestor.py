"""把公开 PDF 交给 MinerU，并保存原文与解析正文制品。"""

import hashlib
from datetime import UTC, datetime

from sales_research_agent.domain.models import Failure, SourceRevision
from sales_research_agent.domain.repository import DomainRepository
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.ingestion.fetcher import Fetcher
from sales_research_agent.ingestion.ingestor import IngestionResult
from sales_research_agent.providers.base import PdfParser
from sales_research_agent.providers.mineru import MinerUError


class PdfIngestor:
    """协调安全下载、MinerU 解析和 PDF 制品持久化。"""

    def __init__(
        self,
        fetcher: Fetcher,
        parser: PdfParser | None,
        artifacts: ArtifactStore,
        repository: DomainRepository,
    ) -> None:
        self._fetcher = fetcher
        self._parser = parser
        self._artifacts = artifacts
        self._repository = repository

    async def ingest(self, run_id: str, source_id: str, url: str) -> IngestionResult:
        fetched = await self._fetcher.fetch(url, related_entity_id=source_id)
        if fetched.failure is not None:
            return await self._record_failure(run_id, source_id, fetched.failure.code, fetched.failure.retryable, fetched.failure.message)
        if fetched.body is None or fetched.final_url is None or fetched.status_code is None:
            return await self._record_failure(run_id, source_id, "FETCH_FAILED", False, "fetch returned incomplete success")
        if self._parser is None:
            return await self._record_failure(run_id, source_id, "MINERU_CONFIGURATION_MISSING", False, "PDF parser is not configured")

        digest = hashlib.sha256(fetched.body).hexdigest()
        raw_ref = self._artifacts.write_bytes(run_id, f"sources/{source_id}/{digest}.pdf", fetched.body, media_type="application/pdf")
        raw_ref = raw_ref.model_copy(update={"id": await self._repository.upsert_artifact_ref(raw_ref, f"{run_id}:raw:{source_id}:{digest}")})
        try:
            parsed = await self._parser.parse(
                fetched.body,
                fetched.final_url,
                related_entity_id=source_id,
            )
        except (MinerUError, RuntimeError) as error:
            return await self._record_failure(run_id, source_id, "PDF_PARSE_FAILED", True, str(error))
        if not parsed.text.strip():
            return await self._record_failure(run_id, source_id, "PDF_PARSE_EMPTY", False, "MinerU returned no extractable text")
        text_digest = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        clean_ref = self._artifacts.write_text(
            run_id, f"sources/{source_id}/{text_digest}.md", parsed.text, media_type="text/markdown"
        )
        clean_ref = clean_ref.model_copy(update={"id": await self._repository.upsert_artifact_ref(clean_ref, f"{run_id}:clean:{source_id}:{text_digest}")})
        revision = SourceRevision(
            id=f"{source_id}-{digest[:16]}", run_id=run_id, source_id=source_id,
            fetched_at=datetime.now(UTC), final_url=fetched.final_url,
            status_code=fetched.status_code, raw_artifact_id=raw_ref.id, sha256=digest,
        )
        await self._repository.upsert_source_revision(revision, f"{run_id}:source-revision:{source_id}:{digest}")
        await self._repository.append_audit_event(run_id, {"operation": "MINERU_PARSE", "source_id": source_id, "task_id": parsed.task_id})
        return IngestionResult(raw_ref=raw_ref, clean_ref=clean_ref, source_revision=revision)

    async def _record_failure(self, run_id: str, source_id: str, code: str, retryable: bool, message: str) -> IngestionResult:
        failure = Failure(id=f"{source_id}-{code.lower()}", run_id=run_id, operation="PDF_INGESTION", code=code, retryable=retryable, message=message[:200], related_entity_id=source_id)
        await self._repository.upsert_failure(failure, f"{run_id}:pdf:{source_id}:{code}")
        return IngestionResult(failure=failure)
