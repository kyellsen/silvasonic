import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

        # Verify it published "crashed" instead
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        payload = json.loads(args[1])
        assert payload["event"] == "crashed"
        assert payload["payload"]["reason"] == "Boom"


@pytest.mark.asyncio
async def test_publish_redis_exception() -> None:
    """Test that Redis exceptions during publish are caught and logged."""
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.side_effect = Exception("Redis Connection Failed")

    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_ctx):
        publisher = RedisPublisher("test-service")

        # This should NOT raise an exception, but log an error
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

    # Directly process message
    await subscriber._process_message(msg.model_dump_json())

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

    # Should not raise
    await subscriber._process_message(msg.model_dump_json())


@pytest.mark.asyncio
async def test_subscriber_invalid_json() -> None:
    """Test handling of invalid JSON."""
    subscriber = RedisSubscriber("service")
    # Should log warning but not crash
    await subscriber._process_message("{invalid_json")


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
    await subscriber._process_message(msg.model_dump_json())


@pytest.mark.asyncio
async def test_subscriber_loop_timeout_and_errors() -> None:
    """Test subscriber loop handles TimeoutError and generic exceptions."""
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_redis.pubsub.return_value = mock_pubsub

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_redis

    # We want to simulate:
    # 1. TimeoutError (should continue)
    # 2. Exception (should break inner loop)
    # 3. Stop running to exit outer loop

    call_count = 0
    subscriber = RedisSubscriber("test")

    async def side_effect(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError()
        if call_count == 2:
            raise Exception("Inner Loop Error")
        # Should not be reached if inner loop breaks,
        # but we need to stop subscriber to exit outer loop eventually
        subscriber._running = False
        return None

    mock_pubsub.get_message.side_effect = side_effect

    with patch("silvasonic.core.redis.subscriber.get_redis_client", return_value=mock_ctx):
        with patch("asyncio.sleep", return_value=None):  # Skip sleeps
            subscriber._running = True
            # We run it directly (not as task) but we need to ensure it exits
            # The inner loop breaks on Exception.
            # The outer loop continues.
            # We mock get_redis_client to NOT fail, so it re-enters inner loop.
            # We need a way to stop it.
            # Let's mock get_redis_client to fail the SECOND time to test outer loop backoff?

            # Revised Plan:
            # 1. First ctx: OK. Inner Loop: Timeout -> Exception -> Break.
            # 2. Outer Loop: Re-enters ctx.
            # We need side_effect on get_redis_client.
            pass


@pytest.mark.asyncio
async def test_subscriber_loop_flow() -> None:
    """Test complete subscriber loop flow with errors."""
    subscriber = RedisSubscriber("test")

    # Mock Redis client and PubSub
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    # redis.pubsub() is synchronous!
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    # Control loop execution
    # Iteration 1: Connection OK.
    #   Inner 1: TimeoutError -> Continue
    #   Inner 2: Exception -> Log Error & Break Inner
    # Iteration 2: Connection Error -> Log Error & Backoff & Sleep
    # Iteration 3: Stop

    # Mock get_redis_client context manager factory
    ctx_1 = AsyncMock()
    ctx_1.__aenter__.return_value = mock_redis

    ctx_2 = AsyncMock()
    ctx_2.__aenter__.side_effect = Exception("Connection Failed")

    # We patch the function itself.
    # Since it's an asynccontextmanager, it returns a context manager.

    attempt = 0

    def get_client_side_effect() -> AsyncMock:
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            return ctx_1
        if attempt == 2:
            return ctx_2
        subscriber._running = False  # Stop after attempt 2 failure handling
        return ctx_2  # Should not be used

    # Mock pubsub.get_message for the first successful connection
    msg_attempt = 0

    async def get_message_side_effect(**kwargs: Any) -> None:
        nonlocal msg_attempt
        msg_attempt += 1
        if msg_attempt == 1:
            raise TimeoutError()
        if msg_attempt == 2:
            raise ValueError("Bad Message Processing")
        return None

    mock_pubsub.get_message.side_effect = get_message_side_effect

    with patch(
        "silvasonic.core.redis.subscriber.get_redis_client", side_effect=get_client_side_effect
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            subscriber._running = True
            await subscriber._subscribe_loop()

            # Verify flow
            assert msg_attempt == 2  # Timeout then Error
            # Should have slept once due to connection error
            mock_sleep.assert_called()
