"""v2 Redis 客户端：用于 agent 短期上下文存储。"""
from __future__ import annotations

from typing import AsyncIterator

import redis.asyncio as aioredis

from app.config import get_settings

_settings = get_settings()

# 全局单例（连接池自动管理）
redis_client: aioredis.Redis = aioredis.from_url(
    _settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
)


async def get_redis() -> AsyncIterator[aioredis.Redis]:
    """FastAPI 依赖：yield 一个 Redis 客户端。"""
    yield redis_client