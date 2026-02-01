import asyncio
import json
import socket
from collections.abc import Callable, Coroutine
from typing import Any

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

    def register_handler(
        self, command: str, callback: Callable[[ControlMessage], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for a specific control command."""
        self.callbacks[command] = callback

    async def start(self) -> None:
        """Start listening for control messages in the background."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._subscribe_loop())
        logger.info("subscriber_started", service=self.service_name)

    async def stop(self) -> None:
        """Stop the subscriber loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("subscriber_stopped")

    async def _subscribe_loop(self) -> None:
        """Internal loop to listen to Redis channels."""
        channel_name = "silvasonic.control"

        while self._running:
            try:
                async with get_redis_client() as redis:
                    pubsub = redis.pubsub()
                    await pubsub.subscribe(channel_name)
                    logger.debug("subscribed_to_channel", channel=channel_name)

                    while self._running:
                        try:
                            # Get message with timeout to allow checking self._running
                            message = await pubsub.get_message(
                                ignore_subscribe_messages=True, timeout=1.0
                            )

                            if message and message["type"] == "message":
                                await self._process_message(message["data"])

                        except TimeoutError:
                            continue
                        except Exception as e:
                            logger.error("subscriber_loop_error", error=str(e))
                            # Break inner loop to reconnect
                            break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("redis_connection_error", error=str(e))
                await asyncio.sleep(5)  # Wait before reconnecting

    async def _process_message(self, raw_data: str) -> None:
        """Process an incoming message."""
        try:
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
                logger.info(
                    "executing_control_command", command=msg.command, initiator=msg.initiator
                )
                try:
                    await self.callbacks[msg.command](msg)
                except Exception as e:
                    logger.error("command_execution_failed", command=msg.command, error=str(e))
            else:
                logger.debug("unknown_command_ignored", command=msg.command)

        except Exception as e:
            logger.warning("invalid_message_received", error=str(e))
