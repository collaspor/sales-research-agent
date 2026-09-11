"""从同一 ReportModel 确定性生成双格式报告并发布制品。"""

from collections.abc import Iterable
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sales_research_agent.domain.models import ReportVersion
from sales_research_agent.domain.repository import DomainRepository
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.reporting.models import (
    ReportFact,
    ReportInference,
    ReportModel,
    ReportQuestion,
)


def compile_markdown(report: ReportModel) -> str:
    """按稳定 ID 顺序编译 Markdown，保留审计所需的 data 属性。"""
    lines = ["# 调研报告", "", "## 声明", "", _text(report.declaration), "", "## 执行摘要", "", _text(report.summary), ""]
    _append_fact_section(lines, "客户公开事实", report.facts)
    _append_fact_section(lines, "近期公开变化", report.recent_changes)
    _append_inference_section(lines, report.inferences)
    _append_question_section(lines, report.questions)
    _append_plain_section(lines, "信息缺口", ((item.code, item.description) for item in report.gaps))
    _append_plain_section(lines, "失败来源", ((item.code, item.message) for item in report.failures))

    lines.extend(["## 来源", ""])
    for source in sorted(report.sources, key=lambda item: item.source_id):
        lines.append(
            f"- `{_attribute(source.source_id)}`：[{_text(source.title)}]({_url(source.url)}) "
            f"[{_authority_label(source.authority)}]"
        )
    lines.append("")
    lines.extend(["## 证据索引", ""])
    for index, evidence in enumerate(sorted(report.evidence_index, key=lambda item: item.evidence_id), start=1):
        lines.append(
            f"{index}. {_evidence_marker(evidence.evidence_id)} {_text(evidence.quote)}"
            f"（来源：`{_attribute(evidence.source_id)}`）"
        )
    lines.append("")
    lines.extend(
        [
            "## 本次运行统计",
            "",
            f"- 成功来源：{report.stats.sources_succeeded}",
            f"- 失败来源：{report.stats.sources_failed}",
            f"- 已批准 Claim：{report.stats.claims_approved}",
            "",
        ]
    )
    return "\n".join(lines)


def compile_html(report: ReportModel) -> str:
    """按稳定 ID 顺序渲染 HTML，模板自动转义全部不可信文本。"""
    template = _template_environment().get_template("report.html.j2")
    return template.render(
        report=report,
        facts=sorted(report.facts, key=lambda item: item.claim_id),
        recent_changes=sorted(report.recent_changes, key=lambda item: item.claim_id),
        inferences=sorted(report.inferences, key=lambda item: item.claim_id),
        questions=sorted(report.questions, key=lambda item: item.claim_id),
        gaps=sorted(report.gaps, key=lambda item: (item.code, item.description)),
        failures=sorted(report.failures, key=lambda item: (item.code, item.message)),
        sources=sorted(report.sources, key=lambda item: item.source_id),
        evidence_index=sorted(report.evidence_index, key=lambda item: item.evidence_id),
    )


class ReportPublisher:
    """仅在完整双格式制品写入成功后登记新的报告版本。"""

    def __init__(self, artifacts: ArtifactStore, repository: DomainRepository) -> None:
        self._artifacts = artifacts
        self._repository = repository

    async def publish(self, run_id: str, report: ReportModel) -> ReportVersion:
        """原子替换三份报告文件，并在其后持久化 active ReportVersion。"""
        report_version_id = str(uuid4())
        previous_contents = await self._read_active_contents(run_id)
        try:
            published = self._artifacts.publish_text_bundle(
                run_id,
                {
                    "reports/report-model.json": (
                        report.model_dump_json(indent=2),
                        "application/json; charset=utf-8",
                    ),
                    "reports/report.md": (compile_markdown(report), "text/markdown; charset=utf-8"),
                    "reports/report.html": (compile_html(report), "text/html; charset=utf-8"),
                },
            )
            report_model_ref = published["reports/report-model.json"]
            markdown_ref = published["reports/report.md"]
            html_ref = published["reports/report.html"]
            for reference in (report_model_ref, markdown_ref, html_ref):
                await self._repository.upsert_artifact_ref(
                    reference, f"{run_id}:report-artifact:{report_version_id}:{reference.relative_path}"
                )

            version = ReportVersion(
                id=report_version_id,
                run_id=run_id,
                created_at=datetime.now(UTC),
                report_model_artifact_id=report_model_ref.id,
                markdown_artifact_id=markdown_ref.id,
                html_artifact_id=html_ref.id,
                status="PUBLISHED",
                is_active=True,
            )
            await self._repository.upsert_report_version(
                version, f"{run_id}:report-version:{report_version_id}"
            )
        except Exception:
            if previous_contents:
                self._artifacts.publish_text_bundle(run_id, previous_contents)
            raise
        return version

    async def _read_active_contents(self, run_id: str) -> dict[str, tuple[str, str]]:
        """在发布前保留 active 报告，供领域登记失败时回滚。"""
        active_versions = [
            version for version in await self._repository.list_report_versions(run_id) if version.is_active
        ]
        if not active_versions:
            return {}
        active_version = max(active_versions, key=lambda version: version.created_at)
        references = (
            await self._repository.get_artifact_ref(active_version.report_model_artifact_id),
            await self._repository.get_artifact_ref(active_version.markdown_artifact_id),
            await self._repository.get_artifact_ref(active_version.html_artifact_id),
        )
        if any(reference is None for reference in references):
            return {}
        return {
            Path(reference.relative_path).relative_to(run_id).as_posix(): (
                self._artifacts.read_text(reference),
                reference.media_type,
            )
            for reference in references
            if reference is not None
        }


async def publish_report(
    artifacts: ArtifactStore, repository: DomainRepository, run_id: str, report: ReportModel
) -> ReportVersion:
    """提供无需构造发布器的窄接口，便于 Graph 节点调用。"""
    return await ReportPublisher(artifacts, repository).publish(run_id, report)


def _append_fact_section(lines: list[str], title: str, items: tuple[ReportFact, ...]) -> None:
    lines.extend([f"## {title}", ""])
    for item in sorted(items, key=lambda value: value.claim_id):
        evidence = ", ".join(_evidence_marker(value) for value in sorted(item.evidence_ids))
        authority = _authority_label(item.authority)
        lines.append(f"- {_claim_marker(item.claim_id)} [{authority}] {_text(item.text)}")
        if evidence:
            lines.append(f"  - 证据：{evidence}")
    lines.append("")


def _append_inference_section(lines: list[str], items: tuple[ReportInference, ...]) -> None:
    lines.extend(["## 基于事实的需求假设", ""])
    for item in sorted(items, key=lambda value: value.claim_id):
        upstream = ", ".join(f"`{_attribute(value)}`" for value in sorted(item.upstream_claim_ids))
        lines.append(f"- {_claim_marker(item.claim_id)} **推断**：{_text(item.text)}")
        if upstream:
            lines.append(f"  - 上游 Claim：{upstream}")
        if item.evidence_ids:
            evidence = ", ".join(_evidence_marker(value) for value in sorted(item.evidence_ids))
            lines.append(f"  - 证据：{evidence}")
    lines.append("")


def _append_question_section(lines: list[str], items: tuple[ReportQuestion, ...]) -> None:
    lines.extend(["## 首次交流验证问题", ""])
    for item in sorted(items, key=lambda value: value.claim_id):
        lines.append(f"- {_claim_marker(item.claim_id)} {_text(item.text)}")
    lines.append("")


def _append_plain_section(lines: list[str], title: str, items: Iterable[tuple[str, str]]) -> None:
    lines.extend([f"## {title}", ""])
    for code, text in sorted(items):
        lines.append(f"- `{_attribute(code)}`：{_text(text)}")
    lines.append("")


def _claim_marker(claim_id: str) -> str:
    return f'<span data-claim-id="{_attribute(claim_id)}"></span>'


def _evidence_marker(evidence_id: str) -> str:
    return f'<span data-evidence-id="{_attribute(evidence_id)}"></span>'


def _attribute(value: str) -> str:
    return escape(value, quote=True)


def _text(value: str) -> str:
    return escape(value, quote=False)


def _url(value: str) -> str:
    return escape(value, quote=True)


def _authority_label(authority: str) -> str:
    """将来源等级转换为不会误导审阅者的固定中文标签。"""
    if authority == "OFFICIAL_PRIMARY":
        return "官方/一手来源"
    if authority == "TRUSTED_SECONDARY":
        return "二手来源，待官方验证"
    return "来源等级未确认"


def _template_environment() -> Environment:
    template_directory = Path(__file__).with_name("templates")
    return Environment(
        loader=FileSystemLoader(template_directory),
        autoescape=select_autoescape(("html", "xml"), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
