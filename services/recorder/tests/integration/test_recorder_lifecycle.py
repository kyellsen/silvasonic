"""Integration tests: RecorderService ↔ Redis.

Verifies the real data-flow through the chain specific to the Recorder:

    RecorderService._setup()
    → ServiceContext.setup()
    → HeartbeatPublisher (standard, no extra meta)
    → _monitor_recording() updates health

Uses the shared ``redis_container`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast
from unittest.mock import patch

import pytest
from redis.asyncio import Redis
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer


@pytest.mark.integration
class TestRecorderLifecycleRedis:
    """Verify RecorderService lifecycle with real Redis."""

    async def test_setup_creates_heartbeat(self, redis_container: RedisContainer) -> None:
        """After _setup(), heartbeat is active and resource_collector is present."""
        from silvasonic.recorder.__main__ import RecorderService

        url = build_redis_url(redis_container)

        svc = RecorderService.__new__(RecorderService)
        from silvasonic.core.service import SilvaService

        SilvaService.__init__(svc, redis_url=url, instance_id="rec-int-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            assert svc._ctx.heartbeat is not None, "Heartbeat not created with real Redis"
            assert svc._ctx.resource_collector is not None
        finally:
            await svc._teardown()

    async def test_heartbeat_data_in_redis(self, redis_container: RedisContainer) -> None:
        """Redis heartbeat payload contains correct service name, health, and resources."""
        from silvasonic.recorder.__main__ import RecorderService

        url = build_redis_url(redis_container)
        instance_id = "rec-hb-01"

        svc = RecorderService.__new__(RecorderService)
        from silvasonic.core.service import SilvaService

        SilvaService.__init__(svc, redis_url=url, instance_id=instance_id, heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            svc.health.update_status("recorder", True, "running")
            await asyncio.sleep(1.5)
        finally:
            await svc._teardown()

        redis = Redis.from_url(url, decode_responses=True)
        key = f"silvasonic:status:{instance_id}"
        raw = await redis.get(key)
        assert raw is not None, f"Heartbeat key {key} not found in Redis"

        payload = json.loads(raw)
        assert payload["service"] == "recorder"
        assert payload["instance_id"] == instance_id
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]

        await cast(Any, redis).aclose()

    async def test_monitor_recording_updates_health(self, redis_container: RedisContainer) -> None:
        """_monitor_recording() updates health component to 'Recording active'."""
        from silvasonic.recorder.__main__ import RecorderService

        url = build_redis_url(redis_container)

        svc = RecorderService.__new__(RecorderService)
        from silvasonic.core.service import SilvaService

        SilvaService.__init__(svc, redis_url=url, instance_id="rec-mr-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            # Run one iteration of _monitor_recording
            task = asyncio.create_task(svc._monitor_recording())
            await asyncio.sleep(0.5)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            status = svc.health.get_status()
            assert "recording" in status["components"]
            assert status["components"]["recording"]["healthy"] is True
            assert status["components"]["recording"]["details"] == "Recording active"
        finally:
            await svc._teardown()

    async def test_teardown_stops_heartbeat(self, redis_container: RedisContainer) -> None:
        """After _teardown(), the heartbeat background task is done."""
        from silvasonic.recorder.__main__ import RecorderService

        url = build_redis_url(redis_container)

        svc = RecorderService.__new__(RecorderService)
        from silvasonic.core.service import SilvaService

        SilvaService.__init__(svc, redis_url=url, instance_id="rec-td-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        heartbeat = svc._ctx.heartbeat
        assert heartbeat is not None
        assert heartbeat._task is not None
        assert not heartbeat._task.done()

        await svc._teardown()

        assert heartbeat._task.done()
