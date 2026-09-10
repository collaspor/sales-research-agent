import pytest
from pydantic import ValidationError

from sales_research_agent.config import Settings


def test_live_mode_requires_both_api_keys() -> None:
    with pytest.raises(ValidationError):
        Settings(live_mode=True, tavily_api_key=None, deepseek_api_key=None)


def test_offline_mode_uses_safe_defaults_without_api_keys() -> None:
    settings = Settings(live_mode=False, tavily_api_key=None, deepseek_api_key=None)

    assert settings.live_mode is False
    assert settings.max_sources == 6
    assert settings.max_concurrency == 3
