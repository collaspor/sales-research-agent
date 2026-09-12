"""区分语义支持、来源可信度和资料时效，不把历史计划升级为现状。"""

import re

from sales_research_agent.reporting.models import ReportFact, ReportModel


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
