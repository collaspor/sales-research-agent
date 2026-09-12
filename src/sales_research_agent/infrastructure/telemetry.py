"""以追加式审计事件记录外部调用，不保存请求正文或密钥。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sales_research_agent.domain.repository import DomainRepository


class ExternalCallRecorder(Protocol):
    """Provider 所依赖的最小两阶段遥测端口。"""

    async def start(self, *, provider: str, operation: str) -> str: ...

    async def finish(self, call_id: str, *, status: str) -> None: ...


class NullExternalCallRecorder:
    """未装配持久化遥测时保持 Provider 向后兼容。"""

    async def start(self, *, provider: str, operation: str) -> str:
        del provider, operation
        return str(uuid4())

    async def finish(self, call_id: str, *, status: str) -> None:
        del call_id, status


class AuditExternalCallRecorder:
    """把调用开始和结束写入运行自己的 SQLite 审计流。"""

    def __init__(
        self,
        repository: DomainRepository,
        run_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._run_id = run_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._started: dict[str, datetime] = {}

    async def start(self, *, provider: str, operation: str) -> str:
        call_id = str(uuid4())
        occurred_at = self._clock()
        self._started[call_id] = occurred_at
        await self._repository.append_audit_event(
            self._run_id,
            {
                "event_type": "CALL_STARTED",
                "call_id": call_id,
                "provider": provider,
                "operation": operation,
                "occurred_at": occurred_at.isoformat(),
            },
        )
        return call_id

    async def finish(self, call_id: str, *, status: str) -> None:
        occurred_at = self._clock()
        started_at = self._started.pop(call_id, occurred_at)
        duration_ms = int((occurred_at - started_at).total_seconds() * 1000)
        await self._repository.append_audit_event(
            self._run_id,
            {
                "event_type": "CALL_FINISHED",
                "call_id": call_id,
                "status": status,
                "duration_ms": max(duration_ms, 0),
                "occurred_at": occurred_at.isoformat(),
            },
        )


@dataclass(frozen=True, slots=True)
class ExternalCallSummary:
    search_calls: int = 0
    http_calls: int = 0
    pdf_calls: int = 0
    model_calls: int = 0
    interrupted_calls: int = 0


def summarize_external_calls(events: list[dict[str, object]]) -> ExternalCallSummary:
    """按 started 事件统计请求尝试，并披露没有结束事件的调用。"""
    started: dict[str, str] = {}
    finished: set[str] = set()
    for event in events:
        call_id = event.get("call_id")
        if not isinstance(call_id, str):
            continue
        if event.get("event_type") == "CALL_STARTED":
            provider = event.get("provider")
            if isinstance(provider, str):
                started.setdefault(call_id, provider)
        elif event.get("event_type") == "CALL_FINISHED":
            finished.add(call_id)

    return ExternalCallSummary(
        search_calls=sum(provider == "tavily" for provider in started.values()),
        http_calls=sum(provider == "fetcher" for provider in started.values()),
        pdf_calls=sum(provider == "mineru" for provider in started.values()),
        model_calls=sum(provider == "deepseek" for provider in started.values()),
        interrupted_calls=len(set(started) - finished),
    )
