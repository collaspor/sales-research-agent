import pytest


@pytest.mark.asyncio
async def test_resume_does_not_duplicate_completed_source_revision(crash_harness) -> None:
    with pytest.raises(RuntimeError, match="injected graph crash"):
        await crash_harness.run()
    before = await crash_harness.repository.count_source_revisions(crash_harness.run_id)

    result = await crash_harness.resume()
    after = await crash_harness.repository.count_source_revisions(crash_harness.run_id)

    assert result["execution_status"] == "FINISHED"
    assert after == before + 1
    assert await crash_harness.repository.has_duplicate_operation_keys(crash_harness.run_id) is False
