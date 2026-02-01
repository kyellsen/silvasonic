import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis
from silvasonic.core.redis.client import settings

logger = logging.getLogger(__name__)


class MessageSubscriber:
    """Subscriber service for the Status Board."""

    def __init__(self) -> None:
        """Initialize the MessageSubscriber."""
        self.redis: redis.Redis | None = None
        self.pubsub: Any = None
        self.cache: dict[str, Any] = {}
        self._listeners: list[asyncio.Queue[str]] = []
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the Redis subscriber background task."""
        self.redis = redis.Redis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe("silvasonic.status", "silvasonic.lifecycle")
        self._task = asyncio.create_task(self._run_listener())
        logger.info("MessageSubscriber started.")

    async def stop(self) -> None:
        """Stop the subscriber and close connections."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.pubsub:
            await self.pubsub.unsubscribe()
        if self.redis:
            await self.redis.close()
        logger.info("MessageSubscriber stopped.")

    async def _run_listener(self) -> None:
        """Listen for Redis messages and broadcast them."""
        if not self.pubsub:
            return

        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    await self._process_message(message["channel"], message["data"])
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in Redis listener: {e}")

    async def _process_message(self, channel: str, data: str) -> None:
        """Process a single message: update cache and broadcast."""
        try:
            payload = json.loads(data)

            # Update Cache
            # We want to key by "service:instance"
            service = payload.get("service")
            instance = payload.get("instance_id")

            if service and instance:
                key = f"{service}:{instance}"
                self.cache[key] = payload
            elif service:
                self.cache[service] = payload

            # Broadcast to SSE clients
            # SSE event format: data: <json_string>\n\n
            # We broadcast the RAW data to avoid re-serialization overhead
            sse_message = f"data: {data}\n\n"

            # Fan-out to all connected listeners
            # We use a copy of the list to handle disconnection mid-loop safely-ish
            for queue in self._listeners:
                await queue.put(sse_message)

        except Exception as e:
            logger.error(f"Failed to process message: {e}")

    async def stream_events(self) -> AsyncGenerator[str, None]:
        """Yield events for a single SSE connection."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._listeners.append(queue)

        # 1. Send initial state (dump cache)
        # This ensures the UI is populated immediately upon connection
        for state in self.cache.values():
            yield f"data: {json.dumps(state)}\n\n"

        # 2. Yield new events as they come
        try:
            while True:
                msg = await queue.get()
                yield msg
        finally:
            if queue in self._listeners:
                self._listeners.remove(queue)
