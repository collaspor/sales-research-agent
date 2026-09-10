from pathlib import Path

import pytest

from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository


@pytest.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    instance = SQLiteRepository(tmp_path / "domain.sqlite3")
    await instance.initialize()
    return instance
