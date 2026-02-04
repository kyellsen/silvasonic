import socket
from typing import Any, Literal

import structlog
from silvasonic.core.redis.client import get_redis_client
from silvasonic.core.schemas.audit import AuditMessage
from silvasonic.core.schemas.control import ControlMessage, ControlPayloadContent
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
        self._last_error_time = 0.0
        self._error_throttle_interval = 60.0  # Seconds

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
            logger.warning("invalid_lifecycle_event", lifecycle_event=event)
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

        await self._publish_stream("stream:lifecycle", msg.model_dump_json())

    async def publish_control(
        self,
        command: str,
        initiator: str,
        target_service: str,
        target_instance: str = "*",
        params: dict[str, Any] | None = None,
    ) -> None:
        """Publish a control command."""
        msg = ControlMessage(
            command=command,
            initiator=initiator,
            target_service=target_service,
            target_instance=target_instance,
            payload=ControlPayloadContent(params=params or {}),
        )
        # Use Stream for reliability
        await self._publish_stream("stream:control", msg.model_dump_json())

    async def publish_audit(
        self,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        """Publish an audit event."""
        msg = AuditMessage(
            event=event,
            service=self.service_name,
            instance_id=self.instance_id,
            payload=payload,
        )
        # Use Stream for persistence/replay
        await self._publish_stream("stream:audit", msg.model_dump_json())

    async def _publish(self, channel: str, message: str) -> None:
        try:
            async with get_redis_client() as redis:
                await redis.publish(channel, message)
            self._reset_error_state()
        except Exception as e:
            self._log_error_throttled("redis_publish_failed", error=str(e), channel=channel)

    async def _publish_stream(self, stream: str, message: str) -> None:
        """Publish a message to a Redis Stream."""
        try:
            async with get_redis_client() as redis:
                # XADD stream * data value
                # We store the JSON payload under the key "json"
                await redis.xadd(stream, {"json": message})
            self._reset_error_state()
        except Exception as e:
            self._log_error_throttled("redis_stream_publish_failed", error=str(e), stream=stream)

    async def _set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        try:
            async with get_redis_client() as redis:
                await redis.set(key, value, ex=ttl)
            self._reset_error_state()
        except Exception as e:
            self._log_error_throttled("redis_set_failed", error=str(e), key=key)

    def _log_error_throttled(self, event: str, **kwargs: Any) -> None:
        """Log error with throttling to prevent log pollution."""
        now = __import__("time").time()
        if now - self._last_error_time > self._error_throttle_interval:
            logger.error(event, **kwargs)
            self._last_error_time = now
        else:
            # Log as debug to keep trace but reduce noise level
            logger.debug(f"{event} (throttled)", **kwargs)

    def _reset_error_state(self) -> None:
        """Reset error state on successful operation."""
        if self._last_error_time > 0:
            logger.info("redis_connection_restored", service=self.service_name)
            self._last_error_time = 0.0
