from pathlib import Path

import pytest

from sales_research_agent.reporting.models import ReportModel
from tests.fakes import execute_offline_run


@pytest.mark.asyncio
async def test_offline_poc_run_persists_auditable_approved_outputs(tmp_path: Path) -> None:
    """离线验收必须覆盖完整 Graph，而不是分别拼接单元测试。"""
    run_tree = tmp_path / "run-tree"

    offline_run = await execute_offline_run(run_tree)

    assert (run_tree / "domain.sqlite3").is_file()
    assert (run_tree / "checkpoint.sqlite3").is_file()
    assert list((run_tree / "artifacts" / offline_run.run_id / "sources").rglob("*.html"))
    assert list((run_tree / "artifacts" / offline_run.run_id / "sources").rglob("*.txt"))

    versions = await offline_run.repository.list_report_versions(offline_run.run_id)
    assert len(versions) == 1
    report_version = versions[0]
    report_model_ref = await offline_run.repository.get_artifact_ref(
        report_version.report_model_artifact_id
    )
    markdown_ref = await offline_run.repository.get_artifact_ref(report_version.markdown_artifact_id)
    html_ref = await offline_run.repository.get_artifact_ref(report_version.html_artifact_id)
    assert report_model_ref is not None
    assert markdown_ref is not None
    assert html_ref is not None

    report_model = ReportModel.model_validate_json(offline_run.artifacts.read_text(report_model_ref))
    markdown = offline_run.artifacts.read_text(markdown_ref)
    html = offline_run.artifacts.read_text(html_ref)
    approved_ids = {claim.id for claim in await offline_run.repository.list_claims(offline_run.run_id)
                    if claim.status == "APPROVED"}
    reported_ids = {fact.claim_id for fact in report_model.facts}
    assert reported_ids == approved_ids
    assert all(claim_id in markdown for claim_id in reported_ids)
    assert all(claim_id in html for claim_id in reported_ids)
    assert report_model.stats.claims_approved == len(approved_ids)
    rejected_claims = [
        claim for claim in await offline_run.repository.list_claims(offline_run.run_id)
        if claim.status == "REJECTED"
    ]
    assert rejected_claims
    assert all(claim.id not in markdown and claim.id not in html for claim in rejected_claims)
    assert all(claim.text not in markdown and claim.text not in html for claim in rejected_claims)

    stats = await offline_run.repository.get_stats(offline_run.run_id)
    assert stats is not None
    assert stats.sources_succeeded == 1
    assert stats.claims_approved == len(approved_ids)
