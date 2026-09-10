import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sales_research_agent.graph.state import merge_unique


def test_merge_unique_keeps_the_first_occurrence_order() -> None:
    assert merge_unique(["successful", "failing"], ["failing", "join", "successful"]) == [
        "successful",
        "failing",
        "join",
    ]


def test_async_sqlite_saver_keeps_successful_pending_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    environment = os.environ.copy()
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    process = subprocess.run(
        [sys.executable, "-c", _CHECKPOINT_SCRIPT, str(tmp_path / "checkpoint.sqlite3")],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["strict_msgpack"] is True
    assert result["successful_pending_write_seen"] is True
    assert result["calls_after_failure"] == {"successful": 1, "failing": 1, "join": 0}
    assert set(result["completed"]) == {"successful", "failing", "join"}
    assert result["calls_after_resume"] == {"successful": 1, "failing": 2, "join": 1}


_CHECKPOINT_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import json
    import sys
    from pathlib import Path
    from typing import Annotated, TypedDict

    from langgraph.checkpoint.serde._msgpack import STRICT_MSGPACK_ENABLED
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START, StateGraph


    def append(values: list[str], update: list[str]) -> list[str]:
        return list(dict.fromkeys([*values, *update]))


    class State(TypedDict):
        completed: Annotated[list[str], append]


    async def main(database_path: Path) -> dict[str, object]:
        assert STRICT_MSGPACK_ENABLED is True
        calls = {"successful": 0, "failing": 0, "join": 0}
        successful_finished = asyncio.Event()
        successful_pending_write_seen = False
        config = {"configurable": {"thread_id": "checkpoint-test"}}

        async with AsyncSqliteSaver.from_conn_string(str(database_path)) as saver:
            async def successful(_: State) -> dict[str, list[str]]:
                calls["successful"] += 1
                successful_finished.set()
                return {"completed": ["successful"]}

            async def successful_write_is_persisted() -> bool:
                checkpoint = await saver.aget_tuple(config)
                if checkpoint is None:
                    return False
                return any(
                    channel == "completed" and value == ["successful"]
                    for _, channel, value in checkpoint.pending_writes
                )

            async def failing(_: State) -> dict[str, list[str]]:
                nonlocal successful_pending_write_seen

                calls["failing"] += 1
                if calls["failing"] == 1:
                    await successful_finished.wait()
                    for _ in range(100):
                        if await successful_write_is_persisted():
                            successful_pending_write_seen = True
                            break
                        await asyncio.sleep(0)
                    assert successful_pending_write_seen is True
                    raise RuntimeError("injected crash")
                return {"completed": ["failing"]}

            async def join(_: State) -> dict[str, list[str]]:
                calls["join"] += 1
                return {"completed": ["join"]}

            builder = StateGraph(State)
            builder.add_node("successful", successful)
            builder.add_node("failing", failing)
            builder.add_node("join", join)
            builder.add_edge(START, "successful")
            builder.add_edge(START, "failing")
            builder.add_edge(["successful", "failing"], "join")
            builder.add_edge("join", END)
            graph = builder.compile(checkpointer=saver)

            try:
                await graph.ainvoke({"completed": []}, config=config)
            except RuntimeError as error:
                assert str(error) == "injected crash"
            else:
                raise AssertionError("首次调用必须抛出注入的崩溃")

            calls_after_failure = calls.copy()
            assert calls_after_failure == {"successful": 1, "failing": 1, "join": 0}
            result = await graph.ainvoke(None, config=config)

        return {
            "completed": result["completed"],
            "calls_after_failure": calls_after_failure,
            "calls_after_resume": calls,
            "strict_msgpack": STRICT_MSGPACK_ENABLED,
            "successful_pending_write_seen": successful_pending_write_seen,
        }


    print(json.dumps(asyncio.run(main(Path(sys.argv[1])))))
    """
)
