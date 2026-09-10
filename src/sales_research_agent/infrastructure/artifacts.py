"""本地文件制品存储。"""

import hashlib
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sales_research_agent.domain.models import ArtifactRef


class ArtifactStore:
    """将单个运行的制品限制在指定根目录内。"""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def write_bytes(
        self,
        run_id: str,
        relative_path: str,
        content: bytes,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        target = self._resolve_target(run_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(suffix=".tmp", dir=target.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            temporary_path.replace(target)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        stored_relative_path = target.relative_to(self._root).as_posix()
        return ArtifactRef(
            id=str(uuid.uuid4()),
            run_id=run_id,
            relative_path=stored_relative_path,
            sha256=hashlib.sha256(content).hexdigest(),
            media_type=media_type,
            size_bytes=len(content),
            created_at=datetime.now(UTC),
        )

    def write_text(
        self,
        run_id: str,
        relative_path: str,
        content: str,
        media_type: str = "text/plain; charset=utf-8",
    ) -> ArtifactRef:
        return self.write_bytes(run_id, relative_path, content.encode("utf-8"), media_type)

    def read_bytes(self, reference: ArtifactRef) -> bytes:
        return self._resolve_reference(reference).read_bytes()

    def read_text(self, reference: ArtifactRef) -> str:
        return self.read_bytes(reference).decode("utf-8")

    def _resolve_target(self, run_id: str, relative_path: str) -> Path:
        path = Path(relative_path)
        if not run_id or path.is_absolute() or ".." in path.parts:
            raise ValueError("relative path must remain within the artifact root")
        return self._ensure_within_root(self._root / run_id / path)

    def _resolve_reference(self, reference: ArtifactRef) -> Path:
        path = Path(reference.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("relative path must remain within the artifact root")
        return self._ensure_within_root(self._root / path)

    def _ensure_within_root(self, target: Path) -> Path:
        resolved = target.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as error:
            raise ValueError("relative path must remain within the artifact root") from error
        return resolved
