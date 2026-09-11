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
