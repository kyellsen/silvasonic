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
        # 1. PubSub (Status)
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe("silvasonic.status")
        self._task = asyncio.create_task(self._run_pubsub_listener())

        # 2. Streams (Lifecycle, Audit)
        self._stream_task = asyncio.create_task(self._run_stream_listener())

        logger.info("MessageSubscriber started (PubSub + Streams).")

    async def stop(self) -> None:
        """Stop the subscriber and close connections."""
        for t in [self._task, getattr(self, "_stream_task", None)]:
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        if self.pubsub:
            await self.pubsub.unsubscribe()
        if self.redis:
            await self.redis.close()
        logger.info("MessageSubscriber stopped.")

    async def _run_pubsub_listener(self) -> None:
        """Listen for Redis PubSub messages (Status)."""
        if not self.pubsub:
            return

        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    await self._process_message(message["channel"], message["data"])
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in Redis PubSub listener: {e}")

    async def _run_stream_listener(self) -> None:
        """Listen for Redis Stream messages (Lifecycle, Audit)."""
        streams = ["stream:lifecycle", "stream:audit"]
        last_ids: dict[Any, Any] = {s: "$" for s in streams}  # Start with new messages

        # 1. Load History (Last 50 items)
        if self.redis:
            for s in streams:
                try:
                    # xrevrange returns list of (id, fields)
                    history = await self.redis.xrevrange(s, count=20)
                    # We want chronological order (oldest first)
                    for _, fields in reversed(history):
                        await self._process_stream_msg(s, fields)
                except Exception as e:
                    logger.warning(f"Failed to load history for {s}: {e}")

        # 2. Listen Loop
        while True:
            try:
                if not self.redis:
                    await asyncio.sleep(1)
                    continue

                # XREAD
                response = await self.redis.xread(last_ids, count=1, block=2000)  # type: ignore[arg-type]
                if not response:
                    continue

                for stream_name, messages in response:
                    for msg_id, fields in messages:
                        await self._process_stream_msg(stream_name, fields)
                        last_ids[stream_name] = msg_id

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis Stream listener: {e}")
                await asyncio.sleep(1)

    async def _process_stream_msg(self, stream: str, fields: dict[str, Any]) -> None:
        """Process a stream message."""
        raw_data = fields.get("json")
        if raw_data:
            # Map stream name to "logical channel" for existing processor
            channel_map = {
                "stream:lifecycle": "silvasonic.lifecycle",
                "stream:audit": "silvasonic.audit",
            }
            channel = channel_map.get(stream, stream)
            await self._process_message(channel, raw_data)

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
