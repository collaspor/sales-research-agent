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
from sales_research_agent.reporting.trust import attributed_fact, eligible_for_summary


def compile_markdown(report: ReportModel) -> str:
    """按稳定 ID 顺序编译 Markdown，保留审计所需的 data 属性。"""
    source_by_id = {item.source_id: item for item in report.sources}
    lines = ["# 售前会前公网调研报告", "", "## 0. 报告说明", "", _text(report.declaration), ""]
    lines.extend(["### 来源等级", "", "| 标记 | 含义 |", "|---|---|", "| `L1` | 官方 / 一手来源 |", "| `L2` | 二手来源，待官方验证 |", "| `LU` | 来源等级尚未确认，需要人工判断 |", "", "来源等级是系统提示，不代表内容本身一定真实。关键事实应打开原始网页进行最终确认。", ""])
    lines.extend(["## 1. Executive Summary", "", "### 1.1 当前调研摘要", "", _text(report.summary), ""])
    lines.extend(["### 1.2 面客前最值得关注的事实", ""])
    _append_fact_cards(lines, tuple(f for f in report.facts if eligible_for_summary(f, report)))
    lines.extend(["### 1.3 当前最重要的信息缺口", ""])
    _append_plain_section(lines, "", ((item.code, item.description) for item in report.gaps), heading=False)

    lines.extend(["## 2. 面向售前的事实摘要", "", "### 2.1 业务与技术公开事实", ""])
    _append_fact_section(lines, "", tuple(attributed_fact(f, report) for f in report.facts), heading=False)
    if not report.facts:
        lines.append("未获得可靠公开信息。\n")
    lines.extend(["## 3. 信息缺口与待确认事项", ""])
    _append_plain_section(lines, "", ((item.code, item.description) for item in report.gaps), heading=False)
    if not report.gaps:
        lines.append("本次未记录结构化信息缺口。\n")
    _append_question_section(lines, report.questions)
    lines.extend(["## 4. 证据索引", ""])
    for index, evidence in enumerate(sorted(report.evidence_index, key=lambda item: item.evidence_id), start=1):
        source = source_by_id.get(evidence.source_id)
        lines.extend([f"### E{index:03d} {{#{evidence.evidence_id}}}", "", f"**Claim/Evidence ID：** {_evidence_marker(evidence.evidence_id)} `{_attribute(evidence.evidence_id)}`", "", "**原文：**", "", f"> {_text(evidence.quote)}", ""])
        if source is not None:
            lines.extend([f"**来源标题：** {_text(source.title)}  ", f"**来源 URL：** {_url(source.url)}  ", f"**来源等级：** `{_authority_code(source.authority)}` {_authority_label(source.authority)}", ""])
    lines.extend(["## 5. 来源清单", "", "| Source ID | 来源 | 来源等级 |", "|---|---|---|"])
    for source in sorted(report.sources, key=lambda item: item.source_id):
        lines.append(f"| `{_attribute(source.source_id)}` | [{_text(source.title)}]({_url(source.url)}) | `{_authority_code(source.authority)}` {_authority_label(source.authority)} |")
    lines.extend(["", "## 6. 失败来源", ""])
    _append_plain_section(lines, "", ((item.code, item.message) for item in report.failures), heading=False)
    if not report.failures:
        lines.append("本次没有记录失败来源。\n")
    lines.extend(["## 7. 研究覆盖情况", "", f"- 已覆盖：{len(report.facts)} 条有证据事实、{len(report.evidence_index)} 条证据、{len(report.sources)} 个来源", "- 部分覆盖：来源等级与官方属性仍需人工复核", "- 未获得可靠公开信息：未在当前 ReportModel 中提供的企业字段和场景模块", ""])
    lines.extend(["## 8. 本次运行统计", "", "| 指标 | 数值 |", "|---|---:|", f"| 成功来源 | {report.stats.sources_succeeded} |", f"| 失败来源 | {report.stats.sources_failed} |", f"| Evidence | {len(report.evidence_index)} |", f"| Verified Claims | {report.stats.claims_approved} |", f"| 官方来源覆盖 | {'是' if report.stats.official_coverage else '未确认'} |", ""])
    lines.extend(["## Appendix：可信度说明", "", "1. 外部事实必须绑定可定位 Evidence。", "2. 无 Evidence 的内容不能作为确定事实进入报告。", "3. Fact、分析和信息缺口分开呈现。", "4. 系统不根据域名自动认定官方网站。", "5. 访问失败、解析失败和验证失败均显式记录。", ""])
    return "\n".join(lines)


def compile_html(report: ReportModel) -> str:
    """按稳定 ID 顺序渲染 HTML，模板自动转义全部不可信文本。"""
    template = _template_environment().get_template("report.html.j2")
    return template.render(
        report=report,
        summary_facts=sorted((f for f in report.facts if eligible_for_summary(f, report)), key=lambda item: item.claim_id),
        facts=sorted((attributed_fact(f, report) for f in report.facts), key=lambda item: item.claim_id),
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


def _append_fact_section(lines: list[str], title: str, items: tuple[ReportFact, ...], *, heading: bool = True) -> None:
    if heading:
        lines.extend([f"## {title}", ""])
    for item in sorted(items, key=lambda value: value.claim_id):
        evidence = ", ".join(_evidence_marker(value) for value in sorted(item.evidence_ids))
        authority = _authority_label(item.authority)
        lines.append(f"- {_claim_marker(item.claim_id)} [{authority}] {_text(item.text)}")
        if evidence:
            lines.append(f"  - 证据：{evidence}")
    lines.append("")


def _append_fact_cards(lines: list[str], items: tuple[ReportFact, ...]) -> None:
    """将重点事实以可审阅卡片输出，来源详情在证据索引中展开。"""
    for index, item in enumerate(sorted(items, key=lambda value: value.claim_id), start=1):
        evidence = ", ".join(_evidence_marker(value) for value in sorted(item.evidence_ids))
        lines.extend([f"#### {index}．{_text(item.text)}", "", f"**来源等级：** `{_authority_code(item.authority)}` {_authority_label(item.authority)}", f"**证据：** {evidence or '未获得可靠公开证据'}", ""])
    if not items:
        lines.append("未获得可靠公开信息。\n")


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


def _append_plain_section(lines: list[str], title: str, items: Iterable[tuple[str, str]], *, heading: bool = True) -> None:
    if heading:
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


def _authority_code(authority: str) -> str:
    return {"OFFICIAL_PRIMARY": "L1", "TRUSTED_SECONDARY": "L2"}.get(authority, "LU")


def _template_environment() -> Environment:
    template_directory = Path(__file__).with_name("templates")
    return Environment(
        loader=FileSystemLoader(template_directory),
        autoescape=select_autoescape(("html", "xml"), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
