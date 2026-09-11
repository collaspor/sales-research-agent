import re

import pytest
from pydantic import ValidationError

from sales_research_agent.reporting.compiler import compile_html, compile_markdown
from sales_research_agent.reporting.models import ReportModel


def extract_ids(payload: str, kind: str) -> set[str]:
    return set(re.findall(rf'data-{kind}-id="([^"]+)"', payload))


def test_markdown_and_html_contain_same_claim_and_evidence_ids(report_model: ReportModel) -> None:
    markdown = compile_markdown(report_model)
    html = compile_html(report_model)

    assert extract_ids(markdown, "claim") == extract_ids(html, "claim")
    assert extract_ids(markdown, "evidence") == extract_ids(html, "evidence")


def test_html_escapes_untrusted_source_text(malicious_report_model: ReportModel) -> None:
    html = compile_html(malicious_report_model)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_discloses_unclassified_authority_and_clickable_source(
    report_model: ReportModel,
) -> None:
    report = report_model.model_copy(
        update={
            "facts": (
                report_model.facts[0].model_copy(update={"authority": "UNCLASSIFIED"}),
            ),
            "sources": (
                report_model.sources[0].model_copy(update={"authority": "UNCLASSIFIED"}),
            ),
        }
    )

    markdown = compile_markdown(report)

    assert "来源等级未确认" in markdown
    assert "[示例来源](https://example.com/report)" in markdown
    assert "二手来源，待官方验证" not in markdown


def test_report_model_and_nested_models_are_immutable(report_model: ReportModel) -> None:
    with pytest.raises(ValidationError):
        report_model.summary = "篡改"
    with pytest.raises(ValidationError):
        report_model.facts[0].text = "篡改"
