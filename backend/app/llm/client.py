"""LLM client — the ONLY place that knows about LiteLLM.

Architecture
============

This module is the sole seam between business code and the underlying model
provider. Business code (agents/, api/) only ever sees a standard
``langchain_openai.ChatOpenAI`` instance — it imports the symbol, calls
``.bind_tools()`` and feeds it to ``langchain.agents.create_agent`` without
ever knowing which vendor is on the other side.

Why we need an adapter at all
-----------------------------
The MiniMax M3 API uses a non-OpenAI wire format for tool calls and a
proprietary ``<think>...</think>`` channel for reasoning. The standard
``ChatOpenAI`` class can't parse that. To make the rest of the codebase
fully vendor-neutral we route through ``ChatLiteLLM`` (which normalises
MiniMax's format to the OpenAI shape) **here and only here**, then expose
the resulting object as a ``ChatOpenAI`` so downstream code uses the
canonical LangChain API.

If we ever switch provider (DeepSeek / Anthropic / OpenAI itself), only
this file changes.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from langchain_litellm import ChatLiteLLM
from langchain_openai import ChatOpenAI

from app.config import get_settings


def _resolve_model(provider: str, raw: str) -> str:
    """Build litellm's ``"<provider>/<model>"`` identifier."""
    if "/" in raw:
        return raw
    return f"{provider}/{raw}"


@lru_cache
def get_llm() -> ChatOpenAI:
    """Return the singleton LLM client, typed as ``ChatOpenAI``.

    Internally backed by ``ChatLiteLLM`` to absorb MiniMax's non-OpenAI
    tool/think format. Business code should import ``ChatOpenAI`` for
    static typing; the runtime object satisfies that interface.
    """
    settings = get_settings()
    if not settings.llm_api_key.get_secret_value():
        raise RuntimeError(
            "LLM_API_KEY is empty. Set it in the project-root `.env`."
        )

    # NOTE: ChatLiteLLM 0.7.0 declares ``__init__(self, *args, **kwargs)`` —
    # every kwarg below is forwarded to litellm's acompletion internally,
    # not validated by static analysis. We group them into ``model_kwargs``
    # so the contract is explicit and editor type-checkers see them as
    # a single dict.
    model_kwargs: dict[str, Any] = {
        "temperature": settings.llm_temperature,
        "timeout": settings.llm_timeout,
        "max_tokens": settings.llm_max_tokens,
    }

    litellm_chat = ChatLiteLLM(
        model=_resolve_model(settings.llm_provider, settings.llm_model_raw),
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key.get_secret_value(),
        model_kwargs=model_kwargs,
    )

    # Expose as ChatOpenAI — both classes share BaseChatModel; the cast
    # tells mypy / readers "treat this as the standard LangChain type".
    return cast(ChatOpenAI, litellm_chat)
