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
