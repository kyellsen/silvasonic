import asyncio
import json
import os
import sys
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Add paths for imports
sys.path.append(os.path.abspath("services/status-board/src"))
sys.path.append(os.path.abspath("packages/core/src"))

from silvasonic.status_board.subscriber import MessageSubscriber


async def run_test() -> None:
    """Run the standalone subscriber verification test."""
    print("Starting standalone test...")

    # Mock Redis
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    # redis.pubsub() is synchronous, so we use MagicMock for the method
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    # Mock listen
    async def mock_listen() -> AsyncGenerator[dict[str, Any], None]:
        print("Mock: yielding message")
        msg = {
            "type": "message",
            "channel": b"silvasonic.status",
            "data": json.dumps(
                {"service": "test-service", "instance_id": "test-1", "health": "healthy"}
            ).encode(),
        }
        yield msg
        # yield forever
        while True:
            await asyncio.sleep(0.1)

    mock_pubsub.listen = MagicMock(return_value=mock_listen())

    with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
        sub = MessageSubscriber()
        await sub.start()
        print("Subscriber started.")

        # Verify subscription was called
        mock_pubsub.subscribe.assert_called()
        print("Redis subscribed.")

        await asyncio.sleep(0.5)

        # Check cache
        print(f"Cache state: {sub.cache}")
        if "test-service:test-1" in sub.cache:
            if sub.cache["test-service:test-1"]["health"] == "healthy":
                print("SUCCESS: Cache updated correctly.")
            else:
                print("FAILURE: Cache content incorrect.")
        else:
            print("FAILURE: Cache not updated.")

        # Test streaming
        print("Testing streaming fan-out...")
        queue: asyncio.Queue[str] = asyncio.Queue()
        sub._listeners.append(queue)

        # Inject another message
        new_msg = json.dumps(
            {"service": "test-service", "instance_id": "test-1", "health": "degraded"}
        )
        await sub._process_message("silvasonic.status", new_msg)

        try:
            sse_msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            print(f"Received SSE message: {sse_msg.strip()}")
            if "degraded" in sse_msg:
                print("SUCCESS: SSE broadcast received.")
            else:
                print("FAILURE: SSE content incorrect.")
        except TimeoutError:
            print("FAILURE: SSE broadcast timed out.")

        await sub.stop()
        print("Test finished.")


if __name__ == "__main__":
    asyncio.run(run_test())
