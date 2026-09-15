"""报告输出使用的不可变数据模型。"""

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportItem(BaseModel):
    """报告嵌套项的不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportFact(ReportItem):
    """已批准的公开事实或近期变化。"""

    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    authority: str = "UNCLASSIFIED"


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
    authority: str = "UNCLASSIFIED"
    published_on: date | None = None


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
    official_sources_succeeded: int = 0
    secondary_sources_succeeded: int = 0
    official_coverage: bool = False


class FactTrust(ReportItem):
    """事实在正文中的来源、时效和可信度标签。"""

    authority_code: str
    time_status: str
    confidence: str
    label: str
    source_ids: tuple[str, ...]


class CompositionItem(ReportItem):
    """报告编排器输出项的最小可追溯基类。"""

    text: str
    claim_ids: tuple[str, ...]


class CompositionFinding(CompositionItem):
    """面客前重点事实及其售前意义。"""

    title: str
    presales_significance: str


class OpportunityHypothesis(CompositionItem):
    """仅供会前验证的机会假设，不能等同客户需求。"""

    public_signal: str
    related_capability: str
    validation_needed: str


class DiscoveryQuestion(ReportItem):
    """首次交流建议问题及其来源边界。"""

    category: str
    question: str
    rationale: str
    claim_ids: tuple[str, ...] = ()
    gap_codes: tuple[str, ...] = ()


class ReadableGap(ReportItem):
    """供售前阅读的信息缺口，内部代码仅保留在附录。"""

    title: str
    description: str
    risk_note: str
    suggested_question: str
    gap_codes: tuple[str, ...]


class ExecutiveJudgment(CompositionItem):
    """受约束的会前一句话判断。"""


class ReportComposition(ReportItem):
    """模型或回退逻辑生成的报告编排结果。"""

    executive_judgment: ExecutiveJudgment
    key_findings: tuple[CompositionFinding, ...] = ()
    opportunity_hypotheses: tuple[OpportunityHypothesis, ...] = ()
    discovery_questions: tuple[DiscoveryQuestion, ...] = ()
    readable_gaps: tuple[ReadableGap, ...] = ()


class BriefHeader(ReportItem):
    """报告首页展示的输入背景。"""

    customer_name: str
    scenario: str
    research_goal: str
    known_context: str


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
    brief: BriefHeader | None = None
    composition: ReportComposition | None = None
    composition_mode: str = "FALLBACK"
    generated_on: date = Field(default_factory=lambda: datetime.now(UTC).date())
