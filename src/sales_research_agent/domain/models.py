"""POC 的可追溯领域实体。"""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

UppercaseValue = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z_]*$")]
FailureCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
SourceAuthority = Literal["OFFICIAL_PRIMARY", "TRUSTED_SECONDARY", "UNCLASSIFIED"]
ContentKind = Literal["HTML", "PDF", "UNKNOWN"]
ExecutionStatus = Literal["RUNNING", "FINISHED", "FAILED"]
ReportOutcome = Literal["COMPLETED", "PARTIAL", "NEEDS_REVIEW", "FAILED"]
CURRENT_RUNTIME_VERSION = 2


class DomainModel(BaseModel):
    """所有领域实体的严格基础模型。"""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_utc_datetimes(self) -> Self:
        """领域时间必须是零偏移的 UTC 时间。"""
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if isinstance(value, datetime) and (
                value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            ):
                raise ValueError(f"{field_name} must be a UTC-aware datetime")
        return self


class Brief(DomainModel):
    id: str
    run_id: str
    customer_name: str
    scenario: str
    known_context: str
    research_goal: str


class ResearchQuestion(DomainModel):
    id: str
    run_id: str
    text: str
    purpose: str
    preferred_source_types: list[UppercaseValue]
    completion_criteria: str


class Source(DomainModel):
    id: str
    run_id: str
    url: str
    canonical_url: str
    title: str
    source_type: UppercaseValue
    discovered_by_question_ids: list[str]
    authority: SourceAuthority = "UNCLASSIFIED"
    content_kind: ContentKind = "UNKNOWN"


class SourceRevision(DomainModel):
    id: str
    run_id: str
    source_id: str
    fetched_at: datetime
    final_url: str
    status_code: int
    raw_artifact_id: str
    sha256: str


class DocumentBlock(DomainModel):
    id: str
    run_id: str
    source_revision_id: str
    ordinal: int
    text: str
    clean_start: int
    clean_end: int


class Evidence(DomainModel):
    id: str
    run_id: str
    block_id: str
    quote: str
    start: int
    end: int
    locator_method: UppercaseValue
    numeric_ok: bool
    status: UppercaseValue


class Claim(DomainModel):
    id: str
    run_id: str
    kind: Literal["FACT", "INFERENCE", "QUESTION"]
    text: str
    evidence_ids: list[str]
    upstream_claim_ids: list[str]
    status: UppercaseValue

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        """Claim 的类别决定最小可追溯血缘。"""
        if self.kind == "FACT" and not self.evidence_ids:
            raise ValueError("FACT claims require at least one evidence id")
        if self.kind == "INFERENCE" and not (self.evidence_ids or self.upstream_claim_ids):
            raise ValueError("INFERENCE claims require evidence or upstream claims")
        if self.kind == "QUESTION" and self.status == "APPROVED":
            raise ValueError("QUESTION claims cannot be APPROVED")
        return self


class Verification(DomainModel):
    id: str
    run_id: str
    claim_id: str
    evidence_id: str
    located: bool
    numeric_ok: bool
    semantic_decision: UppercaseValue
    reason: str


class Gap(DomainModel):
    id: str
    run_id: str
    question_id: str
    code: UppercaseValue
    description: str
    related_source_ids: list[str]
    related_claim_ids: list[str]


class Failure(DomainModel):
    id: str
    run_id: str
    operation: str
    code: FailureCode
    retryable: bool
    message: str
    related_entity_id: str


class RunStats(DomainModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    search_calls: int
    http_calls: int
    model_calls: int
    pdf_calls: int = 0
    sources_succeeded: int
    sources_failed: int
    claims_approved: int
    claims_rejected: int
    official_sources_succeeded: int = 0
    secondary_sources_succeeded: int = 0


class RunMetadata(DomainModel):
    """独立于 checkpoint 的运行兼容版本与生命周期摘要。"""

    run_id: str
    runtime_version: int
    execution_status: ExecutionStatus
    report_outcome: ReportOutcome | None
    started_at: datetime
    finished_at: datetime | None


class ReportVersion(DomainModel):
    id: str
    run_id: str
    created_at: datetime
    report_model_artifact_id: str
    markdown_artifact_id: str
    html_artifact_id: str
    status: UppercaseValue
    is_active: bool


class ArtifactRef(DomainModel):
    id: str
    run_id: str
    relative_path: str
    sha256: str
    media_type: str
    size_bytes: int
    created_at: datetime
