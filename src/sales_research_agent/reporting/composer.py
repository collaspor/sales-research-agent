"""受约束的报告编排和确定性回退逻辑。"""

from sales_research_agent.reporting.models import (
    CompositionFinding,
    DiscoveryQuestion,
    ExecutiveJudgment,
    OpportunityHypothesis,
    ReadableGap,
    ReportComposition,
    ReportModel,
)


class ReportCompositionValidationError(ValueError):
    """报告编排结果试图越过既有事实和证据边界。"""


def validate_composition(report: ReportModel, composition: ReportComposition) -> ReportComposition:
    """确认所有面向客户的编排项都能回溯到已批准实体。"""
    known_claim_ids = {fact.claim_id for fact in report.facts}
    known_gap_codes = {gap.code for gap in report.gaps}
    _validate_claim_ids(composition.executive_judgment.claim_ids, known_claim_ids)
    for finding in composition.key_findings:
        _validate_claim_ids(finding.claim_ids, known_claim_ids)
    for hypothesis in composition.opportunity_hypotheses:
        _validate_claim_ids(hypothesis.claim_ids, known_claim_ids)
    for question in composition.discovery_questions:
        _validate_claim_ids(question.claim_ids, known_claim_ids, allow_empty=True)
        _validate_gap_codes(question.gap_codes, known_gap_codes)
    for gap in composition.readable_gaps:
        _validate_gap_codes(gap.gap_codes, known_gap_codes)
    if len(composition.key_findings) > 5:
        raise ReportCompositionValidationError("too many key findings")
    if len(composition.opportunity_hypotheses) > 5:
        raise ReportCompositionValidationError("too many opportunity hypotheses")
    if len(composition.discovery_questions) > 5:
        raise ReportCompositionValidationError("too many discovery questions")
    return composition


def fallback_composition(report: ReportModel) -> ReportComposition:
    """模型不可用时，只用已审批事实生成可读且可追溯的基础 Brief。"""
    facts = tuple(sorted(report.facts, key=lambda item: item.claim_id))[:5]
    judgment = (
        "公开信息已形成可追溯的会前背景，具体技术架构与采购计划仍需在首次交流中确认。"
        if facts
        else "本次未获得足以形成会前判断的可追溯公开事实，建议先以信息收集为主。"
    )
    return ReportComposition(
        executive_judgment=ExecutiveJudgment(
            text=judgment,
            claim_ids=tuple(item.claim_id for item in facts),
        ),
        key_findings=tuple(
            CompositionFinding(
                title=f"关键事实 {index}",
                text=item.text,
                presales_significance="该公开信号可作为会前背景，需结合客户实际情况验证。",
                claim_ids=(item.claim_id,),
            )
            for index, item in enumerate(facts, start=1)
        ),
        opportunity_hypotheses=tuple(
            OpportunityHypothesis(
                text="该假设仅用于引导首次交流，不代表客户已提出需求。",
                public_signal=item.text,
                related_capability="待结合客户当前业务与技术架构确认。",
                validation_needed="请确认相关场景是否存在、优先级及现有解决方式。",
                claim_ids=(item.claim_id,),
            )
            for item in facts[:3]
        ),
        discovery_questions=tuple(
            DiscoveryQuestion(
                category="背景确认",
                question="上述公开方向在当前阶段的优先级、覆盖范围和主要挑战是什么？",
                rationale="避免将历史公开信息直接视为当前需求。",
                claim_ids=(item.claim_id,),
            )
            for item in facts[:3]
        ),
        readable_gaps=tuple(
            ReadableGap(
                title="待确认信息",
                description=gap.description,
                risk_note="该项尚无可用于面客陈述的充分公开证据。",
                suggested_question="您是否方便补充当前相关情况，供我们进一步理解？",
                gap_codes=(gap.code,),
            )
            for gap in report.gaps[:5]
        ),
    )


def _validate_claim_ids(ids: tuple[str, ...], known: set[str], *, allow_empty: bool = False) -> None:
    if not ids and not allow_empty:
        raise ReportCompositionValidationError("missing claim lineage")
    if not set(ids) <= known:
        raise ReportCompositionValidationError("unknown claim lineage")


def _validate_gap_codes(codes: tuple[str, ...], known: set[str]) -> None:
    if not set(codes) <= known:
        raise ReportCompositionValidationError("unknown gap lineage")
