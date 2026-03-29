"""Redis heartbeat publisher for Silvasonic services (ADR-0019).

Publishes periodic heartbeat payloads to a Redis Pub/Sub channel so the
Web-Interface can display live service status via SSE (Read+Subscribe
pattern, ADR-0017).

Each heartbeat performs two Redis operations:

1. ``SET silvasonic:status:<instance_id> <payload> EX <TTL>`` — snapshot
   readable anytime (TTL: ``interval * HEARTBEAT_TTL_MULTIPLIER``).
2. ``PUBLISH silvasonic:status <payload>`` — live push notification.

Heartbeats are best-effort, fire-and-forget.  A failed publish does NOT
affect the service's operation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Callable
from typing import Any, Protocol

import structlog
from pydantic import BaseModel
from redis.asyncio import Redis

logger = structlog.get_logger()

DEFAULT_HEARTBEAT_INTERVAL_S: float = 10.0
"""Default seconds between heartbeat publishes.

Override per service via ``SILVASONIC_HEARTBEAT_INTERVAL_S``.
Lower values (e.g. 5) improve dashboard responsiveness but increase
Redis traffic.  Higher values (e.g. 30) save resources on
battery-powered deployments.
"""

HEARTBEAT_TTL_MULTIPLIER: int = 3
"""TTL = interval * multiplier.  Ensures the Redis key survives
at least 2 missed heartbeats before expiring."""


StatusProvider = Callable[[], dict[str, Any]]
"""Type alias for callables returning a status dict (health or meta)."""


class ResourceCollectorProtocol(Protocol):
    """Protocol for objects that collect resource metrics."""

    def collect(self) -> dict[str, Any]:
        """Collect and return resource metrics."""
        ...


class HeartbeatPayload(BaseModel):
    """Heartbeat JSON payload schema (ADR-0019 §2.4, ADR-0012).

    All heartbeats use this schema.  Service-specific fields are added
    via the ``meta`` dict (e.g. ``meta.db_level``, ``meta.host_resources``).
    """

    service: str
    instance_id: str
    timestamp: float
    health: dict[str, Any]
    activity: str
    meta: dict[str, Any]


class HeartbeatPublisher:
    """Publishes periodic heartbeat payloads to Redis.

    Args:
        redis: Async Redis client.
        service_name: Canonical service name (e.g. ``recorder``).
        instance_id: Unique instance identifier (e.g. ``ultramic-01``).
        channel: Redis Pub/Sub channel for heartbeats.
        interval: Seconds between heartbeats.
    """

    def __init__(
        self,
        redis: Redis,
        service_name: str,
        instance_id: str = "default",
        channel: str = "silvasonic:status",
        interval: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        """Initialize the heartbeat publisher."""
        self._redis = redis
        self._service_name = service_name
        self._instance_id = instance_id
        self._channel = channel
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._health_fn: StatusProvider | None = None
        self._meta_fn: StatusProvider | None = None
        self._activity: str = "idle"

    def set_health_provider(self, fn: StatusProvider) -> None:
        """Register a callable that returns the health dict."""
        self._health_fn = fn

    def set_meta_provider(self, fn: StatusProvider) -> None:
        """Register a callable that returns additional meta fields."""
        self._meta_fn = fn

    def set_activity(self, activity: str) -> None:
        """Update the current activity label (e.g. ``recording``, ``idle``)."""
        self._activity = activity

    def _build_payload(self, resources: dict[str, Any]) -> HeartbeatPayload:
        """Build the complete heartbeat payload as a Pydantic model."""
        health: dict[str, Any] = {"status": "ok", "components": {}}
        if self._health_fn:
            try:
                health = self._health_fn()
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("health_provider_error", error=type(exc).__name__)
                health = {"status": "error", "components": {}}
            except Exception:
                health = {"status": "error", "components": {}}

        meta: dict[str, Any] = {"resources": resources}
        if self._meta_fn:
            try:
                extra = self._meta_fn()
                if isinstance(extra, dict):
                    meta.update(extra)
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("meta_provider_error", error=type(exc).__name__)
            except Exception:
                logger.debug("meta_provider_failed", exc_info=True)

        return HeartbeatPayload(
            service=self._service_name,
            instance_id=self._instance_id,
            timestamp=round(time.time(), 3),
            health=health,
            activity=self._activity,
            meta=meta,
        )

    async def publish_once(self, resources: dict[str, Any]) -> None:
        """Publish a single heartbeat. Best-effort, fire-and-forget.

        Performs two Redis operations (ADR-0017 Read+Subscribe pattern):
        1. ``SET silvasonic:status:<instance_id> <payload> EX <TTL>``
        2. ``PUBLISH silvasonic:status <payload>``
        """
        payload = self._build_payload(resources)
        json_payload = json.dumps(payload.model_dump())
        key = f"silvasonic:status:{self._instance_id}"
        try:
            ttl = max(30, int(self._interval * HEARTBEAT_TTL_MULTIPLIER))
            await self._redis.set(key, json_payload, ex=ttl)
            await self._redis.publish(self._channel, json_payload)
        except Exception as exc:
            logger.warning("heartbeat_publish_failed", error=str(exc))

    async def _loop(self, resource_collector: ResourceCollectorProtocol) -> None:
        """Internal heartbeat loop."""
        while True:
            try:
                resources = resource_collector.collect()
                await self.publish_once(resources)
            except asyncio.CancelledError:  # pragma: no cover — integration-tested
                break
            except Exception as exc:
                logger.warning("heartbeat_loop_error", error=str(exc))
            await asyncio.sleep(self._interval)

    def start(self, resource_collector: ResourceCollectorProtocol) -> asyncio.Task[None]:
        """Start the heartbeat loop as a background async task.

        Args:
            resource_collector: A ``ResourceCollector`` instance.

        Returns:
            The background asyncio.Task.
        """
        self._task = asyncio.create_task(self._loop(resource_collector))
        return self._task

    async def stop(self) -> None:
        """Cancel the heartbeat loop gracefully."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
