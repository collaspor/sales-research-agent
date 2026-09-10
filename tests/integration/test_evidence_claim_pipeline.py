from pathlib import Path
from typing import cast

import pytest

from sales_research_agent.domain.models import Brief, DocumentBlock, ResearchQuestion
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository
from sales_research_agent.providers.base import (
    ClaimCandidate,
    ClaimSynthesis,
    EvidenceCandidate,
    EvidenceExtraction,
    SupportVerification,
)
from sales_research_agent.runtime import ResearchPipeline
from tests.fakes import FakeResearchModel


@pytest.fixture
async def pipeline(repository: SQLiteRepository, tmp_path: Path) -> ResearchPipeline:
    model = FakeResearchModel()
    return ResearchPipeline(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        model=model,
        brief=Brief(
            id="brief-1",
            run_id="run-1",
            customer_name="示例客户",
            scenario="会前调研",
            known_context="",
            research_goal="核验公开事实",
        ),
        question=ResearchQuestion(
            id="question-1",
            run_id="run-1",
            text="公司何时发布年度报告？",
            purpose="核验发布时间",
            preferred_source_types=["WEB"],
            completion_criteria="有一条已核验证据",
        ),
    )


async def _save_block(repository: SQLiteRepository, text: str) -> DocumentBlock:
    block = DocumentBlock(
        id="block-1",
        run_id="run-1",
        source_revision_id="revision-1",
        ordinal=0,
        text=text,
        clean_start=0,
        clean_end=len(text),
    )
    await repository.upsert_document_block(block, operation_key="run-1:block:block-1")
    return block


@pytest.mark.asyncio
async def test_pipeline_only_approves_supported_located_fact(
    pipeline: ResearchPipeline, repository: SQLiteRepository
) -> None:
    model = cast(FakeResearchModel, pipeline.model)
    block = await _save_block(repository, "2025 年公司发布年度报告。")
    model.queue_evidence(
        EvidenceExtraction(
            candidates=[
                EvidenceCandidate(
                    document_block_id=block.id,
                    quote="2025年公司发布年度报告。",
                    rationale="原文直接说明发布时间。",
                )
            ]
        )
    )
    model.queue_claim(
        ClaimSynthesis(
            claims=[
                ClaimCandidate(
                    kind="FACT",
                    text="公司于2025年发布年度报告。",
                    evidence_ids=["evidence-block-1-0"],
                    upstream_claim_ids=[],
                )
            ]
        )
    )
    model.queue_verification(SupportVerification(decision="SUPPORTED", reason="原文直接支持。"))

    result = await pipeline.run(block_ids=[block.id])

    assert result.approved_claim_ids == ["claim-0"]
    assert result.gap_ids == []
    assert len(await repository.list_evidence("run-1")) == 1
    assert (await repository.list_claims("run-1"))[0].status == "APPROVED"
    assert (await repository.list_verifications("run-1"))[0].semantic_decision == "SUPPORTED"
    assert len(model.evidence_calls) == 1
    assert len(model.claim_calls) == 1
    assert len(model.verification_calls) == 1
    assert len(await repository.list_artifact_refs("run-1")) == 3


@pytest.mark.asyncio
async def test_pipeline_records_gap_when_model_quote_is_not_present(
    pipeline: ResearchPipeline, repository: SQLiteRepository
) -> None:
    model = cast(FakeResearchModel, pipeline.model)
    block = await _save_block(repository, "2025 年公司发布年度报告。")
    model.queue_evidence(
        EvidenceExtraction(
            candidates=[
                EvidenceCandidate(
                    document_block_id=block.id,
                    quote="2024 年收入增长 99%。",
                    rationale="不存在的引用。",
                )
            ]
        )
    )

    result = await pipeline.run(block_ids=[block.id])

    assert result.approved_claim_ids == []
    assert result.gap_ids
    assert (await repository.list_evidence("run-1"))[0].status == "REJECTED"
    assert await repository.list_claims("run-1") == []
    assert model.claim_calls == []
