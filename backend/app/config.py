"""Application settings loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root `.env` is the single source of truth (gitignored).
# backend/app/config.py -> backend/app/ -> backend/ -> project root
project_root = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = project_root / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "thinkcanvas"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+asyncpg://thinkcanvas:thinkcanvas@localhost:5432/thinkcanvas"
    )

    # LLM — all model-format quirks (MiniMax thinking blocks, tool-call
    # tags, etc.) are handled by embedded LiteLLM (via langchain-litellm);
    # this layer only holds endpoint / credentials / generation params.
    # See app.llm.client.
    llm_provider: str = "openai"  # litellm provider prefix, e.g. "openai" / "deepseek"
    llm_api_base: str = "https://api.minimaxi.com/v1"
    llm_api_key: SecretStr = SecretStr("")  # 必填：填进根 .env
    llm_model_raw: str = "MiniMax-M3"  # raw upstream model name (no provider prefix)
    llm_timeout: int = 120  # seconds; cover long-thinking LLM responses
    llm_max_tokens: int = 4000
    llm_temperature: float = 0.2
    llm_max_retries: int = 2  # retry this many times after the first attempt

    # Manim rendering
    manim_timeout: int = 60
    manim_max_cpu: int = 1
    manim_max_mem: int = 2048
    manim_default_quality: str = "m"  # single letter: l|m|h|p|k

    # CORS
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
