import pytest

from sales_research_agent.domain.models import Source
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository


@pytest.mark.asyncio
async def test_repository_upsert_is_idempotent(repository: SQLiteRepository) -> None:
    source = Source(
        id="src-1",
        run_id="run-1",
        url="https://example.com",
        canonical_url="https://example.com/",
        title="Example",
        source_type="OFFICIAL",
        discovered_by_question_ids=["question-1"],
    )

    first_id = await repository.upsert_source(
        source, operation_key="run-1:source:https://example.com"
    )
    duplicate_id = await repository.upsert_source(
        source, operation_key="run-1:source:https://example.com"
    )

    assert first_id == duplicate_id == source.id
    assert await repository.get_source(source.id) == source
    assert await repository.list_sources("run-1") == [source]
    assert await repository.has_duplicate_operation_keys("run-1") is False


@pytest.mark.asyncio
async def test_repository_keeps_source_revisions_scoped_to_run(
    repository: SQLiteRepository,
) -> None:
    source = Source(
        id="src-1",
        run_id="run-1",
        url="https://example.com",
        canonical_url="https://example.com/",
        title="Example",
        source_type="OFFICIAL",
        discovered_by_question_ids=[],
    )
    await repository.upsert_source(source, operation_key="run-1:source:example")

    assert await repository.count_source_revisions("run-1") == 0
