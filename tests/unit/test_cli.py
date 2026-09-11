import json
from pathlib import Path

from typer.testing import CliRunner

from sales_research_agent.cli import app


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

    result = CliRunner().invoke(app, ["run", "--case", str(case_path), "--live"])

    assert result.exit_code == 2
    assert "live_mode requires both" in result.output


def test_inspect_missing_run_does_not_echo_environment_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-secret-sentinel")

    result = CliRunner().invoke(app, ["inspect", "--run-id", "missing", "--run-root", str(tmp_path)])

    assert result.exit_code == 2
    assert "tavily-secret-sentinel" not in result.output
