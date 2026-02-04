import asyncio
import json
import socket
from collections.abc import Callable, Coroutine
from typing import Any, cast

import structlog
from silvasonic.core.redis.client import get_redis_client
from silvasonic.core.schemas.control import ControlMessage

logger = structlog.get_logger()


class RedisSubscriber:
    """Standardized Redis Subscriber for Silvasonic services."""

    def __init__(self, service_name: str, instance_id: str | None = None) -> None:
        """Initialize the subscriber with service identity."""
        self.service_name = service_name
        self.instance_id = instance_id or socket.gethostname()
        self.callbacks: dict[str, Callable[[ControlMessage], Coroutine[Any, Any, None]]] = {}
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._consecutive_errors = 0

    def register_handler(
        self, command: str, callback: Callable[[ControlMessage], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for a specific control command."""
        self.callbacks[command] = callback

    async def start(self) -> None:
        """Start listening for control messages via Redis Streams."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._stream_loop())
        logger.info(
            "stream_subscriber_started", service=self.service_name, instance=self.instance_id
        )

    async def stop(self) -> None:
        """Stop the subscriber loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("stream_subscriber_stopped")

    async def _ensure_group(self, stream: str, group: str) -> None:
        """Ensure consumer group exists."""
        try:
            async with get_redis_client() as redis:
                # MKSTREAM ensures stream is created if missing
                await redis.xgroup_create(stream, group, id="$", mkstream=True)
                logger.info("consumer_group_created", stream=stream, group=group)
        except Exception as e:
            if "BUSYGROUP" in str(e):
                pass
            else:
                logger.error("group_creation_failed", error=str(e))
                raise

    async def _stream_loop(self) -> None:
        """Internal loop to consume from Redis Stream."""
        stream_name = "stream:control"
        # CRITICAL FIX: Group must be unique PER INSTANCE to ensure every instance
        # receives a copy of the message (Broadcast-like).
        # If we shared group "recorder", only ONE recorder would get the message.
        # This acts as "Persistent Pub/Sub".
        group_name = f"{self.service_name}:{self.instance_id}"
        consumer_name = self.instance_id

        backoff_delay = 1.0

        # 1. Ensure Group Exists
        try:
            await self._ensure_group(stream_name, group_name)
        except Exception:
            # Retry a few times or exit?
            # If redis is down at start, we might fail here.
            # We should probably do this inside the loop or retry.
            pass

        while self._running:
            try:
                async with get_redis_client() as redis:
                    backoff_delay = 1.0

                    while self._running:
                        try:
                            # XREADGROUP
                            # > means "new messages never delivered to other consumers"
                            streams = {stream_name: ">"}
                            # Cast to Any to satisfy mypy strict variance
                            response = await redis.xreadgroup(
                                group_name,
                                consumer_name,
                                cast(Any, streams),
                                count=1,
                                block=2000,
                            )

                            # SUCCESS - Reset Error State
                            if self._consecutive_errors > 0:
                                logger.info(
                                    "redis_connection_restored",
                                    service=self.service_name,
                                )
                                self._consecutive_errors = 0

                            if not response:
                                continue

                            for _, messages in response:
                                for msg_id, fields in messages:
                                    # Fields is a dict, e.g. {b'json': b'{...}'}
                                    # We need to decode keys/values usually, but decode_responses=True in client might handle it
                                    # Assuming standard client from client.py handles decoding if configured,
                                    # otherwise we handle bytes.
                                    await self._process_stream_message(
                                        redis, stream_name, group_name, msg_id, fields
                                    )

                        except Exception as e:
                            self._consecutive_errors += 1
                            if self._consecutive_errors == 1:
                                logger.error("stream_read_error", error=str(e))
                            else:
                                logger.warning(
                                    "stream_read_error_retrying",
                                    error=str(e),
                                    attempt=self._consecutive_errors,
                                )

                            await asyncio.sleep(1.0)
                            # Break to outer loop to refresh client
                            break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._consecutive_errors += 1
                if self._consecutive_errors == 1:
                    logger.error("redis_connection_error", error=str(e), retry_in=backoff_delay)
                else:
                    logger.warning(
                        "redis_connection_error_retrying",
                        error=str(e),
                        retry_in=backoff_delay,
                        attempt=self._consecutive_errors,
                    )

                await asyncio.sleep(backoff_delay)
                backoff_delay = min(60.0, backoff_delay * 2)

    async def _process_stream_message(
        self, redis: Any, stream: str, group: str, msg_id: str, fields: dict[str, Any]
    ) -> None:
        """Process a single stream message and ACK."""
        try:
            # Extract JSON
            # We used 'json' key in publisher
            # decode_responses=True means we get strings
            raw_data = fields.get("json")
            if not raw_data:
                logger.warning("malformed_stream_message", msg_id=msg_id, fields=fields)
                # ACK anyway to skip bad message? Yes.
                await redis.xack(stream, group, msg_id)
                return

            if isinstance(raw_data, bytes):  # Helper just in case
                raw_data = raw_data.decode("utf-8")

            # Reuse existing logic
            await self._process_message_logic(raw_data)

            # ACK on success
            await redis.xack(stream, group, msg_id)

        except Exception as e:
            logger.error("message_processing_failed", msg_id=msg_id, error=str(e))
            # Decision: Do we ACK?
            # If we don't ACK, it will be redelivered.
            # If it's a bug in code, infinite loop.
            # For now, let's NOT ACK so we can retry (or use manual DLQ logic later).
            # But to avoid immediate spin loop, maybe we ack if it matches "invalid_message"?
            pass

    async def _process_message_logic(self, raw_data: str) -> None:
        """Process an incoming message (moved from old _process_message)."""
        data = json.loads(raw_data)
        msg = ControlMessage(**data)

        # 1. Filter by Target Service
        if msg.target_service != "*" and msg.target_service != self.service_name:
            return

        # 2. Filter by Target Instance
        if msg.target_instance != "*" and msg.target_instance != self.instance_id:
            return

        # 3. Dispatch
        if msg.command in self.callbacks:
            logger.info("executing_control_command", command=msg.command, initiator=msg.initiator)
            try:
                await self.callbacks[msg.command](msg)
            except Exception as e:
                logger.error("command_execution_failed", command=msg.command, error=str(e))
                raise e  # Propagate to prevent ACK if critical?
                # Actually _process_stream_message catches this, logs, and does NOT ack.
        else:
            logger.debug("unknown_command_ignored", command=msg.command)
