"""把受限 HTML 获取结果保存为原始与正文制品。"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sales_research_agent.domain.models import ArtifactRef, Failure, SourceRevision
from sales_research_agent.domain.repository import DomainRepository
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.ingestion.extractor import HtmlExtractor
from sales_research_agent.ingestion.fetcher import Fetcher


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """单来源摄取的结构化结果。"""

    raw_ref: ArtifactRef | None = None
    clean_ref: ArtifactRef | None = None
    source_revision: SourceRevision | None = None
    failure: Failure | None = None


class HtmlIngestor:
    """协调获取、正文抽取和本地制品持久化。"""

    def __init__(
        self,
        fetcher: Fetcher,
        extractor: HtmlExtractor,
        artifacts: ArtifactStore,
        repository: DomainRepository,
    ) -> None:
        self._fetcher = fetcher
        self._extractor = extractor
        self._artifacts = artifacts
        self._repository = repository

    async def ingest(self, run_id: str, source_id: str, url: str) -> IngestionResult:
        """获取并保存一个来源；可预期失败被收敛为领域 Failure。"""
        fetched = await self._fetcher.fetch(url, related_entity_id=source_id)
        if fetched.failure is not None:
            return await self._record_failure(
                run_id,
                source_id,
                fetched.failure.code,
                fetched.failure.retryable,
                fetched.failure.message,
            )
        if fetched.body is None or fetched.final_url is None or fetched.status_code is None:
            return await self._record_failure(
                run_id, source_id, "FETCH_FAILED", False, "fetch returned incomplete success"
            )

        digest = hashlib.sha256(fetched.body).hexdigest()
        raw_ref = self._artifacts.write_bytes(
            run_id,
            f"sources/{source_id}/{digest}.html",
            fetched.body,
            media_type="text/html",
        )
        raw_artifact_id = await self._repository.upsert_artifact_ref(
            raw_ref, f"{run_id}:raw:{source_id}:{digest}"
        )
        raw_ref = raw_ref.model_copy(update={"id": raw_artifact_id})

        extracted = self._extractor.extract(fetched.body, fetched.final_url)
        if extracted.failure_code is not None or extracted.text is None:
            return await self._record_failure(
                run_id,
                source_id,
                extracted.failure_code or "EXTRACTION_FAILED",
                False,
                "HTML body is empty or cannot be decoded into reliable readable text",
            )

        clean_ref = self._artifacts.write_text(
            run_id,
            f"sources/{source_id}/{digest}.txt",
            extracted.text,
        )
        clean_artifact_id = await self._repository.upsert_artifact_ref(
            clean_ref, f"{run_id}:clean:{source_id}:{digest}"
        )
        clean_ref = clean_ref.model_copy(update={"id": clean_artifact_id})
        revision = SourceRevision(
            id=f"{source_id}-{digest[:16]}",
            run_id=run_id,
            source_id=source_id,
            fetched_at=datetime.now(UTC),
            final_url=fetched.final_url,
            status_code=fetched.status_code,
            raw_artifact_id=raw_ref.id,
            sha256=digest,
            published_on=extracted.published_on,
            encoding=extracted.encoding,
        )
        await self._repository.upsert_source_revision(
            revision, f"{run_id}:source-revision:{source_id}:{digest}"
        )
        return IngestionResult(raw_ref=raw_ref, clean_ref=clean_ref, source_revision=revision)

    async def _record_failure(
        self,
        run_id: str,
        source_id: str,
        code: str,
        retryable: bool,
        message: str,
    ) -> IngestionResult:
        failure = Failure(
            id=f"{source_id}-{code.lower()}",
            run_id=run_id,
            operation="HTML_INGESTION",
            code=code,
            retryable=retryable,
            message=message,
            related_entity_id=source_id,
        )
        await self._repository.upsert_failure(failure, f"{run_id}:ingest:{source_id}:{code}")
        return IngestionResult(failure=failure)
