"""Integration tests: RecorderService ↔ Redis.

Verifies the real data-flow through the chain specific to the Recorder:

    RecorderService._setup()
    → ServiceContext.setup()
    → HeartbeatPublisher (standard, no extra meta)
    → _monitor_recording() updates health

Uses the shared ``redis_container`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``) and the local ``recorder_service`` fixture.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer


@pytest.mark.integration
class TestRecorderLifecycleRedis:
    """Verify RecorderService lifecycle with real Redis."""

    async def test_setup_creates_heartbeat(self, recorder_service: Any) -> None:
        """After _setup(), heartbeat is active and resource_collector is present."""
        assert recorder_service._ctx.heartbeat is not None, "Heartbeat not created with real Redis"
        assert recorder_service._ctx.resource_collector is not None

    async def test_heartbeat_data_in_redis(
        self, recorder_service: Any, redis_container: RedisContainer
    ) -> None:
        """Redis heartbeat payload contains correct service name, health, and resources."""
        recorder_service.health.update_status("recorder", True, "running")
        await asyncio.sleep(1.5)

        url = build_redis_url(redis_container)
        redis = Redis.from_url(url, decode_responses=True)
        instance_id = "test_heartbeat_data_in_redis"
        key = f"silvasonic:status:{instance_id}"
        raw = await redis.get(key)
        assert raw is not None, f"Heartbeat key {key} not found in Redis"

        payload = json.loads(raw)
        assert payload["service"] == "recorder"
        assert payload["instance_id"] == instance_id
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]

        await cast(Any, redis).aclose()

    async def test_monitor_recording_updates_health(self, recorder_service: Any) -> None:
        """_monitor_recording() updates health component status.

        Without a running pipeline, the monitor reports 'Pipeline not initialized'.
        """
        task = asyncio.create_task(recorder_service._monitor_recording())
        await asyncio.sleep(0.5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        status = recorder_service.health.get_status()
        assert "recording" in status["components"]
        assert status["components"]["recording"]["healthy"] is False
        assert status["components"]["recording"]["details"] == "Pipeline not initialized"

    async def test_teardown_stops_heartbeat(self, recorder_service: Any) -> None:
        """After _teardown(), the heartbeat background task is done."""
        heartbeat = recorder_service._ctx.heartbeat
        assert heartbeat is not None
        assert heartbeat._task is not None
        assert not heartbeat._task.done()

        await recorder_service._teardown()

        assert heartbeat._task.done()
