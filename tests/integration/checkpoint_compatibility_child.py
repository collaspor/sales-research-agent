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


async def run(mode: str, database_path: Path, calls_path: Path) -> dict[str, object]:
    if not STRICT_MSGPACK_ENABLED:
        raise RuntimeError("LANGGRAPH_STRICT_MSGPACK 未在导入前启用")

    calls = _load_calls(calls_path)
    config = {"configurable": {"thread_id": "checkpoint-test"}}
    successful_finished = asyncio.Event()
    successful_pending_write_seen = False

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
            if mode == "crash" and calls["failing"] == 1:
                await successful_finished.wait()
                for _ in range(100):
                    if await successful_write_is_persisted():
                        successful_pending_write_seen = True
                        break
                    await asyncio.sleep(0)
                if not successful_pending_write_seen:
                    raise AssertionError("successful 的 pending write 未持久化")
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

        if mode == "crash":
            try:
                await graph.ainvoke({"completed": []}, config=config)
            except RuntimeError as error:
                if str(error) != "injected crash":
                    raise
            else:
                raise AssertionError("首次调用必须抛出注入的崩溃")
            result: dict[str, object] = {
                "calls": calls,
                "strict_msgpack": STRICT_MSGPACK_ENABLED,
                "successful_pending_write_seen": successful_pending_write_seen,
            }
        elif mode == "resume":
            resumed = await graph.ainvoke(None, config=config)
            result = {
                "calls": calls,
                "completed": resumed["completed"],
                "strict_msgpack": STRICT_MSGPACK_ENABLED,
            }
        else:
            raise ValueError(f"未知运行模式: {mode}")

    _save_calls(calls_path, calls)
    return result


def _load_calls(calls_path: Path) -> dict[str, int]:
    if not calls_path.exists():
        return {"successful": 0, "failing": 0, "join": 0}
    return json.loads(calls_path.read_text(encoding="utf-8"))


def _save_calls(calls_path: Path, calls: dict[str, int]) -> None:
    calls_path.write_text(json.dumps(calls), encoding="utf-8")


if __name__ == "__main__":
    _, mode_argument, database_argument, calls_argument = sys.argv
    output = asyncio.run(run(mode_argument, Path(database_argument), Path(calls_argument)))
    print(json.dumps(output))
