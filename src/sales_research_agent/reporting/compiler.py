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
from sales_research_agent.reporting.composer import fallback_composition
from sales_research_agent.reporting.models import (
    ReportComposition,
    ReportEvidence,
    ReportFact,
    ReportInference,
    ReportModel,
    ReportQuestion,
    ReportSource,
)
from sales_research_agent.reporting.trust import build_fact_trust


def compile_markdown(report: ReportModel) -> str:
    """输出先供售前阅读、后供审计追溯的 Markdown 报告。"""
    context = _report_context(report)
    composition = context.composition
    facts = context.facts
    lines = ["# 售前会前 Intelligence Brief", "", "## 1. Executive Brief", ""]
    if report.brief:
        lines.extend([f"**客户：** {_text(report.brief.customer_name)}  ", f"**调研目标：** {_text(report.brief.research_goal)}", ""])
    lines.extend(["### 一句话判断", "", _text(composition.executive_judgment.text), "", "### 会前关键发现", ""])
    for finding in composition.key_findings:
        lines.extend([f"#### {_text(finding.title)}", "", f"{_claim_marker(finding.claim_ids[0]) if finding.claim_ids else ''}{_text(finding.text)}", "", f"**售前意义：** {_text(finding.presales_significance)}", ""])
        _append_trust(lines, finding.claim_ids, facts, report.sources)
    lines.extend(["## 2. 面客前关键事实", ""])
    for fact in facts.values():
        trust = build_fact_trust(fact, report.sources)
        lines.extend([f"- {_claim_marker(fact.claim_id)} {_text(fact.text)}  ", f"  - `{trust.label}`；证据：{', '.join(_evidence_marker(item) for item in fact.evidence_ids)}", ""])
    lines.extend(["## 3. 售前机会假设", "", "以下均为机会假设，不代表客户已提出需求。", "", "| 公开信号 | 可能关联能力 | 会前待确认 |", "|---|---|---|"])
    for hypothesis in composition.opportunity_hypotheses:
        marker = _claim_marker(hypothesis.claim_ids[0]) if hypothesis.claim_ids else ""
        lines.append(f"| {marker}{_text(hypothesis.public_signal)} | {_text(hypothesis.related_capability)} | {_text(hypothesis.validation_needed)} |")
    lines.extend(["", "## 4. 首次交流建议问题", ""])
    for question in composition.discovery_questions:
        lines.extend([f"- **{_text(question.category)}：** {_text(question.question)}  ", f"  - 为什么问：{_text(question.rationale)}", ""])
    lines.extend(["## 5. 当前判断边界与信息缺口", "", "### 已确认公开事实", ""])
    for fact in facts.values():
        lines.append(f"- {_claim_marker(fact.claim_id)} {_text(fact.text)}")
    lines.extend(["", "### 合理假设，但不可作为事实", ""])
    for hypothesis in composition.opportunity_hypotheses:
        lines.append(f"- {_text(hypothesis.text)}")
    lines.extend(["", "### 尚未确认 / 建议交流验证", ""])
    for gap in composition.readable_gaps:
        lines.extend([f"- **{_text(gap.title)}：** {_text(gap.description)}", f"  - 风险提示：{_text(gap.risk_note)}", f"  - 建议询问：{_text(gap.suggested_question)}", ""])
    lines.extend(["## Appendix A — Evidence Index", "", "注：来源陈述，待人工核实；历史信息不代表当前事实。", ""])
    for index, evidence in enumerate(context.evidence, start=1):
        source = context.sources.get(evidence.source_id)
        lines.extend([f"### E{index:03d}", "", f"{_evidence_marker(evidence.evidence_id)} **原文：**", "", f"> {_text(evidence.quote)}", ""])
        if source:
            lines.extend([f"**来源：** [{_text(source.title)}]({_url(source.url)})  ", f"**来源等级：** `{_authority_code(source.authority)}` {_authority_label(source.authority)}", ""])
    lines.extend(["## Appendix B — Sources Used", "", "| 来源 | 网页 | 等级 | 日期 |", "|---|---|---|---|"])
    for source in context.sources.values():
        published = source.published_on.isoformat() if source.published_on else "日期未识别"
        lines.append(f"| {_text(source.title)} | [{_url(source.url)}]({_url(source.url)}) | `{_authority_code(source.authority)}` | {published} |")
    lines.extend(["", "## Appendix C — Research Quality", "", f"- 成功来源：{report.stats.sources_succeeded}；失败来源：{report.stats.sources_failed}；已批准事实：{report.stats.claims_approved}。", f"- 编排模式：{_text(report.composition_mode)}。内部失败与缺口记录保留在审计库，不作为正文面客信息。", "", "### 可信度说明", "", "- 所有正文事实均绑定已审批 Evidence；机会假设不等同客户需求。", "- L1/L2/LU 仅说明来源类型；请在重要客户交流前打开原始网页复核。", ""])
    return "\n".join(lines)


def compile_html(report: ReportModel) -> str:
    """按稳定 ID 顺序渲染 HTML，模板自动转义全部不可信文本。"""
    template = _template_environment().get_template("report.html.j2")
    return template.render(
        report=report, **_report_context(report), trust=build_fact_trust,
    )


def _report_context(report: ReportModel) -> "ReportContext":
    """筛出仅支撑正文结论的来源和证据，避免无关搜索结果进入报告。"""
    composition = report.composition or fallback_composition(report)
    referenced_claims = set(composition.executive_judgment.claim_ids)
    for group in (composition.key_findings, composition.opportunity_hypotheses):
        referenced_claims.update(claim_id for item in group for claim_id in item.claim_ids)
    facts = {item.claim_id: item for item in report.facts if item.claim_id in referenced_claims}
    if not facts:
        facts = {item.claim_id: item for item in report.facts}
    source_ids = {source_id for fact in facts.values() for source_id in fact.source_ids}
    sources = {source.source_id: source for source in report.sources if source.source_id in source_ids}
    evidence_ids = {evidence_id for fact in facts.values() for evidence_id in fact.evidence_ids}
    evidence = tuple(item for item in report.evidence_index if item.evidence_id in evidence_ids and item.source_id in sources)
    return ReportContext(composition=composition, facts=facts, sources=sources, evidence=evidence)


def _append_trust(
    lines: list[str], claim_ids: tuple[str, ...], facts: dict[str, ReportFact], sources: tuple[ReportSource, ...]
) -> None:
    for claim_id in claim_ids:
        fact = facts.get(claim_id)
        if fact:
            lines.append(f"**可信标签：** `{build_fact_trust(fact, sources).label}`")
    if claim_ids:
        lines.append("")


class ReportContext(dict[str, object]):
    """模板和 Markdown 共享的已过滤报告视图。"""

    composition: ReportComposition
    facts: dict[str, ReportFact]
    sources: dict[str, ReportSource]
    evidence: tuple[ReportEvidence, ...]

    def __init__(
        self,
        *,
        composition: ReportComposition,
        facts: dict[str, ReportFact],
        sources: dict[str, ReportSource],
        evidence: tuple[ReportEvidence, ...],
    ) -> None:
        super().__init__(composition=composition, facts=facts, sources=sources, evidence=evidence)
        self.composition = composition
        self.facts = facts
        self.sources = sources
        self.evidence = evidence


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
