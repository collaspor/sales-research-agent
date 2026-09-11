import hashlib
from pathlib import Path

import pytest

from sales_research_agent.infrastructure.artifacts import ArtifactStore


def test_artifact_store_writes_content_and_hash(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    ref = store.write_text("run-1", "sources/src-1/clean.txt", "可信正文")

    assert store.read_text(ref) == "可信正文"
    assert ref.sha256 == hashlib.sha256("可信正文".encode()).hexdigest()
    assert ref.relative_path == "run-1/sources/src-1/clean.txt"
    assert ref.size_bytes == len("可信正文".encode())


def test_artifact_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="relative path"):
        store.write_bytes("run-1", "../outside.txt", b"unsafe")


def test_artifact_store_replaces_target_without_temp_files(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.write_bytes("run-1", "reports/report.md", b"old")
    second = store.write_bytes("run-1", "reports/report.md", b"new")

    assert store.read_bytes(first) == b"new"
    assert store.read_bytes(second) == b"new"
    assert list(tmp_path.rglob("*.tmp")) == []
