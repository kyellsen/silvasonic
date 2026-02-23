"""Shared Redis connection helper for Silvasonic services (ADR-0019).

Provides a best-effort connection factory that logs warnings on failure
but never raises — services continue operating without Redis.

Usage::

    from silvasonic.core.redis import get_redis_connection

    redis = await get_redis_connection("redis://localhost:6379/0")
    if redis is None:
        # Redis unavailable — heartbeats disabled, service continues
        ...
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


async def get_redis_connection(
    url: str = "redis://localhost:6379/0",
    *,
    decode_responses: bool = True,
    socket_connect_timeout: float = 5.0,
) -> Redis | None:
    """Create a Redis connection with best-effort semantics.

    Attempts to connect and issue a PING. If Redis is unreachable,
    logs a warning and returns ``None`` — the calling service should
    degrade gracefully (e.g., skip heartbeats).

    Args:
        url: Redis connection URL.
        decode_responses: Decode byte responses to strings.
        socket_connect_timeout: Timeout for the initial connection.

    Returns:
        An async Redis client, or ``None`` if the connection failed.
    """
    try:
        redis = Redis.from_url(
            url,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
        )
        await redis.ping()  # type: ignore[misc]
        logger.info("redis_connected", url=url)
        return redis
    except Exception as exc:
        logger.warning(
            "redis_connection_failed",
            url=url,
            error=str(exc),
        )
        return None
