import pytest
from pydantic import ValidationError

from sales_research_agent.config import Settings


@pytest.mark.parametrize(
    ("tavily_api_key", "deepseek_api_key"),
    [(None, "deepseek-test"), ("tavily-test", None), (None, None)],
)
def test_live_mode_requires_both_api_keys(
    tavily_api_key: str | None, deepseek_api_key: str | None
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            live_mode=True,
            tavily_api_key=tavily_api_key,
            deepseek_api_key=deepseek_api_key,
        )


def test_live_mode_reads_api_keys_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")

    settings = Settings(live_mode=True)

    assert settings.tavily_api_key == "tavily-test"
    assert settings.deepseek_api_key == "deepseek-test"


def test_offline_mode_uses_safe_defaults_without_api_keys() -> None:
    settings = Settings(live_mode=False, tavily_api_key=None, deepseek_api_key=None)

    assert settings.live_mode is False
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-chat"
    assert settings.max_sources == 6
    assert settings.max_concurrency == 3
