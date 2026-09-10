import pytest


@pytest.mark.live
def test_live_selection_contract() -> None:
    """验证 live 标记可单独选择；测试本身不访问网络。"""
    assert True
