from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    upstream_base_url: str = "https://api.openai.com/v1"
    upstream_provider: Literal["openai", "deepseek"] = "openai"
    openai_base_url: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    gateway_api_key: str | None = None
    gateway_auth_mode: Literal["static", "database"] = "database"
    gateway_key_pepper: str = ""
    database_url: str | None = None
    request_timeout_seconds: float = 120.0
