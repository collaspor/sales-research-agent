import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sales_research_agent.cli as cli_module
from sales_research_agent.cli import _inspect_run, _resume_live_run, app
from sales_research_agent.config import Settings
from sales_research_agent.domain.models import RunMetadata, RunStats
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository


def test_run_refuses_real_providers_when_live_flag_is_absent(tmp_path: Path) -> None:
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps({"customer_name": "Example"}), encoding="utf-8")

    result = CliRunner().invoke(app, ["run", "--case", str(case_path)])

    assert result.exit_code == 2
    assert "offline mode" in result.output


def test_live_run_validates_provider_keys_before_network(tmp_path: Path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps({"customer_name": "Example"}), encoding="utf-8")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["run", "--case", str(case_path), "--live"])

    assert result.exit_code == 2
    assert "live_mode requires both" in result.output


def test_inspect_missing_run_does_not_echo_environment_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-secret-sentinel")

    result = CliRunner().invoke(app, ["inspect", "--run-id", "missing", "--run-root", str(tmp_path)])

    assert result.exit_code == 2
    assert "tavily-secret-sentinel" not in result.output


@pytest.mark.asyncio
async def test_inspect_reports_persisted_runtime_and_call_summary(tmp_path: Path) -> None:
    run_id = "run-1"
    directory = tmp_path / run_id
    repository = SQLiteRepository(directory / "domain.sqlite3")
    await repository.initialize()
    started_at = datetime.now(UTC) - timedelta(seconds=10)
    finished_at = datetime.now(UTC)
    await repository.save_run_metadata(
        RunMetadata(
            run_id=run_id,
            runtime_version=2,
            execution_status="FINISHED",
            report_outcome="COMPLETED",
            started_at=started_at,
            finished_at=finished_at,
        )
    )
    await repository.save_stats(
        RunStats(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            search_calls=1,
            http_calls=2,
            pdf_calls=3,
            model_calls=4,
            sources_succeeded=0,
            sources_failed=0,
            claims_approved=0,
            claims_rejected=0,
        )
    )

    summary = await _inspect_run(directory, run_id)

    assert summary["runtime_version"] == 2
    assert summary["execution_status"] == "FINISHED"
    assert summary["report_outcome"] == "COMPLETED"
    assert summary["duration_seconds"] >= 10
    assert summary["search_calls"] == 1
    assert summary["http_calls"] == 2
    assert summary["pdf_calls"] == 3
    assert summary["model_calls"] == 4


@pytest.mark.asyncio
async def test_resume_rejects_legacy_run_before_provider_construction(tmp_path: Path) -> None:
    run_id = "legacy"
    repository = SQLiteRepository(tmp_path / run_id / "domain.sqlite3")
    await repository.initialize()
    with sqlite3.connect(tmp_path / run_id / "domain.sqlite3") as connection:
        connection.execute("DROP TABLE run_metadata")

    with pytest.raises(Exception, match="runtime version 1"):
        await _resume_live_run(Settings(run_root=tmp_path), run_id)

    with sqlite3.connect(tmp_path / run_id / "domain.sqlite3") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "run_metadata" not in tables


@pytest.mark.asyncio
async def test_inspect_legacy_run_does_not_modify_its_schema(tmp_path: Path) -> None:
    run_id = "legacy"
    directory = tmp_path / run_id
    repository = SQLiteRepository(directory / "domain.sqlite3")
    await repository.initialize()
    with sqlite3.connect(directory / "domain.sqlite3") as connection:
        connection.execute("DROP TABLE run_metadata")

    summary = await _inspect_run(directory, run_id)

    assert summary["runtime_version"] == 1
    with sqlite3.connect(directory / "domain.sqlite3") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "run_metadata" not in tables


@pytest.mark.asyncio
async def test_new_run_marks_metadata_failed_when_graph_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_graph(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("controlled graph failure")

    monkeypatch.setattr(cli_module, "_invoke_graph", fail_graph)
    settings = Settings(run_root=tmp_path)
    payload = {
        "customer_name": "示例客户",
        "scenario": "首次交流",
        "known_context": "公开信息",
        "research_goal": "核验事实",
    }

    with pytest.raises(RuntimeError, match="controlled graph failure"):
        await cli_module._start_live_run(settings, payload, "run-failed")

    repository = SQLiteRepository(tmp_path / "run-failed" / "domain.sqlite3")
    metadata = await repository.get_run_metadata("run-failed")
    assert metadata is not None
    assert metadata.execution_status == "FAILED"
    assert metadata.report_outcome == "FAILED"
    assert metadata.finished_at is not None


@pytest.mark.asyncio
async def test_resume_marks_metadata_failed_when_graph_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-resume-failed"
    repository = SQLiteRepository(tmp_path / run_id / "domain.sqlite3")
    await repository.initialize()
    await repository.save_run_metadata(
        RunMetadata(
            run_id=run_id,
            runtime_version=2,
            execution_status="RUNNING",
            report_outcome=None,
            started_at=datetime.now(UTC),
            finished_at=None,
        )
    )

    async def fail_graph(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("controlled resume failure")

    monkeypatch.setattr(cli_module, "_invoke_graph", fail_graph)

    with pytest.raises(RuntimeError, match="controlled resume failure"):
        await _resume_live_run(Settings(run_root=tmp_path), run_id)

    metadata = await repository.get_run_metadata(run_id)
    assert metadata is not None
    assert metadata.execution_status == "FAILED"
    assert metadata.report_outcome == "FAILED"
