"""以追加式审计事件记录外部调用，不保存请求正文或密钥。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sales_research_agent.domain.models import Failure
from sales_research_agent.domain.repository import DomainRepository


class TelemetryWriteError(RuntimeError):
    """外部调用遥测无法可靠持久化。"""


class ExternalCallRecorder(Protocol):
    """Provider 所依赖的最小两阶段遥测端口。"""

    async def start(
        self,
        *,
        provider: str,
        operation: str,
        attempt: int = 1,
        related_entity_id: str | None = None,
    ) -> str: ...

    async def finish(self, call_id: str, *, status: str) -> None: ...


class NullExternalCallRecorder:
    """未装配持久化遥测时保持 Provider 向后兼容。"""

    async def start(
        self,
        *,
        provider: str,
        operation: str,
        attempt: int = 1,
        related_entity_id: str | None = None,
    ) -> str:
        del provider, operation, attempt, related_entity_id
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
        self._started: dict[str, tuple[datetime, str, str, int, str | None]] = {}

    async def start(
        self,
        *,
        provider: str,
        operation: str,
        attempt: int = 1,
        related_entity_id: str | None = None,
    ) -> str:
        call_id = str(uuid4())
        occurred_at = self._clock()
        self._started[call_id] = (
            occurred_at,
            provider,
            operation,
            attempt,
            related_entity_id,
        )
        try:
            await self._repository.append_audit_event(
                self._run_id,
                {
                    "event_type": "CALL_STARTED",
                    "call_id": call_id,
                    "provider": provider,
                    "operation": operation,
                    "attempt": attempt,
                    "related_entity_id": related_entity_id,
                    "occurred_at": occurred_at.isoformat(),
                },
            )
        except Exception:  # noqa: BLE001 - 存储端异常类型不受此适配器控制
            self._started.pop(call_id, None)
            await self._raise_write_failure(call_id, "START", related_entity_id)
        return call_id

    async def finish(self, call_id: str, *, status: str) -> None:
        occurred_at = self._clock()
        started_at, provider, operation, attempt, related_entity_id = self._started.pop(
            call_id,
            (occurred_at, "unknown", "unknown", 1, None),
        )
        duration_ms = int((occurred_at - started_at).total_seconds() * 1000)
        try:
            await self._repository.append_audit_event(
                self._run_id,
                {
                    "event_type": "CALL_FINISHED",
                    "call_id": call_id,
                    "provider": provider,
                    "operation": operation,
                    "attempt": attempt,
                    "status": status,
                    "duration_ms": max(duration_ms, 0),
                    "related_entity_id": related_entity_id,
                    "occurred_at": occurred_at.isoformat(),
                },
            )
        except Exception:  # noqa: BLE001 - 存储端异常类型不受此适配器控制
            await self._raise_write_failure(call_id, "FINISH", related_entity_id)

    async def _raise_write_failure(
        self,
        call_id: str,
        phase: str,
        related_entity_id: str | None,
    ) -> None:
        """尽力保存脱敏失败；无论二次写入结果如何都以受控异常终止。"""
        failure = Failure(
            id=f"failure-telemetry-{call_id}-{phase.lower()}",
            run_id=self._run_id,
            operation="TELEMETRY",
            code="TELEMETRY_WRITE_FAILED",
            retryable=True,
            message="外部调用遥测写入失败，未记录请求正文或密钥。",
            related_entity_id=related_entity_id or self._run_id,
        )
        try:
            await self._repository.upsert_failure(
                failure,
                f"{self._run_id}:failure:{failure.id}",
            )
        except Exception:  # noqa: BLE001 - 二次写入失败时仍须抛出统一异常
            failure_persisted = False
        else:
            failure_persisted = True
        del failure_persisted
        raise TelemetryWriteError("external call telemetry could not be persisted") from None


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
