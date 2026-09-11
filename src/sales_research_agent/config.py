"""应用配置与运行时安全边界。"""

from pathlib import Path
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量或本地 .env 文件读取的应用配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tavily_api_key: str | None = None
    deepseek_api_key: str | None = None
    mineru_api_key: str | None = None
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_poll_seconds: float = 3.0
    mineru_timeout_seconds: float = 300.0
    official_hosts: tuple[str, ...] = ()
    trusted_secondary_hosts: tuple[str, ...] = ()
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    live_mode: bool = False
    run_root: Path = Path("var/runs")
    max_questions: int = 4
    max_sources: int = 6
    max_concurrency: int = 3
    deadline_minutes: int = 30
    langgraph_strict_msgpack: bool = True

    @model_validator(mode="after")
    def validate_live_credentials(self) -> Self:
        """联网模式必须同时配置搜索与模型服务密钥。"""
        if self.live_mode and (not self.tavily_api_key or not self.deepseek_api_key):
            raise ValueError("live_mode requires both TAVILY_API_KEY and DEEPSEEK_API_KEY")
        return self
