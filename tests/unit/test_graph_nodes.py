from sales_research_agent.domain.models import Claim
from sales_research_agent.graph.nodes import _determine_report_outcome


def test_report_outcome_fails_without_approved_fact() -> None:
    assert _determine_report_outcome(["question-0"], [], [], []) == "FAILED"


def test_report_outcome_is_partial_when_a_question_has_no_approved_fact() -> None:
    approved = Claim(
        id="claim-question-0-source-0-0",
        run_id="run-1",
        kind="FACT",
        text="事实",
        evidence_ids=["evidence-1"],
        upstream_claim_ids=[],
        status="APPROVED",
    )

    assert (
        _determine_report_outcome(["question-0", "question-1"], [approved], [], [])
        == "PARTIAL"
    )


def test_report_outcome_completes_when_every_question_has_an_approved_fact() -> None:
    claims = [
        Claim(
            id=f"claim-{question_id}-source-0-0",
            run_id="run-1",
            kind="FACT",
            text="事实",
            evidence_ids=["evidence-1"],
            upstream_claim_ids=[],
            status="APPROVED",
        )
        for question_id in ("question-0", "question-1")
    ]

    assert _determine_report_outcome(["question-0", "question-1"], claims, [], []) == "COMPLETED"
