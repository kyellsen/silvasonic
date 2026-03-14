"""Integration tests: LogForwarder ↔ real Redis.

Verifies that the LogForwarder correctly publishes container log lines
to a real Redis Pub/Sub channel, matching the ADR-0022 payload schema.

Uses the shared ``redis_container`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``).  Podman is mocked — the integration
boundary under test is LogForwarder → Redis Pub/Sub.

Pattern follows ``test_nudge_subscriber.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from redis.asyncio import Redis
from silvasonic.controller.log_forwarder import LOGS_CHANNEL, LogForwarder
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer


def _make_mock_podman(
    containers: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Create a mock Podman client with optional managed containers."""
    mock = MagicMock()
    mock.is_connected = True
    mock.list_managed_containers.return_value = containers or []
    return mock


@pytest.mark.integration
class TestLogForwarderRedis:
    """Verify LogForwarder publishes logs via real Redis Pub/Sub."""

    async def test_publishes_log_to_real_redis(self, redis_container: RedisContainer) -> None:
        """JSON log line from container stdout → received by Redis subscriber."""
        url = build_redis_url(redis_container)

        # Mock Podman: one container producing one JSON log line
        containers = [
            {
                "name": "silvasonic-recorder-test-001",
                "status": "running",
                "labels": {
                    "io.silvasonic.service": "recorder",
                    "io.silvasonic.device_id": "test-device-001",
                },
            },
        ]
        mock_podman = _make_mock_podman(containers)

        mock_container = MagicMock()
        mock_container.logs.return_value = iter(
            [
                b'{"event": "Recording started", "level": "info"}\n',
            ]
        )
        mock_podman.containers.get.return_value = mock_container

        forwarder = LogForwarder(mock_podman, redis_url=url, poll_interval=0.2)

        # Subscribe to the logs channel from a separate client
        subscriber = Redis.from_url(url, decode_responses=True)
        pubsub = subscriber.pubsub()
        await pubsub.subscribe(LOGS_CHANNEL)
        # Consume the subscription confirmation message
        await pubsub.get_message(timeout=1.0)

        # Start forwarder in background
        task = asyncio.create_task(forwarder.run())
        try:
            # Wait for the forwarder to poll and publish
            received = None
            for _ in range(20):  # up to 2s
                msg = await pubsub.get_message(timeout=0.1)
                if msg and msg["type"] == "message":
                    received = json.loads(msg["data"])
                    break
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await pubsub.unsubscribe(LOGS_CHANNEL)
            await cast(Any, pubsub).aclose()
            await cast(Any, subscriber).aclose()

        assert received is not None, "No log message received on Redis channel"
        assert received["service"] == "recorder"
        assert received["instance_id"] == "test-device-001"
        assert received["container_name"] == "silvasonic-recorder-test-001"
        assert received["message"] == "Recording started"
        assert received["level"] == "info"

    async def test_non_json_wrapped_over_redis(self, redis_container: RedisContainer) -> None:
        """Non-JSON stdout is wrapped as level='raw' and received via Redis."""
        url = build_redis_url(redis_container)

        containers = [
            {
                "name": "silvasonic-recorder-raw-001",
                "status": "running",
                "labels": {
                    "io.silvasonic.service": "recorder",
                    "io.silvasonic.device_id": "raw-device",
                },
            },
        ]
        mock_podman = _make_mock_podman(containers)

        mock_container = MagicMock()
        mock_container.logs.return_value = iter(
            [
                b"Traceback (most recent call last):\n",
            ]
        )
        mock_podman.containers.get.return_value = mock_container

        forwarder = LogForwarder(mock_podman, redis_url=url, poll_interval=0.2)

        subscriber = Redis.from_url(url, decode_responses=True)
        pubsub = subscriber.pubsub()
        await pubsub.subscribe(LOGS_CHANNEL)
        await pubsub.get_message(timeout=1.0)

        task = asyncio.create_task(forwarder.run())
        try:
            received = None
            for _ in range(20):
                msg = await pubsub.get_message(timeout=0.1)
                if msg and msg["type"] == "message":
                    received = json.loads(msg["data"])
                    break
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await pubsub.unsubscribe(LOGS_CHANNEL)
            await cast(Any, pubsub).aclose()
            await cast(Any, subscriber).aclose()

        assert received is not None, "No log message received on Redis channel"
        assert received["level"] == "raw"
        assert received["message"] == "Traceback (most recent call last):"

    async def test_container_removal_stops_publishing(
        self, redis_container: RedisContainer
    ) -> None:
        """When a container disappears, no more log messages are published."""
        url = build_redis_url(redis_container)

        containers: list[dict[str, Any]] = [
            {
                "name": "silvasonic-recorder-vanish-001",
                "status": "running",
                "labels": {
                    "io.silvasonic.service": "recorder",
                    "io.silvasonic.device_id": "vanish-device",
                },
            },
        ]
        mock_podman = _make_mock_podman(containers)

        mock_container = MagicMock()
        mock_container.logs.return_value = iter(
            [
                b'{"event": "line1", "level": "info"}\n',
            ]
        )
        mock_podman.containers.get.return_value = mock_container

        forwarder = LogForwarder(mock_podman, redis_url=url, poll_interval=0.2)

        subscriber = Redis.from_url(url, decode_responses=True)
        pubsub = subscriber.pubsub()
        await pubsub.subscribe(LOGS_CHANNEL)
        await pubsub.get_message(timeout=1.0)

        task = asyncio.create_task(forwarder.run())
        try:
            # Wait for first message
            for _ in range(20):
                msg = await pubsub.get_message(timeout=0.1)
                if msg and msg["type"] == "message":
                    break
                await asyncio.sleep(0.1)

            # Remove the container from mock
            mock_podman.list_managed_containers.return_value = []

            # Wait a polling cycle, then check no more messages
            await asyncio.sleep(0.5)
            stale_msg = await pubsub.get_message(timeout=0.3)
            # Should be None or not a message type
            has_stale = stale_msg is not None and stale_msg["type"] == "message"
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await pubsub.unsubscribe(LOGS_CHANNEL)
            await cast(Any, pubsub).aclose()
            await cast(Any, subscriber).aclose()

        assert not has_stale, "Should not receive messages after container removal"

    async def test_graceful_shutdown_via_cancel(self, redis_container: RedisContainer) -> None:
        """CancelledError gracefully shuts down the LogForwarder."""
        url = build_redis_url(redis_container)

        mock_podman = _make_mock_podman(containers=[])
        forwarder = LogForwarder(mock_podman, redis_url=url, poll_interval=0.2)

        task = asyncio.create_task(forwarder.run())
        # Let it run a few poll cycles
        await asyncio.sleep(0.5)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Verify internal state is clean
        assert len(forwarder._follow_tasks) == 0, "Follow tasks should be cleared"
