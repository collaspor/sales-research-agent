from datetime import UTC, datetime, timedelta

import pytest

from sales_research_agent.infrastructure.telemetry import (
    AuditExternalCallRecorder,
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
    assert events[1]["duration_ms"] == 12


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
