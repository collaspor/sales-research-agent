"""区分语义支持、来源可信度和资料时效，不把历史计划升级为现状。"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sales_research_agent.reporting.models import FactTrust, ReportFact, ReportModel, ReportSource


def build_fact_trust(fact: ReportFact, sources: tuple[ReportSource, ...]) -> FactTrust:
    """为正文事实生成不替代人工判断的固定可信度标签。"""
    source_by_id = {source.source_id: source for source in sources}
    related = tuple(source_by_id[source_id] for source_id in fact.source_ids if source_id in source_by_id)
    effective_authority = _effective_authority(fact.authority, related)
    code = _authority_code(effective_authority)
    time_status = _time_status(fact, related)
    confidence = _confidence(effective_authority, time_status, related)
    return FactTrust(
        authority_code=code,
        time_status=time_status,
        confidence=confidence,
        label=f"{code} · {time_status} · {confidence} Confidence",
        source_ids=tuple(source.source_id for source in related),
    )


def _authority_code(authority: str) -> str:
    return {"OFFICIAL_PRIMARY": "L1", "TRUSTED_SECONDARY": "L2"}.get(authority, "LU")


def _effective_authority(authority: str, sources: tuple[ReportSource, ...]) -> str:
    """优先使用事实血缘中的最高已知来源等级。"""
    source_authorities = {source.authority for source in sources}
    if "OFFICIAL_PRIMARY" in source_authorities:
        return "OFFICIAL_PRIMARY"
    if "TRUSTED_SECONDARY" in source_authorities:
        return "TRUSTED_SECONDARY"
    return authority


def _time_status(fact: ReportFact, sources: tuple[ReportSource, ...]) -> str:
    if any(token in fact.text for token in ("计划", "预计", "将于", "即将", "未来")):
        return "Forward-looking"
    dates = [source.published_on for source in sources if source.published_on is not None]
    if not dates:
        return "Date Unknown"
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if all(today - timedelta(days=365) <= value <= today for value in dates):
        return "Current"
    return "Historical"


def _confidence(authority: str, time_status: str, sources: tuple[ReportSource, ...]) -> str:
    if authority == "OFFICIAL_PRIMARY" and time_status == "Current":
        return "High"
    secondary_count = sum(source.authority == "TRUSTED_SECONDARY" for source in sources)
    if authority == "OFFICIAL_PRIMARY" or secondary_count >= 2:
        return "Medium"
    return "Low"


def eligible_for_summary(fact: ReportFact, report: ReportModel) -> bool:
    sources = {s.source_id: s for s in report.sources}
    evidence = {e.evidence_id: e for e in report.evidence_index}
    if not fact.evidence_ids or any(eid not in evidence for eid in fact.evidence_ids):
        return False
    if any(evidence[eid].source_id not in fact.source_ids for eid in fact.evidence_ids):
        return False
    linked = [sources[sid] for sid in fact.source_ids if sid in sources]
    if not linked or len(linked) != len(fact.source_ids):
        return False
    if any(s.authority != "OFFICIAL_PRIMARY" or s.published_on is None for s in linked):
        return False
    if any(not 0 <= (report.generated_on - s.published_on).days <= 365
           for s in linked if s.published_on is not None):
        return False
    # 相对时间和计划类表达保留在带来源日期的明细，不能自动认定已经实现。
    text = fact.text + " ".join(evidence[eid].quote for eid in fact.evidence_ids if eid in evidence)
    return re.search(r"今年|明年|年底|即将|计划|预计|将于|currently|this year|next year", text, re.IGNORECASE) is None


def attributed_fact(fact: ReportFact, report: ReportModel) -> ReportFact:
    linked = [s for s in report.sources if s.source_id in fact.source_ids]
    context = "；".join(
        f"{s.title}（发布日期：{s.published_on.isoformat() if s.published_on else '未知'}）"
        for s in linked
    ) or "来源信息缺失"
    return fact.model_copy(update={
        "text": f"来源陈述，待人工核实｜{context}：{fact.text}（时间表达以原文为准，不代表当前状态）"
    })
