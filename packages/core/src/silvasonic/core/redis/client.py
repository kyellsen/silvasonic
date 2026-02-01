from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio import Redis
from silvasonic.core.redis.settings import RedisSettings

settings = RedisSettings()


@asynccontextmanager
async def get_redis_client() -> AsyncGenerator[Redis, None]:
    """Async context manager that yields a Redis client.

    The client is closed when the context exits.

    Yields:
        redis.asyncio.Redis: An async Redis client connected to the configured instance.
    """
    client = redis.Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
