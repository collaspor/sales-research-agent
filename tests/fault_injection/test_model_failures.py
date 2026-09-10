from pathlib import Path
from typing import cast

import pytest

from sales_research_agent.domain.models import Brief, DocumentBlock, ResearchQuestion
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository
from sales_research_agent.providers.base import (
    ClaimSynthesis,
    EvidenceCandidate,
    EvidenceExtraction,
)
from sales_research_agent.providers.deepseek import ProviderSchemaError
from sales_research_agent.runtime import ResearchPipeline
from tests.fakes import FakeResearchModel


@pytest.fixture
async def pipeline(repository: SQLiteRepository, tmp_path: Path) -> ResearchPipeline:
    model = FakeResearchModel()
    block = DocumentBlock(
        id="block-1",
        run_id="run-1",
        source_revision_id="revision-1",
        ordinal=0,
        text="2025 年公司发布年度报告。",
        clean_start=0,
        clean_end=15,
    )
    await repository.upsert_document_block(block, operation_key="run-1:block:block-1")
    return ResearchPipeline(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        model=model,
        brief=Brief(
            id="brief-1", run_id="run-1", customer_name="示例客户", scenario="会前调研",
            known_context="", research_goal="核验公开事实",
        ),
        question=ResearchQuestion(
            id="question-1", run_id="run-1", text="发布时间？", purpose="核验发布时间",
            preferred_source_types=["WEB"], completion_criteria="有一条已核验证据",
        ),
    )


def _valid_evidence() -> EvidenceExtraction:
    return EvidenceExtraction(
        candidates=[
            EvidenceCandidate(
                document_block_id="block-1", quote="2025年公司发布年度报告。", rationale="直接引用。"
            )
        ]
    )


@pytest.mark.asyncio
async def test_empty_evidence_response_retries_once_then_succeeds(
    pipeline: ResearchPipeline, repository: SQLiteRepository
) -> None:
    model = cast(FakeResearchModel, pipeline.model)
    model.queue_evidence(EvidenceExtraction(candidates=[]))
    model.queue_evidence(_valid_evidence())
    model.queue_claims(ClaimSynthesis(claims=[]))

    result = await pipeline.run(block_ids=["block-1"])

    assert len(model.evidence_calls) == 2
    assert result.failure_ids == []
    assert result.gap_ids
    assert await repository.list_failures("run-1") == []


@pytest.mark.asyncio
async def test_two_schema_errors_become_failure_and_gap_without_fact(
    pipeline: ResearchPipeline, repository: SQLiteRepository
) -> None:
    model = cast(FakeResearchModel, pipeline.model)
    model.queue_evidence(ProviderSchemaError("invalid response"))
    model.queue_evidence(ProviderSchemaError("invalid response"))

    result = await pipeline.run(block_ids=["block-1"])

    failures = await repository.list_failures("run-1")
    assert len(model.evidence_calls) == 2
    assert result.approved_claim_ids == []
    assert result.failure_ids == [failures[0].id]
    assert failures[0].code == "MODEL_SCHEMA_ERROR"
    assert result.gap_ids
    assert await repository.list_claims("run-1") == []


@pytest.mark.asyncio
async def test_verification_timeout_becomes_failure_and_never_approves_fact(
    pipeline: ResearchPipeline, repository: SQLiteRepository
) -> None:
    model = cast(FakeResearchModel, pipeline.model)
    model.queue_evidence(_valid_evidence())
    from sales_research_agent.providers.base import ClaimCandidate

    model.queue_claims(
        ClaimSynthesis(
            claims=[
                ClaimCandidate(
                    kind="FACT", text="公司于2025年发布年度报告。",
                    evidence_ids=["evidence-block-1-0"], upstream_claim_ids=[],
                )
            ]
        )
    )
    model.queue_verification(TimeoutError())

    result = await pipeline.run(block_ids=["block-1"])

    failures = await repository.list_failures("run-1")
    claims = await repository.list_claims("run-1")
    assert result.approved_claim_ids == []
    assert failures[0].code == "MODEL_TIMEOUT"
    assert result.gap_ids
    assert claims[0].status == "REJECTED"
    assert await repository.list_verifications("run-1") == []
