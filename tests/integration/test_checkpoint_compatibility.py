import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NotRequired, get_type_hints

import pytest
from langgraph.graph import END, START, StateGraph

from sales_research_agent.graph.state import PocState, merge_unique


def test_merge_unique_keeps_the_first_occurrence_order() -> None:
    assert merge_unique(["successful", "failing"], ["failing", "join", "successful"]) == [
        "successful",
        "failing",
        "join",
    ]


def test_poc_state_keeps_branch_input_outside_global_state() -> None:
    annotations = get_type_hints(PocState, include_extras=True)

    assert "current_source_id" not in annotations
    assert annotations["report_outcome"] == NotRequired[str | None]


@pytest.mark.asyncio
async def test_poc_state_merges_parallel_id_updates_without_duplicates() -> None:
    async def first_source(_: PocState) -> dict[str, list[str]]:
        return {"source_ids": ["source-1", "source-2"]}

    async def duplicate_source(_: PocState) -> dict[str, list[str]]:
        return {"source_ids": ["source-2", "source-3"]}

    builder = StateGraph(PocState)
    builder.add_node("first_source", first_source)
    builder.add_node("duplicate_source", duplicate_source)
    builder.add_edge(START, "first_source")
    builder.add_edge(START, "duplicate_source")
    builder.add_edge("first_source", END)
    builder.add_edge("duplicate_source", END)

    result = await builder.compile().ainvoke({"source_ids": []})

    assert set(result["source_ids"]) == {"source-1", "source-2", "source-3"}
    assert len(result["source_ids"]) == len(set(result["source_ids"]))


def test_async_sqlite_saver_recovers_pending_writes_after_process_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    database_path = tmp_path / "checkpoint.sqlite3"
    calls_path = tmp_path / "calls.json"

    crash = _run_checkpoint_child("crash", database_path, calls_path)

    assert crash["strict_msgpack"] is True
    assert crash["successful_pending_write_seen"] is True
    assert crash["calls"] == {"successful": 1, "failing": 1, "join": 0}

    resumed = _run_checkpoint_child("resume", database_path, calls_path)

    assert resumed["strict_msgpack"] is True
    assert set(resumed["completed"]) == {"successful", "failing", "join"}
    assert len(resumed["completed"]) == len(set(resumed["completed"]))
    assert resumed["calls"] == {"successful": 1, "failing": 2, "join": 1}


def _run_checkpoint_child(mode: str, database_path: Path, calls_path: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    process = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("checkpoint_compatibility_child.py")),
            mode,
            str(database_path),
            str(calls_path),
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)
