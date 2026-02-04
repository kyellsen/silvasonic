import asyncio
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

    # Mock Redis XREADGROUP response
    # Format: [[stream_name, [[msg_id, fields]]]]

    # helper to format message for stream
    def format_stream_msg(msg_id: str, data: ControlMessage) -> list[Any]:
        return ["stream:control", [(msg_id, {"json": data.model_dump_json()})]]

    # We use a mutable list to pop messages
    stream_responses = [
        format_stream_msg("1-0", msg1),
        format_stream_msg("2-0", msg2),
        format_stream_msg("3-0", msg3),
    ]

    async def mock_xreadgroup(*args: Any, **kwargs: Any) -> list[Any]:
        if stream_responses:
            return [stream_responses.pop(0)]
        await asyncio.sleep(0.1)  # Simulate wait
        return []

    mock_redis.xreadgroup.side_effect = mock_xreadgroup
    mock_redis.xgroup_create = AsyncMock()

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
        await subscriber.start()

        # Give it time to process (3 messages)
        await asyncio.sleep(0.2)

        await subscriber.stop()

        # Verification
        # Handler 2 should be called (Target: my_service)
        assert handler2.called
        assert handler2.call_count == 1

        # Handler 3 should be called (Target: *)
        assert handler3.called
        assert handler3.call_count == 1


if __name__ == "__main__":
    pass
