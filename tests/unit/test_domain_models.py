from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from sales_research_agent.domain.models import Claim, SourceRevision


def test_fact_requires_evidence_id() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="claim-1",
            run_id="run-1",
            kind="FACT",
            text="公开事实",
            evidence_ids=[],
            upstream_claim_ids=[],
            status="PROPOSED",
        )


@pytest.mark.parametrize(
    ("kind", "evidence_ids", "upstream_claim_ids", "status"),
    [
        ("INFERENCE", [], [], "PROPOSED"),
        ("QUESTION", [], [], "APPROVED"),
    ],
)
def test_claim_lineage_rules_are_enforced(
    kind: str, evidence_ids: list[str], upstream_claim_ids: list[str], status: str
) -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="claim-1",
            run_id="run-1",
            kind=kind,
            text="待验证陈述",
            evidence_ids=evidence_ids,
            upstream_claim_ids=upstream_claim_ids,
            status=status,
        )


def test_inference_and_question_allow_valid_minimal_lineage() -> None:
    inference = Claim(
        id="claim-2",
        run_id="run-1",
        kind="INFERENCE",
        text="推断",
        evidence_ids=[],
        upstream_claim_ids=["claim-1"],
        status="PROPOSED",
    )
    question = Claim(
        id="claim-3",
        run_id="run-1",
        kind="QUESTION",
        text="待确认问题",
        evidence_ids=[],
        upstream_claim_ids=[],
        status="PROPOSED",
    )

    assert inference.upstream_claim_ids == ["claim-1"]
    assert question.status == "PROPOSED"


def test_source_revision_requires_utc_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        SourceRevision(
            id="revision-1",
            run_id="run-1",
            source_id="source-1",
            fetched_at=datetime.now(timezone(timedelta(hours=8))),
            final_url="https://example.com",
            status_code=200,
            raw_artifact_id="artifact-1",
            sha256="abc",
        )

    revision = SourceRevision(
        id="revision-1",
        run_id="run-1",
        source_id="source-1",
        fetched_at=datetime.now(UTC),
        final_url="https://example.com",
        status_code=200,
        raw_artifact_id="artifact-1",
        sha256="abc",
    )
    assert revision.fetched_at.tzinfo is UTC


def test_enum_values_must_be_uppercase() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="claim-1",
            run_id="run-1",
            kind="fact",
            text="公开事实",
            evidence_ids=["evidence-1"],
            upstream_claim_ids=[],
            status="PROPOSED",
        )
