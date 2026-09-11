"""领域持久化端口。"""

from abc import ABC, abstractmethod
from typing import TypeVar

from sales_research_agent.domain.models import (
    ArtifactRef,
    Brief,
    Claim,
    DocumentBlock,
    Evidence,
    Failure,
    Gap,
    ReportVersion,
    ResearchQuestion,
    RunStats,
    Source,
    SourceRevision,
    Verification,
)

Entity = TypeVar(
    "Entity",
    Brief,
    ResearchQuestion,
    Source,
    SourceRevision,
    DocumentBlock,
    Evidence,
    Claim,
    Verification,
    Gap,
    Failure,
    ReportVersion,
    ArtifactRef,
)


class DomainRepository(ABC):
    """领域实体写入与按运行查询的抽象端口。"""

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def upsert_brief(self, entity: Brief, operation_key: str) -> str: ...

    @abstractmethod
    async def get_brief(self, entity_id: str) -> Brief | None: ...

    @abstractmethod
    async def list_briefs(self, run_id: str) -> list[Brief]: ...

    @abstractmethod
    async def upsert_research_question(
        self, entity: ResearchQuestion, operation_key: str
    ) -> str: ...

    @abstractmethod
    async def get_research_question(self, entity_id: str) -> ResearchQuestion | None: ...

    @abstractmethod
    async def upsert_source(self, entity: Source, operation_key: str) -> str: ...

    @abstractmethod
    async def get_source(self, entity_id: str) -> Source | None: ...

    @abstractmethod
    async def list_sources(self, run_id: str) -> list[Source]: ...

    @abstractmethod
    async def upsert_source_revision(self, entity: SourceRevision, operation_key: str) -> str: ...

    @abstractmethod
    async def get_source_revision(self, entity_id: str) -> SourceRevision | None: ...

    @abstractmethod
    async def list_source_revisions(self, run_id: str) -> list[SourceRevision]: ...

    @abstractmethod
    async def upsert_document_block(self, entity: DocumentBlock, operation_key: str) -> str: ...

    @abstractmethod
    async def get_document_block(self, entity_id: str) -> DocumentBlock | None: ...

    @abstractmethod
    async def list_document_blocks(self, run_id: str) -> list[DocumentBlock]: ...

    @abstractmethod
    async def upsert_evidence(self, entity: Evidence, operation_key: str) -> str: ...

    @abstractmethod
    async def get_evidence(self, entity_id: str) -> Evidence | None: ...

    @abstractmethod
    async def list_evidence(self, run_id: str) -> list[Evidence]: ...

    @abstractmethod
    async def upsert_claim(self, entity: Claim, operation_key: str) -> str: ...

    @abstractmethod
    async def get_claim(self, entity_id: str) -> Claim | None: ...

    @abstractmethod
    async def list_claims(self, run_id: str) -> list[Claim]: ...

    @abstractmethod
    async def upsert_verification(self, entity: Verification, operation_key: str) -> str: ...

    @abstractmethod
    async def get_verification(self, entity_id: str) -> Verification | None: ...

    @abstractmethod
    async def list_verifications(self, run_id: str) -> list[Verification]: ...

    @abstractmethod
    async def upsert_gap(self, entity: Gap, operation_key: str) -> str: ...

    @abstractmethod
    async def get_gap(self, entity_id: str) -> Gap | None: ...

    @abstractmethod
    async def list_gaps(self, run_id: str) -> list[Gap]: ...

    @abstractmethod
    async def upsert_failure(self, entity: Failure, operation_key: str) -> str: ...

    @abstractmethod
    async def get_failure(self, entity_id: str) -> Failure | None: ...

    @abstractmethod
    async def list_failures(self, run_id: str) -> list[Failure]: ...

    @abstractmethod
    async def upsert_report_version(self, entity: ReportVersion, operation_key: str) -> str: ...

    @abstractmethod
    async def get_report_version(self, entity_id: str) -> ReportVersion | None: ...

    @abstractmethod
    async def list_report_versions(self, run_id: str) -> list[ReportVersion]: ...

    @abstractmethod
    async def upsert_artifact_ref(self, entity: ArtifactRef, operation_key: str) -> str: ...

    @abstractmethod
    async def get_artifact_ref(self, entity_id: str) -> ArtifactRef | None: ...

    @abstractmethod
    async def list_artifact_refs(self, run_id: str) -> list[ArtifactRef]: ...

    @abstractmethod
    async def append_audit_event(self, run_id: str, event: dict[str, object]) -> None: ...

    @abstractmethod
    async def save_stats(self, stats: RunStats) -> None: ...

    @abstractmethod
    async def get_stats(self, run_id: str) -> RunStats | None: ...

    @abstractmethod
    async def count_source_revisions(self, run_id: str) -> int: ...

    @abstractmethod
    async def has_duplicate_operation_keys(self, run_id: str) -> bool: ...
