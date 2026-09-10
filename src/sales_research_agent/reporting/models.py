"""报告输出使用的不可变数据模型。"""

from pydantic import BaseModel, ConfigDict


class ReportItem(BaseModel):
    """报告嵌套项的不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportFact(ReportItem):
    """已批准的公开事实或近期变化。"""

    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]


class ReportInference(ReportItem):
    """需显式标注血缘的需求推断。"""

    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    upstream_claim_ids: tuple[str, ...]


class ReportQuestion(ReportItem):
    """首次交流需要验证的问题。"""

    claim_id: str
    text: str


class ReportGap(ReportItem):
    """尚未补齐的信息缺口。"""

    code: str
    description: str


class ReportFailure(ReportItem):
    """本次运行中未掩盖的来源或处理失败。"""

    code: str
    message: str


class ReportSource(ReportItem):
    """报告中可回查的来源。"""

    source_id: str
    title: str
    url: str


class ReportEvidence(ReportItem):
    """对应来源的可定位原文证据。"""

    evidence_id: str
    quote: str
    source_id: str


class ReportStats(ReportItem):
    """只展示运行汇总，不包含模型请求或任何密钥。"""

    sources_succeeded: int
    sources_failed: int
    claims_approved: int


class ReportModel(ReportItem):
    """Markdown 与 HTML 同源的唯一报告输入。"""

    declaration: str
    summary: str
    facts: tuple[ReportFact, ...]
    recent_changes: tuple[ReportFact, ...]
    inferences: tuple[ReportInference, ...]
    questions: tuple[ReportQuestion, ...]
    gaps: tuple[ReportGap, ...]
    failures: tuple[ReportFailure, ...]
    sources: tuple[ReportSource, ...]
    evidence_index: tuple[ReportEvidence, ...]
    stats: ReportStats
