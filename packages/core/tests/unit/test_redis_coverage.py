import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.core.redis.subscriber import RedisSubscriber
from silvasonic.core.schemas.control import ControlMessage, ControlPayloadContent

# --- Publisher Tests ---


@pytest.mark.asyncio
async def test_publish_lifecycle_invalid_event() -> None:
    """Test publishing an invalid lifecycle event falls back to 'crashed'."""
    mock_redis = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_redis

    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_ctx):
        publisher = RedisPublisher("test-service")

        # Pass invalid event "exploded"
        await publisher.publish_lifecycle(event="exploded", reason="Boom")

        # Verify it published "crashed" instead using XADD
        mock_redis.xadd.assert_called_once()
        args = mock_redis.xadd.call_args[0]
        stream_name = args[0]
        payload = args[1]

        assert stream_name == "stream:lifecycle"
        actual_msg = json.loads(payload["json"])
        assert actual_msg["event"] == "crashed"
        assert actual_msg["payload"]["reason"] == "Boom"


@pytest.mark.asyncio
async def test_publish_redis_exception() -> None:
    """Test that Redis exceptions during publish are caught and logged."""
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.side_effect = Exception("Redis Connection Failed")

    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_ctx):
        publisher = RedisPublisher("test-service")

        # This will use _publish -> logger
        await publisher.publish_status("online", "idle", "Ready")


@pytest.mark.asyncio
async def test_set_with_ttl_check() -> None:
    """Test that set_with_ttl is called during status publish."""
    mock_redis = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_redis

    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_ctx):
        publisher = RedisPublisher("test-service", "inst1")
        await publisher.publish_status("online", "idle", "Ready")

        # Verify SET command
        mock_redis.set.assert_called_once()
        args = mock_redis.set.call_args
        assert args[0][0] == "status:test-service:inst1"
        assert args[1]["ex"] == 10


@pytest.mark.asyncio
async def test_set_with_ttl_exception() -> None:
    """Test that Redis exceptions during SET are caught."""
    mock_redis = AsyncMock()
    # Mock set to raise exception
    mock_redis.set.side_effect = Exception("Set Failed")

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_redis

    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_ctx):
        publisher = RedisPublisher("test-service")
        # Should not raise
        await publisher._set_with_ttl("key", "val", 10)


# --- Subscriber Tests ---


@pytest.mark.asyncio
async def test_subscriber_start_idempotent() -> None:
    """Test that calling start twice does not create two tasks."""
    subscriber = RedisSubscriber("test")
    subscriber._running = True

    with patch("asyncio.create_task") as mock_create_task:
        await subscriber.start()
        mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_subscriber_target_instance_mismatch() -> None:
    """Test that messages for other instances are ignored."""
    subscriber = RedisSubscriber("service", "my-instance")

    # Message for "other-instance"
    msg = ControlMessage(
        command="cmd",
        initiator="test",
        target_service="service",
        target_instance="other-instance",
        payload=ControlPayloadContent(params={}),
    )

    # Mock callback
    callback = AsyncMock()
    subscriber.register_handler("cmd", callback)

    # Directly process logic
    await subscriber._process_message_logic(msg.model_dump_json())

    callback.assert_not_called()


@pytest.mark.asyncio
async def test_subscriber_callback_exception() -> None:
    """Test that exceptions in callbacks are caught."""
    subscriber = RedisSubscriber("service", "inst")

    # Handler raises exception
    async def bad_handler(msg: Any) -> None:
        raise ValueError("Oops")

    subscriber.register_handler("cmd", bad_handler)

    msg = ControlMessage(
        command="cmd",
        initiator="test",
        target_service="service",
        target_instance="inst",
        payload=ControlPayloadContent(params={}),
    )

    # Should raise because _process_message_logic re-raises
    with pytest.raises(ValueError):
        await subscriber._process_message_logic(msg.model_dump_json())


@pytest.mark.asyncio
async def test_subscriber_invalid_json() -> None:
    """Test handling of invalid JSON in _process_message_logic."""
    subscriber = RedisSubscriber("service")
    # This will raise JSONDecodeError if passed directly to json.loads,
    # but _process_stream_message handles the try/except block usually.
    # _process_message_logic expects valid json string usually, or raises.
    # The subscriber loop calls _process_stream_message which calls _process_message_logic

    # Let's test _process_stream_message to cover the JSON parsing error handling
    mock_redis = AsyncMock()
    fields = {"json": "{invalid"}

    # Should not raise
    await subscriber._process_stream_message(mock_redis, "stream", "group", "msgid", fields)

    # Should NOT ACK on exception (current behavior)
    mock_redis.xack.assert_not_called()


@pytest.mark.asyncio
async def test_subscriber_unknown_command() -> None:
    """Test handling of unknown commands."""
    subscriber = RedisSubscriber("service", "inst")

    msg = ControlMessage(
        command="unknown_cmd",
        initiator="test",
        target_service="service",
        target_instance="inst",
        payload=ControlPayloadContent(params={}),
    )

    # Verify it logs debug but doesn't crash
    await subscriber._process_message_logic(msg.model_dump_json())


@pytest.mark.asyncio
async def test_subscriber_loop_flow() -> None:
    """Test complete subscriber loop flow with xreadgroup."""
    subscriber = RedisSubscriber("test", "inst")

    mock_redis = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_redis

    # Setup XREADGROUP response
    # format: [[stream_name, [[msg_id, fields]]]]
    msg_fields = {
        "json": json.dumps(
            {
                "command": "test_cmd",
                "initiator": "test",
                "target_service": "test",
                "target_instance": "inst",
                "payload": {},
            }
        )
    }

    valid_resp = [[b"stream:control", [[b"1-0", msg_fields]]]]

    # We want the loop to run once with data, then stop
    # mocking xreadgroup
    async def xread_side_effect(*args: Any, **kwargs: Any) -> Any:
        subscriber._running = False  # Stop after first call
        return valid_resp

    mock_redis.xreadgroup.side_effect = xread_side_effect

    mock_handler = AsyncMock()
    subscriber.register_handler("test_cmd", mock_handler)

    with patch("silvasonic.core.redis.subscriber.get_redis_client", return_value=mock_ctx):
        subscriber._running = True
        await subscriber._stream_loop()

    # Verify processing
    mock_handler.assert_called_once()
    mock_redis.xack.assert_called_once()
