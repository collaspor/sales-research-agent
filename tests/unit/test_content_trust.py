from datetime import date

import pytest

from sales_research_agent.ingestion.extractor import HtmlExtractor, decode_html
from sales_research_agent.ingestion.text_quality import is_readable
from sales_research_agent.reporting.compiler import compile_html, compile_markdown
from sales_research_agent.reporting.trust import eligible_for_summary


@pytest.mark.parametrize("encoding", ["utf-8", "gbk", "gb18030", "utf-16"])
def test_explicit_decoding_preserves_chinese(encoding):
    body = '<html><head><meta charset="gbk"></head><body><article><p>' + "比亚迪公开智能驾驶技术进展。" * 30 + '</p></article></body></html>'
    result = HtmlExtractor().extract(body.encode(encoding), "https://example.com/article")
    assert result.failure_code is None
    assert "比亚迪公开智能驾驶" in result.text


def test_conflicting_utf8_and_gbk_declarations_recover_gbk():
    raw = '<meta charset="utf-8"><meta charset="gbk"><p>比亚迪</p>'.encode("gbk")
    assert "比亚迪" in decode_html(raw)[0]


def test_undeclared_invalid_bytes_fail_closed():
    result = HtmlExtractor().extract(b"<p>\xff\xfe\x81</p>", "https://example.com")
    assert result.failure_code == "TEXT_ENCODING_UNCERTAIN"


@pytest.mark.parametrize("text", [
    "Normal English financial report: revenue increased 10%.",
    "正常中文正文，包含英文 DeepSeek 和数字 2025。",
    "Компания опубликовала годовой отчет.",
    "Компанія опублікувала щорічний звіт і повідомила про підвищення якості продукції.",
])
def test_normal_languages_are_not_blocked(text):
    assert is_readable(text)


@pytest.mark.parametrize("text", [
    "损坏\ufffd正文", "损坏\x00正文",
    "ДгЙ§ШЅБЅЪмЭТВлЧвВЩЙКздВЉЪРЕФL2МЖDipilotМнЪЛИЈжњЯЕЭГЃЌвЛЯТзгОЭИЩЕНСЫздбаЕФИпЫйDNP",
])
def test_known_corruption_is_blocked(text):
    assert not is_readable(text)


def test_publication_date_comes_from_metadata_not_event_text():
    body = '<html><head><meta property="article:published_time" content="2023-06-01T10:00:00"></head><body><article><p>' + "2025年计划上市。" * 30 + '</p></article></body></html>'
    result = HtmlExtractor().extract(body.encode(), "https://example.com")
    assert result.published_on == date(2023, 6, 1)


@pytest.mark.parametrize("authority,published,text,allowed", [
    ("OFFICIAL_PRIMARY", date(2026, 9, 1), "公司发布报告。", True),
    ("UNCLASSIFIED", date(2026, 9, 1), "公司发布报告。", False),
    ("TRUSTED_SECONDARY", date(2026, 9, 1), "公司发布报告。", False),
    ("OFFICIAL_PRIMARY", None, "公司发布报告。", False),
    ("OFFICIAL_PRIMARY", date(2023, 6, 1), "公司发布报告。", False),
    ("OFFICIAL_PRIMARY", date(2027, 6, 1), "公司发布报告。", False),
    ("OFFICIAL_PRIMARY", date(2026, 9, 1), "公司将于年底推出产品。", False),
])
def test_summary_requires_recent_dated_primary_source(report_model, authority, published, text, allowed):
    fact = report_model.facts[0].model_copy(update={"text": text})
    source = report_model.sources[0].model_copy(update={"authority": authority, "published_on": published})
    report = report_model.model_copy(update={
        "facts": (fact,), "sources": (source,), "generated_on": date(2026, 9, 12),
    })
    assert eligible_for_summary(fact, report) is allowed
    md = compile_markdown(report)
    html = compile_html(report)
    assert text in md
    assert text in html
    assert "来源陈述，待人工核实" in md
    assert "来源陈述，待人工核实" in html
    assert ("High Confidence" in md) is allowed
