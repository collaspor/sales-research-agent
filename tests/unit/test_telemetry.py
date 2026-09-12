from datetime import UTC, datetime, timedelta

import pytest

from sales_research_agent.infrastructure.telemetry import (
    AuditExternalCallRecorder,
    TelemetryWriteError,
    summarize_external_calls,
)


@pytest.mark.asyncio
async def test_recorder_persists_started_and_finished_events(repository) -> None:
    current = datetime.now(UTC)
    recorder = AuditExternalCallRecorder(repository, "run-1", clock=lambda: current)

    call_id = await recorder.start(provider="deepseek", operation="plan")
    current += timedelta(milliseconds=12)
    await recorder.finish(call_id, status="SUCCESS")

    events = await repository.list_audit_events("run-1")
    assert [event["event_type"] for event in events] == ["CALL_STARTED", "CALL_FINISHED"]
    assert events[0]["call_id"] == events[1]["call_id"] == call_id
    assert events[1]["provider"] == "deepseek"
    assert events[1]["operation"] == "plan"
    assert events[1]["attempt"] == 1
    assert events[1]["duration_ms"] == 12


@pytest.mark.asyncio
async def test_recorder_persists_attempt_and_related_entity(repository) -> None:
    recorder = AuditExternalCallRecorder(repository, "run-1")

    await recorder.start(
        provider="tavily",
        operation="search",
        attempt=2,
        related_entity_id="question-1",
    )

    event = (await repository.list_audit_events("run-1"))[0]
    assert event["attempt"] == 2
    assert event["related_entity_id"] == "question-1"


@pytest.mark.asyncio
async def test_recorder_start_fails_closed_without_leaking_storage_error(
    repository, monkeypatch
) -> None:
    async def fail_append(run_id: str, event: dict[str, object]) -> None:
        del run_id, event
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(repository, "append_audit_event", fail_append)
    recorder = AuditExternalCallRecorder(repository, "run-1")

    with pytest.raises(TelemetryWriteError) as raised:
        await recorder.start(
            provider="deepseek",
            operation="plan",
            related_entity_id="brief-1",
        )

    failures = await repository.list_failures("run-1")
    assert len(failures) == 1
    assert failures[0].code == "TELEMETRY_WRITE_FAILED"
    assert failures[0].related_entity_id == "brief-1"
    assert "secret" not in str(raised.value)
    assert "secret" not in failures[0].message


@pytest.mark.asyncio
async def test_recorder_finish_fails_closed_and_persists_safe_failure(
    repository, monkeypatch
) -> None:
    original_append = repository.append_audit_event
    calls = 0

    async def fail_second_append(run_id: str, event: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("secret database detail")
        await original_append(run_id, event)

    monkeypatch.setattr(repository, "append_audit_event", fail_second_append)
    recorder = AuditExternalCallRecorder(repository, "run-1")
    call_id = await recorder.start(
        provider="fetcher",
        operation="fetch",
        related_entity_id="source-1",
    )

    with pytest.raises(TelemetryWriteError):
        await recorder.finish(call_id, status="SUCCESS")

    failures = await repository.list_failures("run-1")
    assert len(failures) == 1
    assert failures[0].related_entity_id == "source-1"


@pytest.mark.asyncio
async def test_summary_survives_recorder_reconstruction(repository) -> None:
    first = AuditExternalCallRecorder(repository, "run-1")
    first_call = await first.start(provider="tavily", operation="search")
    await first.finish(first_call, status="SUCCESS")

    second = AuditExternalCallRecorder(repository, "run-1")
    second_call = await second.start(provider="deepseek", operation="plan")
    await second.finish(second_call, status="SUCCESS")

    events = await repository.list_audit_events("run-1")
    summary = summarize_external_calls(events)
    assert first_call != second_call
    assert summary.search_calls == 1
    assert summary.model_calls == 1
    assert summary.interrupted_calls == 0


@pytest.mark.asyncio
async def test_skipped_request_does_not_create_telemetry(repository) -> None:
    AuditExternalCallRecorder(repository, "run-1")

    events = await repository.list_audit_events("run-1")

    assert events == []
    assert summarize_external_calls(events).interrupted_calls == 0


@pytest.mark.asyncio
async def test_summary_counts_started_calls_and_discloses_interrupted_calls(repository) -> None:
    recorder = AuditExternalCallRecorder(repository, "run-1")
    completed = await recorder.start(provider="tavily", operation="search")
    await recorder.finish(completed, status="SUCCESS")
    await recorder.start(provider="fetcher", operation="fetch")
    await recorder.start(provider="mineru", operation="submit")
    await recorder.start(provider="deepseek", operation="verify_support")

    summary = summarize_external_calls(await repository.list_audit_events("run-1"))

    assert summary.search_calls == 1
    assert summary.http_calls == 1
    assert summary.pdf_calls == 1
    assert summary.model_calls == 1
    assert summary.interrupted_calls == 3
