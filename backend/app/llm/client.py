"""OpenAI-compatible LLM client (works with MiniMax / DeepSeek / any OpenAI-compat API)."""
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@lru_cache
def get_llm() -> ChatOpenAI:
    """Return a singleton ChatOpenAI configured from settings."""
    settings = get_settings()
    if not settings.openai_api_key.get_secret_value():
        raise RuntimeError(
            "OPENAI_API_KEY is empty. Set it in the project-root `.env` "
            "(see backend/.env.example)."
        )
    return ChatOpenAI(
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        model_kwargs={"max_tokens": settings.llm_max_tokens},
    )
