from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sales_research_agent.reporting.composer import (
    ReportCompositionValidationError,
    fallback_composition,
    validate_composition,
)
from sales_research_agent.reporting.models import (
    ReportComposition,
    ReportEvidence,
    ReportFact,
    ReportModel,
    ReportSource,
    ReportStats,
)
from sales_research_agent.reporting.trust import build_fact_trust


def _report() -> ReportModel:
    return ReportModel(
        declaration="仅基于公开信息。",
        summary="调研完成。",
        facts=(
            ReportFact(
                claim_id="claim-1",
                text="客户公开发布了年度报告。",
                evidence_ids=("evidence-1",),
                source_ids=("source-1",),
                authority="OFFICIAL_PRIMARY",
            ),
        ),
        recent_changes=(), inferences=(), questions=(), gaps=(), failures=(),
        sources=(ReportSource(source_id="source-1", title="官方公告", url="https://example.com", authority="OFFICIAL_PRIMARY", published_on=datetime.now(ZoneInfo("Asia/Shanghai")).date()),),
        evidence_index=(ReportEvidence(evidence_id="evidence-1", quote="客户发布年度报告。", source_id="source-1"),),
        stats=ReportStats(sources_succeeded=1, sources_failed=0, claims_approved=1),
    )


def test_fact_trust_exposes_authority_freshness_and_confidence() -> None:
    report = _report()

    trust = build_fact_trust(report.facts[0], report.sources)

    assert trust.label == "L1 · Current · High Confidence"
    assert trust.source_ids == ("source-1",)


def test_composition_rejects_unknown_claim_lineage() -> None:
    composition = ReportComposition.model_validate(
        {
            "executive_judgment": {"text": "判断", "claim_ids": ["claim-missing"]},
            "key_findings": [], "opportunity_hypotheses": [],
            "discovery_questions": [], "readable_gaps": [],
        }
    )

    with pytest.raises(ReportCompositionValidationError, match="unknown claim"):
        validate_composition(_report(), composition)


def test_fallback_composition_only_uses_approved_fact_lineage() -> None:
    composition = fallback_composition(_report())

    assert composition.key_findings[0].claim_ids == ("claim-1",)
