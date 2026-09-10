import pytest

from sales_research_agent.verification.gate import decide_claim


def test_supported_external_fact_is_approved() -> None:
    result = decide_claim(kind="FACT", located=True, numeric_ok=True, semantic="SUPPORTED")

    assert result.approved is True
    assert result.reason == "APPROVED"


@pytest.mark.parametrize("decision", ["UNSUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED"])
def test_external_fact_only_accepts_supported(decision: str) -> None:
    result = decide_claim(kind="FACT", located=True, numeric_ok=True, semantic=decision)

    assert result.approved is False
    assert result.reason == "SEMANTIC_NOT_SUPPORTED"


def test_fact_without_evidence_is_rejected_before_numeric_or_semantic_checks() -> None:
    result = decide_claim(kind="FACT", located=False, numeric_ok=False, semantic=None)

    assert result.approved is False
    assert result.reason == "EVIDENCE_NOT_LOCATED"


def test_fact_with_changed_numeric_tokens_is_rejected_before_semantic_check() -> None:
    result = decide_claim(kind="FACT", located=True, numeric_ok=False, semantic="SUPPORTED")

    assert result.approved is False
    assert result.reason == "NUMERIC_MISMATCH"


def test_inference_is_not_counted_as_external_fact() -> None:
    result = decide_claim(kind="INFERENCE", located=True, numeric_ok=True, semantic="SUPPORTED")

    assert result.approved is False
    assert result.reason == "NON_FACT_CLAIM"


def test_question_is_not_counted_as_external_fact() -> None:
    result = decide_claim(kind="QUESTION", located=False, numeric_ok=False, semantic=None)

    assert result.approved is False
    assert result.reason == "NON_FACT_CLAIM"
