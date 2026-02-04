import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.status_board.subscriber import MessageSubscriber


@pytest.mark.asyncio
async def test_subscriber_flow() -> None:
    """Test the subscriber flow including cache and broadcasting."""
    from collections.abc import AsyncGenerator
    from typing import Any
    from unittest.mock import MagicMock

    # Mock Redis
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    # Prevent busy loop in _run_stream_listener
    async def mock_xread(*args: Any, **kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.1)
        return []

    mock_redis.xread.side_effect = mock_xread

    # Mock pubsub listen
    msg_data = {
        "service": "test-service",
        "instance_id": "test-1",
        "health": "healthy",
        "activity": "testing",
    }

    # We need an async iterator that yields one message then waits
    async def mock_listen() -> AsyncGenerator[dict[str, Any], None]:
        yield {
            "type": "message",
            "channel": b"silvasonic.status",
            "data": json.dumps(msg_data).encode(),
        }
        # Sleep forever to keep the listener task running until we cancel it
        while True:
            await asyncio.sleep(0.1)

    # IMPORTANT: listen() must be a sync method (MagicMock) that returns the async generator (coroutine-like iterator)
    # AsyncMock would wrap the return value in a coroutine, which 'async for' doesn't like directly if it expects an iterator.
    # Actually, if side_effect is set to an async gen function, calling the mock returns the gen object.
    # But if the mock itself is AsyncMock, it awaits the result? No.
    # The issue is likely that mock_pubsub.listen was auto-created as AsyncMock.
    mock_pubsub.listen = MagicMock(side_effect=mock_listen)

    with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
        subscriber = MessageSubscriber()
        await subscriber.start()

        # Verify subscription
        mock_pubsub.subscribe.assert_called_with("silvasonic.status")

        # Wait a bit for processing
        await asyncio.sleep(0.1)

        # Check cache
        assert "test-service:test-1" in subscriber.cache
        assert subscriber.cache["test-service:test-1"]["health"] == "healthy"

        # Verify streaming (broadcasting)
        queue: asyncio.Queue[str] = asyncio.Queue()
        subscriber._listeners.append(queue)

        # Inject another message bypassing the loop for deterministic testing
        new_msg_data = {"service": "test-service", "instance_id": "test-1", "health": "degraded"}
        await subscriber._process_message("silvasonic.status", json.dumps(new_msg_data))

        # Read from queue
        sse_msg = await queue.get()
        assert "data: " in sse_msg
        assert "test-service" in sse_msg
        assert "degraded" in sse_msg

        await subscriber.stop()
        mock_pubsub.unsubscribe.assert_called()
        mock_redis.close.assert_called()
