"""Application settings loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "thinkcanvas"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+asyncpg://thinkcanvas:thinkcanvas@localhost:5432/thinkcanvas"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
