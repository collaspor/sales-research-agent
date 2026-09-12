import pytest


@pytest.mark.asyncio
async def test_graph_builds_report_from_approved_claims(poc_harness) -> None:
    result = await poc_harness.run()

    assert result["execution_status"] == "FINISHED"
    assert result["approved_claim_ids"]
    assert result["report_version_id"]


@pytest.mark.asyncio
async def test_one_source_failure_yields_partial_report(poc_harness) -> None:
    poc_harness.fetcher.fail_for("https://example.com/fail")

    result = await poc_harness.run()

    assert result["successful_source_ids"]
    assert len(result["failed_source_ids"]) == 1
    assert result["report_outcome"] == "PARTIAL"


@pytest.mark.asyncio
async def test_source_fanout_respects_configured_concurrency(poc_harness) -> None:
    poc_harness.fetcher.track_concurrency()

    await poc_harness.run(max_concurrency=3)

    assert poc_harness.fetcher.peak_concurrency <= 3


@pytest.mark.asyncio
async def test_shared_source_researches_every_linked_question(poc_harness) -> None:
    poc_harness.configure_shared_source_questions()

    await poc_harness.run()

    assert poc_harness.fetcher.calls == ["https://example.com/shared"]
    assert [call[0].id for call in poc_harness.model.evidence_calls] == [
        "question-0",
        "question-1",
    ]
    claims = await poc_harness.repository.list_claims(poc_harness.run_id)
    assert {claim.id for claim in claims} == {
        "claim-question-0-source-0-0",
        "claim-question-1-source-0-0",
    }
