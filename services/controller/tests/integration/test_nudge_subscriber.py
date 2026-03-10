"""Integration tests: NudgeSubscriber ↔ real Redis.

Verifies that the NudgeSubscriber correctly receives Pub/Sub messages
from a real Redis instance and triggers the reconciliation loop.

Uses the shared ``redis_container`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from redis.asyncio import Redis
from silvasonic.controller.nudge_subscriber import NUDGE_CHANNEL, NudgeSubscriber
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer


@pytest.mark.integration
class TestNudgeSubscriberRedis:
    """Verify NudgeSubscriber with a real Redis Pub/Sub channel."""

    async def test_receives_reconcile_message(self, redis_container: RedisContainer) -> None:
        """NudgeSubscriber triggers reconciliation when 'reconcile' is published."""
        url = build_redis_url(redis_container)

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url=url)

        # Start the subscriber in a background task
        task = asyncio.create_task(sub.run())

        # Allow time for the subscriber to connect and subscribe
        await asyncio.sleep(0.5)

        # Publish a reconcile message from a separate client
        publisher = Redis.from_url(url, decode_responses=True)
        await publisher.publish(NUDGE_CHANNEL, "reconcile")

        # Allow time for the message to be received and processed
        await asyncio.sleep(0.5)

        # Stop the subscriber
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await cast(Any, publisher).aclose()

        reconciler.trigger.assert_called_once()

    async def test_ignores_non_reconcile_message(self, redis_container: RedisContainer) -> None:
        """NudgeSubscriber ignores messages that are not 'reconcile'."""
        url = build_redis_url(redis_container)

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url=url)

        task = asyncio.create_task(sub.run())
        await asyncio.sleep(0.5)

        publisher = Redis.from_url(url, decode_responses=True)
        await publisher.publish(NUDGE_CHANNEL, "restart")
        await asyncio.sleep(0.5)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await cast(Any, publisher).aclose()

        reconciler.trigger.assert_not_called()

    async def test_reconnects_after_disconnect(self, redis_container: RedisContainer) -> None:
        """NudgeSubscriber reconnects after a brief interruption.

        This test verifies the subscriber continues to work after an initial
        successful connection, by checking it receives a second message.
        """
        url = build_redis_url(redis_container)

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url=url)

        task = asyncio.create_task(sub.run())
        await asyncio.sleep(0.5)

        publisher = Redis.from_url(url, decode_responses=True)

        # First message
        await publisher.publish(NUDGE_CHANNEL, "reconcile")
        await asyncio.sleep(0.3)

        # Second message
        await publisher.publish(NUDGE_CHANNEL, "reconcile")
        await asyncio.sleep(0.3)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await cast(Any, publisher).aclose()

        assert reconciler.trigger.call_count == 2
