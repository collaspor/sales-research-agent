from pathlib import Path

import pytest

from tests.fakes import execute_offline_run


@pytest.fixture
def run_tree(tmp_path: Path) -> Path:
    return tmp_path / "run-tree"


@pytest.mark.asyncio
async def test_run_tree_does_not_contain_provider_keys(run_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """完整离线运行不得把环境中的 Provider 密钥持久化。"""
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-secret-sentinel")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret-sentinel")

    await execute_offline_run(run_tree)

    payload = b"".join(path.read_bytes() for path in run_tree.rglob("*") if path.is_file())
    assert b"tavily-secret-sentinel" not in payload
    assert b"deepseek-secret-sentinel" not in payload
