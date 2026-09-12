from datetime import UTC, datetime

import pytest

from sales_research_agent.domain.models import RunMetadata, Source
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


@pytest.mark.asyncio
async def test_repository_persists_run_metadata(repository: SQLiteRepository) -> None:
    metadata = RunMetadata(
        run_id="run-1",
        runtime_version=2,
        execution_status="RUNNING",
        report_outcome=None,
        started_at=datetime.now(UTC),
        finished_at=None,
    )

    await repository.save_run_metadata(metadata)

    assert await repository.get_run_metadata("run-1") == metadata


@pytest.mark.asyncio
async def test_repository_lists_audit_events_in_insert_order(
    repository: SQLiteRepository,
) -> None:
    await repository.append_audit_event("run-1", {"event_type": "FIRST", "value": 1})
    await repository.append_audit_event("run-1", {"event_type": "SECOND", "value": 2})

    assert await repository.list_audit_events("run-1") == [
        {"event_type": "FIRST", "value": 1},
        {"event_type": "SECOND", "value": 2},
    ]
