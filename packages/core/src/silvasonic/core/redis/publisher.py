import socket
from typing import Any, Literal

import structlog
from silvasonic.core.redis.client import get_redis_client
from silvasonic.core.schemas.status import (
    LifecycleMessage,
    LifecyclePayloadContent,
    StatusMessage,
    StatusPayloadContent,
)

logger = structlog.get_logger()


class RedisPublisher:
    """Standardized Redis Publisher for Silvasonic services."""

    def __init__(self, service_name: str, instance_id: str | None = None) -> None:
        """Initialize the publisher with service identity."""
        self.service_name = service_name
        self.instance_id = instance_id or socket.gethostname()

    async def publish_status(
        self,
        status: str,  # "online" or "offline" (mapped to health)
        activity: str,
        message: str,
        meta: dict[str, Any] | None = None,
        progress: float | None = None,
    ) -> None:
        """Publish a status heartbeat."""
        health: Literal["healthy", "degraded"] = "healthy" if status == "online" else "degraded"

        msg = StatusMessage(
            service=self.service_name,
            instance_id=self.instance_id,
            payload=StatusPayloadContent(
                health=health,
                activity=activity,
                progress=progress,
                message=message,
                meta=meta or {},
            ),
        )

        await self._publish("silvasonic.status", msg.model_dump_json())

        # Also set key for persistence (TTL 10s)
        key = f"status:{self.service_name}:{self.instance_id}"
        await self._set_with_ttl(key, msg.model_dump_json(), ttl=10)

    async def publish_lifecycle(
        self,
        event: str,  # "started", "stopping", "crashed"
        reason: str,
        version: str | None = None,
        pid: int | None = None,
    ) -> None:
        """Publish a lifecycle event."""
        if event not in ["started", "stopping", "crashed"]:
            logger.warning("invalid_lifecycle_event", event=event)
            event = "crashed"  # Fallback to reported error

        msg = LifecycleMessage(
            event=event,  # type: ignore
            service=self.service_name,
            instance_id=self.instance_id,
            payload=LifecyclePayloadContent(
                version=version,
                pid=pid,
                reason=reason,
            ),
        )

        await self._publish("silvasonic.lifecycle", msg.model_dump_json())

    async def _publish(self, channel: str, message: str) -> None:
        try:
            async with get_redis_client() as redis:
                await redis.publish(channel, message)
        except Exception as e:
            logger.error("redis_publish_failed", channel=channel, error=str(e))

    async def _set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        try:
            async with get_redis_client() as redis:
                await redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.error("redis_set_failed", key=key, error=str(e))
