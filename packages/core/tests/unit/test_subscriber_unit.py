import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.redis.subscriber import RedisSubscriber
from silvasonic.core.schemas.control import ControlMessage, ControlPayloadContent


@pytest.mark.asyncio
async def test_subscriber_filtering() -> None:
    """Test that subscriber filters messages correctly."""
    # Mock Redis client
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    # redis.pubsub() is synchronous, so we mock it as a MagicMock, not AsyncMock
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    # Message 1: Target different service (Should overwrite?)
    msg1 = ControlMessage(
        command="cmd1",
        initiator="test",
        target_service="other_service",
        payload=ControlPayloadContent(params={}),
    )

    # Message 2: Target this service
    msg2 = ControlMessage(
        command="cmd2",
        initiator="test",
        target_service="my_service",
        payload=ControlPayloadContent(params={}),
    )

    # Message 3: Target all
    msg3 = ControlMessage(
        command="cmd3",
        initiator="test",
        target_service="*",
        payload=ControlPayloadContent(params={}),
    )

    # Setup PubSub yield
    # We simulate a stream of messages
    async def msg_generator() -> AsyncGenerator[dict[str, Any], None]:
        yield {"type": "message", "data": msg1.model_dump_json()}
        yield {"type": "message", "data": msg2.model_dump_json()}
        yield {"type": "message", "data": msg3.model_dump_json()}
        # Then we make it wait so we can cancel
        while True:
            await asyncio.sleep(0.1)

    messages = [
        {"type": "message", "data": msg1.model_dump_json()},
        {"type": "message", "data": msg2.model_dump_json()},
        {"type": "message", "data": msg3.model_dump_json()},
    ]

    async def mock_get_message(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        if messages:
            return messages.pop(0)
        await asyncio.sleep(10)  # Simulate waiting for next message
        return None

    mock_pubsub.get_message.side_effect = mock_get_message

    # Patch get_redis_client to return our mock
    # Since get_redis_client is a context manager, we need to mock __aenter__
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_redis

    with patch("silvasonic.core.redis.subscriber.get_redis_client", return_value=mock_ctx):
        subscriber = RedisSubscriber("my_service", "inst1")

        # Register Handlers
        handler2 = AsyncMock()
        handler3 = AsyncMock()
        subscriber.register_handler("cmd2", handler2)
        subscriber.register_handler("cmd3", handler3)

        # Start Subscriber
        # We need to run it for a bit then stop
        await subscriber.start()

        # Give it time to process
        await asyncio.sleep(0.2)

        # Since we mocked get_message to return values then None, the loop will spin on None (TimeoutError in real code, but here?)
        # Logic in code: await pubsub.get_message(..., timeout=1.0)
        # If we mock it to return None, code continues?
        # Code: if message and type=message: process.
        # It handles None implicitly by doing nothing.

        await subscriber.stop()

        # Verification
        # Handler 2 should be called (Target: my_service)
        assert handler2.called
        assert handler2.call_count == 1

        # Handler 3 should be called (Target: *)
        assert handler3.called
        assert handler3.call_count == 1

        # Msg 1 was for other_service, should NOT call any handler (we didn't register cmd1 anyway, but logic filters first)


if __name__ == "__main__":
    pass
