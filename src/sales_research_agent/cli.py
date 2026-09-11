"""POC 的受限命令行入口。"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import typer
from pydantic import ValidationError

from sales_research_agent.config import Settings
from sales_research_agent.domain.models import Brief
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.infrastructure.sqlite_repository import SQLiteRepository
from sales_research_agent.ingestion.fetcher import Fetcher
from sales_research_agent.ingestion.url_policy import UrlPolicy
from sales_research_agent.providers.deepseek import DeepSeekProvider
from sales_research_agent.providers.tavily import TavilySearchProvider

app = typer.Typer(help="Evidence-driven public web research POC.", no_args_is_help=True)


@app.command()
def run(
    case: Path = typer.Option(..., exists=True, readable=True),  # noqa: B008
    live: bool = typer.Option(False, help="Explicitly allow real provider calls."),
    run_root: Path | None = typer.Option(None, help="Override local run directory."),  # noqa: B008
) -> None:
    """创建一个新运行；默认离线模式绝不实例化真实 Provider。"""
    if not live:
        raise typer.BadParameter("offline mode refuses real providers; rerun with --live")
    try:
        settings = Settings(live_mode=True, run_root=run_root or Path("var/runs"))
    except ValidationError as error:
        raise typer.BadParameter(str(error.errors()[0]["msg"])) from error
    payload = _load_case(case)
    run_id = str(uuid4())
    asyncio.run(_start_live_run(settings, payload, run_id))
    typer.echo(f"run_id={run_id}")


@app.command()
def resume(
    run_id: str = typer.Option(...),
    run_root: Path | None = typer.Option(None, help="Override local run directory."),  # noqa: B008
) -> None:
    """恢复既有运行，不接受新的 Brief。"""
    try:
        settings = Settings(live_mode=True, run_root=run_root or Path("var/runs"))
    except ValidationError as error:
        raise typer.BadParameter(str(error.errors()[0]["msg"])) from error
    asyncio.run(_resume_live_run(settings, run_id))
    typer.echo(f"resumed_run_id={run_id}")


@app.command()
def inspect(
    run_id: str = typer.Option(...),
    run_root: Path | None = typer.Option(None, help="Override local run directory."),  # noqa: B008
) -> None:
    """输出可审计汇总，不读取或输出任何 Provider 密钥。"""
    root = run_root or Path("var/runs")
    run_directory = root / run_id
    if not (run_directory / "domain.sqlite3").is_file():
        raise typer.BadParameter("run was not found")
    summary = asyncio.run(_inspect_run(run_directory, run_id))
    typer.echo(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _load_case(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter("case must be valid UTF-8 JSON") from error
    required = ("customer_name", "scenario", "known_context", "research_goal")
    if not all(isinstance(raw.get(key), str) and raw[key].strip() for key in required):
        raise typer.BadParameter("case must contain customer_name, scenario, known_context, research_goal")
    return {key: raw[key] for key in required}


async def _start_live_run(settings: Settings, payload: dict[str, str], run_id: str) -> None:
    directory = settings.run_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    repository = SQLiteRepository(directory / "domain.sqlite3")
    await repository.initialize()
    brief = Brief(id=f"brief-{run_id}", run_id=run_id, **payload)
    await repository.upsert_brief(brief, f"{run_id}:brief:{brief.id}")
    await _invoke_graph(settings, directory, repository, run_id, resume=False)


async def _resume_live_run(settings: Settings, run_id: str) -> None:
    directory = settings.run_root / run_id
    if not (directory / "domain.sqlite3").is_file():
        raise typer.BadParameter("run was not found")
    repository = SQLiteRepository(directory / "domain.sqlite3")
    await repository.initialize()
    await _invoke_graph(settings, directory, repository, run_id, resume=True)


async def _invoke_graph(
    settings: Settings, directory: Path, repository: SQLiteRepository, run_id: str, *, resume: bool
) -> None:
    if settings.langgraph_strict_msgpack:
        os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from sales_research_agent.graph.builder import Services, build_poc_graph

    artifacts = ArtifactStore(directory / "artifacts")
    search = TavilySearchProvider(settings.tavily_api_key or "")
    client = httpx.AsyncClient()
    try:
        async with AsyncSqliteSaver.from_conn_string(str(directory / "checkpoint.sqlite3")) as saver:
            graph = build_poc_graph(
                Services(
                    repository=repository, artifacts=artifacts, search=search,
                    model=DeepSeekProvider(settings=settings),
                    fetcher=Fetcher(client, UrlPolicy()), clock=lambda: datetime.now(UTC),
                    max_sources=settings.max_sources, max_questions=settings.max_questions,
                ), saver,
            )
            config = {"configurable": {"thread_id": run_id}, "max_concurrency": settings.max_concurrency}
            if resume:
                await graph.ainvoke(None, config)
            else:
                now = datetime.now(UTC)
                await graph.ainvoke(
                    {
                        "run_id": run_id, "thread_id": run_id, "brief_id": f"brief-{run_id}",
                        "research_question_ids": [], "source_ids": [], "successful_source_ids": [],
                        "failed_source_ids": [], "evidence_ids": [], "claim_ids": [],
                        "approved_claim_ids": [], "rejected_claim_ids": [], "gap_ids": [], "failure_ids": [],
                        "execution_status": "RUNNING", "started_at": now.isoformat(),
                        "deadline_at": (now + timedelta(minutes=settings.deadline_minutes)).isoformat(),
                    }, config,
                )
    finally:
        await client.aclose()
        await search.aclose()


async def _inspect_run(directory: Path, run_id: str) -> dict[str, object]:
    repository = SQLiteRepository(directory / "domain.sqlite3")
    await repository.initialize()
    sources = await repository.list_sources(run_id)
    claims = await repository.list_claims(run_id)
    failures = await repository.list_failures(run_id)
    versions = await repository.list_report_versions(run_id)
    active = next((item for item in reversed(versions) if item.is_active), None)
    return {
        "run_id": run_id,
        "sources": len(sources),
        "failures": len(failures),
        "claims_approved": sum(item.status == "APPROVED" for item in claims),
        "claims_rejected": sum(item.status == "REJECTED" for item in claims),
        "report_path": "reports/report.md" if active is not None else None,
    }
