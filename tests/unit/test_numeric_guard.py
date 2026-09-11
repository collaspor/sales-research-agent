import pytest

from sales_research_agent.verification.numeric_guard import compare_critical_tokens


def test_numeric_guard_accepts_tokens_in_different_order() -> None:
    result = compare_critical_tokens(
        source="2025年收入增长 12.3%，服务 1,200 家客户",
        quote="服务 1,200 家客户，收入增长 12.3%（2025年）",
    )

    assert result.ok is True


def test_numeric_guard_rejects_changed_percentage() -> None:
    result = compare_critical_tokens(
        source="营业收入同比增长 12.3%",
        quote="营业收入同比增长 21.3%",
    )

    assert result.ok is False
    assert result.reason == "NUMERIC_MISMATCH"


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("收入为 12.3 亿元", "收入为 12.3 亿元，新增 2 家客户"),
        ("收入为 12.3 亿元，新增 2 家客户", "收入为 12.3 亿元"),
    ],
)
def test_numeric_guard_rejects_missing_or_added_tokens(source: str, quote: str) -> None:
    result = compare_critical_tokens(source=source, quote=quote)

    assert result.ok is False
    assert result.reason == "NUMERIC_MISMATCH"


def test_numeric_guard_accepts_text_without_critical_tokens() -> None:
    result = compare_critical_tokens(source="营业收入保持稳定", quote="营业收入保持稳定")

    assert result.ok is True
