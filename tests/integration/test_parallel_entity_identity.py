from pathlib import Path

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


async def _run_scoped_pipeline(
    repository: SQLiteRepository,
    artifacts: ArtifactStore,
    *,
    question_id: str,
    source_id: str,
) -> None:
    block = DocumentBlock(
        id=f"{source_id}-block-0",
        run_id="run-1",
        source_revision_id=f"revision-{source_id}",
        ordinal=0,
        text="2025 年公司发布年度报告。",
        clean_start=0,
        clean_end=15,
    )
    await repository.upsert_document_block(block, f"run-1:block:{block.id}")
    model = FakeResearchModel()
    evidence_id = f"evidence-{question_id}-{source_id}-0"
    model.queue_evidence(
        EvidenceExtraction(
            candidates=[
                EvidenceCandidate(
                    document_block_id=block.id,
                    quote="2025年公司发布年度报告。",
                    rationale="原文直接陈述。",
                )
            ]
        )
    )
    model.queue_claims(
        ClaimSynthesis(
            claims=[
                ClaimCandidate(
                    kind="FACT",
                    text=f"{source_id} 支持公司于2025年发布年度报告。",
                    evidence_ids=[evidence_id],
                    upstream_claim_ids=[],
                )
            ]
        )
    )
    model.queue_verification(SupportVerification(decision="SUPPORTED", reason="直接支持"))
    pipeline = ResearchPipeline(
        repository=repository,
        artifacts=artifacts,
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
            id=question_id,
            run_id="run-1",
            text="何时发布年度报告？",
            purpose="核验发布时间",
            preferred_source_types=["WEB"],
            completion_criteria="有一条已核验证据",
        ),
        source_id=source_id,
    )
    await pipeline.run(block_ids=[block.id])


@pytest.mark.asyncio
async def test_parallel_pipelines_keep_entities_and_artifacts_isolated(
    repository: SQLiteRepository, tmp_path: Path
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")

    await _run_scoped_pipeline(
        repository, artifacts, question_id="question-0", source_id="source-0"
    )
    await _run_scoped_pipeline(
        repository, artifacts, question_id="question-1", source_id="source-1"
    )

    claims = await repository.list_claims("run-1")
    verifications = await repository.list_verifications("run-1")
    references = await repository.list_artifact_refs("run-1")

    assert {claim.id for claim in claims} == {
        "claim-question-0-source-0-0",
        "claim-question-1-source-1-0",
    }
    assert {item.claim_id for item in verifications} == {claim.id for claim in claims}
    response_paths = {
        reference.relative_path
        for reference in references
        if "model_responses" in reference.relative_path
    }
    assert any("question-0/source-0" in path for path in response_paths)
    assert any("question-1/source-1" in path for path in response_paths)
