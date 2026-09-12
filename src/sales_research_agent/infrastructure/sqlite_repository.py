"""基于 SQLite 的领域持久化实现。"""

import json
from pathlib import Path
from typing import ClassVar, Protocol, TypeVar

import aiosqlite
from pydantic import BaseModel

from sales_research_agent.domain.models import (
    ArtifactRef,
    Brief,
    Claim,
    DocumentBlock,
    Evidence,
    Failure,
    Gap,
    ReportVersion,
    ResearchQuestion,
    RunMetadata,
    RunStats,
    Source,
    SourceRevision,
    Verification,
)
from sales_research_agent.domain.repository import DomainRepository

Model = TypeVar("Model", bound=BaseModel)


class JsonModel(Protocol):
    """可序列化为领域 JSON 的模型协议。"""

    def model_dump_json(self) -> str: ...


class PersistedModel(JsonModel, Protocol):
    """仓储所需的最小领域实体协议。"""

    id: str
    run_id: str


class SQLiteRepository(DomainRepository):
    """每次操作打开短连接和短事务的 SQLite 仓储。"""

    _entity_types: ClassVar[dict[str, type[BaseModel]]] = {
        "briefs": Brief,
        "research_questions": ResearchQuestion,
        "sources": Source,
        "source_revisions": SourceRevision,
        "document_blocks": DocumentBlock,
        "evidence": Evidence,
        "claims": Claim,
        "verifications": Verification,
        "gaps": Gap,
        "failures": Failure,
        "report_versions": ReportVersion,
        "artifact_refs": ArtifactRef,
    }

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        """创建 POC 所需表并启用本地 SQLite 约束。"""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("PRAGMA busy_timeout = 5000")
            for table in self._entity_types:
                await connection.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        operation_key TEXT NOT NULL UNIQUE
                    )
                    """
                )
                await connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_run_id ON {table}(run_id)"
                )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_stats (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_metadata (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            await connection.commit()

    async def upsert_brief(self, entity: Brief, operation_key: str) -> str:
        return await self._upsert("briefs", entity, operation_key)

    async def get_brief(self, entity_id: str) -> Brief | None:
        return await self._get("briefs", entity_id, Brief)

    async def list_briefs(self, run_id: str) -> list[Brief]:
        return await self._list("briefs", run_id, Brief)

    async def upsert_research_question(
        self, entity: ResearchQuestion, operation_key: str
    ) -> str:
        return await self._upsert("research_questions", entity, operation_key)

    async def get_research_question(self, entity_id: str) -> ResearchQuestion | None:
        return await self._get("research_questions", entity_id, ResearchQuestion)

    async def list_research_questions(self, run_id: str) -> list[ResearchQuestion]:
        return await self._list("research_questions", run_id, ResearchQuestion)

    async def upsert_source(self, entity: Source, operation_key: str) -> str:
        return await self._upsert("sources", entity, operation_key)

    async def get_source(self, entity_id: str) -> Source | None:
        return await self._get("sources", entity_id, Source)

    async def list_sources(self, run_id: str) -> list[Source]:
        return await self._list("sources", run_id, Source)

    async def upsert_source_revision(self, entity: SourceRevision, operation_key: str) -> str:
        return await self._upsert("source_revisions", entity, operation_key)

    async def get_source_revision(self, entity_id: str) -> SourceRevision | None:
        return await self._get("source_revisions", entity_id, SourceRevision)

    async def list_source_revisions(self, run_id: str) -> list[SourceRevision]:
        return await self._list("source_revisions", run_id, SourceRevision)

    async def upsert_document_block(self, entity: DocumentBlock, operation_key: str) -> str:
        return await self._upsert("document_blocks", entity, operation_key)

    async def get_document_block(self, entity_id: str) -> DocumentBlock | None:
        return await self._get("document_blocks", entity_id, DocumentBlock)

    async def list_document_blocks(self, run_id: str) -> list[DocumentBlock]:
        return await self._list("document_blocks", run_id, DocumentBlock)

    async def upsert_evidence(self, entity: Evidence, operation_key: str) -> str:
        return await self._upsert("evidence", entity, operation_key)

    async def get_evidence(self, entity_id: str) -> Evidence | None:
        return await self._get("evidence", entity_id, Evidence)

    async def list_evidence(self, run_id: str) -> list[Evidence]:
        return await self._list("evidence", run_id, Evidence)

    async def upsert_claim(self, entity: Claim, operation_key: str) -> str:
        return await self._upsert("claims", entity, operation_key)

    async def get_claim(self, entity_id: str) -> Claim | None:
        return await self._get("claims", entity_id, Claim)

    async def list_claims(self, run_id: str) -> list[Claim]:
        return await self._list("claims", run_id, Claim)

    async def upsert_verification(self, entity: Verification, operation_key: str) -> str:
        return await self._upsert("verifications", entity, operation_key)

    async def get_verification(self, entity_id: str) -> Verification | None:
        return await self._get("verifications", entity_id, Verification)

    async def list_verifications(self, run_id: str) -> list[Verification]:
        return await self._list("verifications", run_id, Verification)

    async def upsert_gap(self, entity: Gap, operation_key: str) -> str:
        return await self._upsert("gaps", entity, operation_key)

    async def get_gap(self, entity_id: str) -> Gap | None:
        return await self._get("gaps", entity_id, Gap)

    async def list_gaps(self, run_id: str) -> list[Gap]:
        return await self._list("gaps", run_id, Gap)

    async def upsert_failure(self, entity: Failure, operation_key: str) -> str:
        return await self._upsert("failures", entity, operation_key)

    async def get_failure(self, entity_id: str) -> Failure | None:
        return await self._get("failures", entity_id, Failure)

    async def list_failures(self, run_id: str) -> list[Failure]:
        return await self._list("failures", run_id, Failure)

    async def upsert_report_version(self, entity: ReportVersion, operation_key: str) -> str:
        return await self._upsert("report_versions", entity, operation_key)

    async def get_report_version(self, entity_id: str) -> ReportVersion | None:
        return await self._get("report_versions", entity_id, ReportVersion)

    async def list_report_versions(self, run_id: str) -> list[ReportVersion]:
        return await self._list("report_versions", run_id, ReportVersion)

    async def upsert_artifact_ref(self, entity: ArtifactRef, operation_key: str) -> str:
        return await self._upsert("artifact_refs", entity, operation_key)

    async def get_artifact_ref(self, entity_id: str) -> ArtifactRef | None:
        return await self._get("artifact_refs", entity_id, ArtifactRef)

    async def list_artifact_refs(self, run_id: str) -> list[ArtifactRef]:
        return await self._list("artifact_refs", run_id, ArtifactRef)

    async def append_audit_event(self, run_id: str, event: dict[str, object]) -> None:
        async with self._connect() as connection:
            await connection.execute("BEGIN")
            await connection.execute(
                "INSERT INTO audit_events (run_id, payload) VALUES (?, ?)",
                (run_id, json.dumps(event, ensure_ascii=False, sort_keys=True)),
            )
            await connection.commit()

    async def list_audit_events(self, run_id: str) -> list[dict[str, object]]:
        """按发生顺序读取一个运行的追加式审计事件。"""
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT payload FROM audit_events WHERE run_id = ? ORDER BY id", (run_id,)
            )
            rows = await cursor.fetchall()
            return [json.loads(row[0]) for row in rows]

    async def save_run_metadata(self, metadata: RunMetadata) -> None:
        """保存运行版本与生命周期，不依赖 LangGraph checkpoint。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN")
            await connection.execute(
                """
                INSERT INTO run_metadata (run_id, payload) VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload
                """,
                (metadata.run_id, self._payload(metadata)),
            )
            await connection.commit()

    async def get_run_metadata(self, run_id: str) -> RunMetadata | None:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT payload FROM run_metadata WHERE run_id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            return RunMetadata.model_validate_json(row[0]) if row is not None else None

    async def save_stats(self, stats: RunStats) -> None:
        async with self._connect() as connection:
            await connection.execute("BEGIN")
            await connection.execute(
                """
                INSERT INTO run_stats (run_id, payload) VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload
                """,
                (stats.run_id, self._payload(stats)),
            )
            await connection.commit()

    async def get_stats(self, run_id: str) -> RunStats | None:
        """读取已持久化的运行统计，供审计与离线验收复核。"""
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT payload FROM run_stats WHERE run_id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            return RunStats.model_validate_json(row[0]) if row is not None else None

    async def count_source_revisions(self, run_id: str) -> int:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM source_revisions WHERE run_id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            return int(row[0]) if row is not None else 0

    async def has_duplicate_operation_keys(self, run_id: str) -> bool:
        for table in self._entity_types:
            async with self._connect() as connection:
                cursor = await connection.execute(
                    f"""
                    SELECT operation_key FROM {table}
                    WHERE run_id = ?
                    GROUP BY operation_key HAVING COUNT(*) > 1
                    LIMIT 1
                    """,
                    (run_id,),
                )
                if await cursor.fetchone() is not None:
                    return True
        return False

    async def _upsert(self, table: str, entity: PersistedModel, operation_key: str) -> str:
        payload = self._payload(entity)
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                f"SELECT id FROM {table} WHERE operation_key = ?", (operation_key,)
            )
            existing = await cursor.fetchone()
            if existing is not None:
                await connection.rollback()
                return str(existing[0])

            cursor = await connection.execute(f"SELECT id FROM {table} WHERE id = ?", (entity.id,))
            existing = await cursor.fetchone()
            if existing is None:
                await connection.execute(
                    f"INSERT INTO {table} (id, run_id, payload, operation_key) VALUES (?, ?, ?, ?)",
                    (entity.id, entity.run_id, payload, operation_key),
                )
            else:
                await connection.execute(
                    f"""
                    UPDATE {table}
                    SET run_id = ?, payload = ?, operation_key = ?
                    WHERE id = ?
                    """,
                    (entity.run_id, payload, operation_key, entity.id),
                )
            await connection.commit()
        return entity.id

    async def _get(self, table: str, entity_id: str, model: type[Model]) -> Model | None:
        async with self._connect() as connection:
            cursor = await connection.execute(f"SELECT payload FROM {table} WHERE id = ?", (entity_id,))
            row = await cursor.fetchone()
            return model.model_validate_json(row[0]) if row is not None else None

    async def _list(self, table: str, run_id: str, model: type[Model]) -> list[Model]:
        async with self._connect() as connection:
            cursor = await connection.execute(
                f"SELECT payload FROM {table} WHERE run_id = ? ORDER BY rowid", (run_id,)
            )
            rows = await cursor.fetchall()
            return [model.model_validate_json(row[0]) for row in rows]

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self._database_path)

    @staticmethod
    def _payload(entity: JsonModel) -> str:
        return entity.model_dump_json()
