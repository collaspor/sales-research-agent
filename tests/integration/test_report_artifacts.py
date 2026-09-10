from pathlib import Path

import pytest

from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.reporting.compiler import ReportPublisher
from sales_research_agent.reporting.models import ReportModel


@pytest.mark.asyncio
async def test_report_publisher_writes_dual_format_artifacts_and_version(
    repository, report_model: ReportModel, tmp_path: Path
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")

    version = await ReportPublisher(artifacts, repository).publish("run-1", report_model)

    assert version.is_active is True
    assert artifacts.read_text(
        await repository.get_artifact_ref(version.report_model_artifact_id)
    ) == report_model.model_dump_json(indent=2)
    assert "data-claim-id=\"claim-1\"" in artifacts.read_text(
        await repository.get_artifact_ref(version.markdown_artifact_id)
    )
    assert "data-evidence-id=\"evidence-1\"" in artifacts.read_text(
        await repository.get_artifact_ref(version.html_artifact_id)
    )


@pytest.mark.asyncio
async def test_publish_failure_keeps_active_report_artifacts_unchanged(
    monkeypatch: pytest.MonkeyPatch, repository, report_model: ReportModel, tmp_path: Path
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    publisher = ReportPublisher(artifacts, repository)
    await publisher.publish("run-1", report_model)
    before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "artifacts" / "run-1" / "reports").iterdir()
    }

    def fail_write(*args: object, **kwargs: object) -> None:
        raise OSError("模拟制品写入失败")

    monkeypatch.setattr(artifacts, "_write_temporary", fail_write)

    with pytest.raises(OSError, match="模拟制品写入失败"):
        await publisher.publish("run-1", report_model)

    after = {
        path.name: path.read_bytes()
        for path in (tmp_path / "artifacts" / "run-1" / "reports").iterdir()
    }
    assert after == before
    assert len(await repository.list_report_versions("run-1")) == 1
