from sales_research_agent.verification.quote_locator import locate_quote


def test_exact_locator_returns_match_and_original_slice() -> None:
    text = "前文；营业收入增长 12.3%。后文"
    quote = "营业收入增长 12.3%。"

    match = locate_quote(text, quote)

    assert match is not None
    assert match.method == "EXACT"
    assert text[match.start : match.end] == quote


def test_normalized_locator_returns_original_offsets_and_complete_slice() -> None:
    text = "2025 年，营业收入增长 12.3%。"
    quote = "2025年，营业收入增长12.3%。"

    match = locate_quote(text, quote)

    assert match is not None
    assert match.method == "NORMALIZED"
    assert text[match.start : match.end] == text
    assert (match.start, match.end) == (0, len(text))


def test_normalized_locator_preserves_offset_after_unrelated_prefix() -> None:
    text = "来源： 2025 年，营业收入增长 12.3%。"
    quote = "2025年，营业收入增长12.3%。"

    match = locate_quote(text, quote)

    assert match is not None
    assert text[match.start : match.end] == "2025 年，营业收入增长 12.3%。"
    assert match.start == 4


def test_locator_returns_none_when_quote_is_not_present_without_fuzzy_matching() -> None:
    assert locate_quote("营业收入增长 12.3%", "营业收入增长 13.3%") is None
