"""Live Log Forwarder — streams Tier 2 container logs via Redis Pub/Sub (ADR-0022).

Continuously follows stdout of all managed Tier 2 containers and publishes
each log line as JSON to the ``silvasonic:logs`` Redis channel.

The forwarder is **fire-and-forget**: if no subscriber is connected, Redis
discards the messages.  No persistence, no backpressure.

Architecture::

    Service → stdout (structlog JSON) → Controller (podman logs --follow)
    → PUBLISH silvasonic:logs → Web-Interface (SSE) → Browser

Usage::

    forwarder = LogForwarder(podman_client, redis_url="redis://redis:6379/0")
    asyncio.create_task(forwarder.run())
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, NoReturn

import structlog

log = structlog.get_logger()

# Redis channel for live log streaming (ADR-0022)
LOGS_CHANNEL = "silvasonic:logs"

# How often to poll for new/removed containers (seconds).
POLL_INTERVAL_S: float = 1.0


def _parse_log_line(
    raw_line: str,
    *,
    service: str,
    instance_id: str,
    container_name: str,
) -> dict[str, Any]:
    """Parse a single log line into the ADR-0022 payload schema.

    Attempts to parse as JSON (structlog output).  If parsing fails
    (e.g. Python traceback, startup banner), wraps the line in a
    fallback structure with ``level: "raw"``.

    Returns:
        Dict matching the ADR-0022 log payload schema.
    """
    base: dict[str, Any] = {
        "service": service,
        "instance_id": instance_id,
        "container_name": container_name,
    }

    try:
        parsed = json.loads(raw_line)
        if isinstance(parsed, dict):
            base["level"] = parsed.get("level", "info")
            base["message"] = parsed.get("event", parsed.get("message", raw_line))
            base["timestamp"] = parsed.get("timestamp", _iso_now())
            # Preserve any extra structlog fields
            for key in ("logger", "exc_info", "stack_info"):
                if key in parsed:
                    base[key] = parsed[key]
            return base
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Fallback: non-JSON line → wrap as raw
    base["level"] = "raw"
    base["message"] = raw_line
    base["timestamp"] = _iso_now()
    return base


def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class LogForwarder:
    """Forward Tier 2 container logs to Redis Pub/Sub (ADR-0022).

    Tracks managed containers by periodically polling the Podman client.
    For each running container, an asyncio task follows its logs via
    ``container.logs(stream=True, follow=True)`` and publishes each
    line to the ``silvasonic:logs`` Redis channel.

    The forwarder is resilient to:
    - Container restarts (follow task ends, next poll spawns a new one)
    - Redis disconnections (reconnects with backoff)
    - Non-JSON log output (wrapped in fallback payload)
    """

    def __init__(
        self,
        podman_client: Any,
        redis_url: str = "redis://localhost:6379/0",
        *,
        poll_interval: float = POLL_INTERVAL_S,
    ) -> None:
        """Initialize with a Podman client and Redis URL.

        Args:
            podman_client: A ``SilvasonicPodmanClient`` instance.
            redis_url: Redis connection URL.
            poll_interval: Seconds between container list polls.
        """
        self._podman = podman_client
        self._redis_url = redis_url
        self._poll_interval = poll_interval
        # container_name → asyncio.Task following that container's logs
        self._follow_tasks: dict[str, asyncio.Task[None]] = {}

    async def run(self) -> NoReturn:
        """Main loop: track managed containers and forward their logs.

        Polls ``list_managed_containers()`` every ``poll_interval`` seconds.
        For each new container: spawns a follow task.
        For each removed container: cancels its follow task.
        """
        import redis.asyncio as aioredis

        while True:
            redis: Any = None
            try:
                redis = aioredis.from_url(self._redis_url)
                log.info("log_forwarder.connected", channel=LOGS_CHANNEL)

                while True:
                    await self._sync_follow_tasks(redis)
                    await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                await self._cancel_all_tasks()
                raise
            except Exception:
                log.warning("log_forwarder.error", reconnect_in=5)
                await self._cancel_all_tasks()
                await asyncio.sleep(5)
            finally:
                if redis is not None:
                    await redis.aclose()

    async def _sync_follow_tasks(self, redis: Any) -> None:
        """Synchronize follow tasks with currently running containers.

        - Start follow tasks for new containers.
        - Cancel follow tasks for removed containers.
        - Clean up completed/failed tasks.
        """
        if not self._podman.is_connected:
            return

        # Get currently managed containers (synchronous → to_thread)
        containers = await asyncio.to_thread(
            self._podman.list_managed_containers,
        )
        current_names = {str(c.get("name", "")) for c in containers if c.get("name")}

        # Build a lookup for container info (labels etc.)
        container_info = {str(c.get("name", "")): c for c in containers}

        # Clean up finished/cancelled tasks
        finished = [name for name, task in self._follow_tasks.items() if task.done()]
        for name in finished:
            del self._follow_tasks[name]

        # Cancel tasks for containers that no longer exist
        orphaned = set(self._follow_tasks.keys()) - current_names
        for name in orphaned:
            log.debug("log_forwarder.stopping_follow", name=name)
            self._follow_tasks[name].cancel()
            del self._follow_tasks[name]

        # Start follow tasks for new containers
        for name in current_names - set(self._follow_tasks.keys()):
            info = container_info.get(name, {})
            labels = info.get("labels", {}) or {}
            service = str(labels.get("io.silvasonic.service", "unknown"))
            instance_id = str(labels.get("io.silvasonic.device_id", name))

            log.debug(
                "log_forwarder.starting_follow",
                name=name,
                service=service,
            )
            task = asyncio.create_task(
                self._follow_container(
                    name=name,
                    service=service,
                    instance_id=instance_id,
                    redis=redis,
                ),
            )
            self._follow_tasks[name] = task

    async def _follow_container(
        self,
        *,
        name: str,
        service: str,
        instance_id: str,
        redis: Any,
    ) -> None:
        """Follow a single container's logs and publish to Redis.

        Runs in its own asyncio task.  Exits when the container stops
        or the task is cancelled.

        Args:
            name: Container name.
            service: Service type from container labels.
            instance_id: Instance ID from container labels.
            redis: Async Redis client for publishing.
        """
        try:
            container = await asyncio.to_thread(
                self._podman.containers.get,
                name,
            )

            # container.logs() is synchronous and blocking → run in thread
            # We use a generator wrapper to iterate in a thread-safe way
            def _iter_logs() -> list[str]:
                """Read a batch of log lines (blocking)."""
                lines: list[str] = []
                try:
                    for line in container.logs(
                        stream=True,
                        follow=True,
                        stdout=True,
                        stderr=True,
                        timestamps=False,
                    ):
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", errors="replace")
                        stripped = line.rstrip("\n\r")
                        if stripped:
                            lines.append(stripped)
                        # Yield control periodically to allow cancellation
                        if len(lines) >= 10:
                            return lines
                except StopIteration:
                    pass
                except Exception:
                    pass
                return lines

            while True:
                lines = await asyncio.to_thread(_iter_logs)
                if not lines:
                    # Container may have stopped — exit follow loop
                    log.debug("log_forwarder.container_stopped", name=name)
                    return

                for raw_line in lines:
                    payload = _parse_log_line(
                        raw_line,
                        service=service,
                        instance_id=instance_id,
                        container_name=name,
                    )
                    try:
                        await redis.publish(
                            LOGS_CHANNEL,
                            json.dumps(payload),
                        )
                    except Exception:
                        log.debug(
                            "log_forwarder.publish_failed",
                            name=name,
                        )

        except asyncio.CancelledError:
            log.debug("log_forwarder.follow_cancelled", name=name)
            raise
        except Exception:
            log.debug("log_forwarder.follow_error", name=name)

    async def _cancel_all_tasks(self) -> None:
        """Cancel all active follow tasks."""
        for _name, task in list(self._follow_tasks.items()):
            if not task.done():
                task.cancel()
        # Wait for all tasks to complete cancellation
        if self._follow_tasks:
            await asyncio.gather(
                *self._follow_tasks.values(),
                return_exceptions=True,
            )
        self._follow_tasks.clear()
        log.debug("log_forwarder.all_tasks_cancelled")
