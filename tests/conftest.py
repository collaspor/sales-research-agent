from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository
from sales_research_agent.ingestion.extractor import HtmlExtractor
from sales_research_agent.ingestion.fetcher import Fetcher
from sales_research_agent.ingestion.ingestor import HtmlIngestor
from sales_research_agent.ingestion.url_policy import UrlPolicy
from sales_research_agent.reporting.models import (
    ReportEvidence,
    ReportFact,
    ReportModel,
    ReportSource,
    ReportStats,
)
from tests.fakes import FixtureTransport


@dataclass(slots=True)
class RunStore:
    """静态 HTML 摄取集成测试所需的真实存储与受控 HTTP 组合。"""

    artifacts: ArtifactStore
    repository: SQLiteRepository
    transport: FixtureTransport
    fetcher: Fetcher
    ingestor: HtmlIngestor


@pytest.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    instance = SQLiteRepository(tmp_path / "domain.sqlite3")
    await instance.initialize()
    return instance


@pytest.fixture
async def run_store(tmp_path: Path) -> RunStore:
    """将 fixture.test 映射到公开地址，生产路径没有测试主机例外。"""
    repository = SQLiteRepository(tmp_path / "domain.sqlite3")
    await repository.initialize()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    transport = FixtureTransport([])
    client = httpx.AsyncClient(transport=transport)
    policy = UrlPolicy(resolver=lambda host: ["93.184.216.34"] if host == "fixture.test" else [])
    fetcher = Fetcher(client, policy)
    ingestor = HtmlIngestor(fetcher, HtmlExtractor(), artifacts, repository)
    try:
        yield RunStore(artifacts, repository, transport, fetcher, ingestor)
    finally:
        await client.aclose()


@pytest.fixture
def report_model() -> ReportModel:
    """提供双格式报告的最小可信数据集。"""
    return ReportModel(
        declaration="本报告仅基于公开信息，不代表客户存在任何需求。",
        summary="已核验一条公开事实。",
        facts=(
            ReportFact(
                claim_id="claim-1",
                text="示例客户发布了年度报告。",
                evidence_ids=("evidence-1",),
                source_ids=("source-1",),
            ),
        ),
        recent_changes=(),
        inferences=(),
        questions=(),
        gaps=(),
        failures=(),
        sources=(
            ReportSource(
                source_id="source-1",
                title="示例来源",
                url="https://example.com/report",
            ),
        ),
        evidence_index=(
            ReportEvidence(
                evidence_id="evidence-1",
                quote="示例客户发布了年度报告。",
                source_id="source-1",
            ),
        ),
        stats=ReportStats(sources_succeeded=1, sources_failed=0, claims_approved=1),
    )


@pytest.fixture
def malicious_report_model(report_model: ReportModel) -> ReportModel:
    """外部来源文本必须在 HTML 输出中保持为文本而非标签。"""
    return report_model.model_copy(
        update={
            "facts": (
                ReportFact(
                    claim_id="claim-1",
                    text="<script>alert(1)</script>",
                    evidence_ids=("evidence-1",),
                    source_ids=("source-1",),
                ),
            )
        }
    )
