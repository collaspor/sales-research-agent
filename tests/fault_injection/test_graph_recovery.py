import pytest


@pytest.mark.asyncio
async def test_resume_does_not_duplicate_completed_source_revision(crash_harness) -> None:
    with pytest.raises(RuntimeError, match="injected graph crash"):
        await crash_harness.run()
    before = await crash_harness.repository.count_source_revisions(crash_harness.run_id)
    before_fetches = crash_harness.fetcher.calls.count("https://example.com/ok")
    before_claims = {
        item.id for item in await crash_harness.repository.list_claims(crash_harness.run_id)
    }
    before_verifications = {
        item.id for item in await crash_harness.repository.list_verifications(crash_harness.run_id)
    }
    before_gaps = {
        item.id for item in await crash_harness.repository.list_gaps(crash_harness.run_id)
    }
    before_failures = {
        item.id for item in await crash_harness.repository.list_failures(crash_harness.run_id)
    }

    result = await crash_harness.resume()
    after = await crash_harness.repository.count_source_revisions(crash_harness.run_id)

    assert result["execution_status"] == "FINISHED"
    assert after == before + 1
    assert before_fetches == 1
    assert crash_harness.fetcher.calls.count("https://example.com/ok") == 1
    assert {
        item.id for item in await crash_harness.repository.list_claims(crash_harness.run_id)
    } == before_claims
    assert {
        item.id
        for item in await crash_harness.repository.list_verifications(crash_harness.run_id)
    } == before_verifications
    assert before_gaps <= {
        item.id for item in await crash_harness.repository.list_gaps(crash_harness.run_id)
    }
    assert before_failures <= {
        item.id for item in await crash_harness.repository.list_failures(crash_harness.run_id)
    }
    assert await crash_harness.repository.has_duplicate_operation_keys(crash_harness.run_id) is False
