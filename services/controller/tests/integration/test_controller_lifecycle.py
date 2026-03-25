"""Integration tests: ControllerService ↔ Redis / Postgres.

Verifies the real data-flow through the chain specific to the Controller:

    ControllerService._setup()
    → ServiceContext.setup()
    → HeartbeatPublisher with get_extra_meta() (host_resources)
    → _monitor_database() → check_database_connection() → real Postgres

Uses shared ``redis_container`` and ``postgres_container`` fixtures from
``silvasonic-test-utils`` (surfaced via root ``conftest.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast
from unittest.mock import patch

import pytest
from redis.asyncio import Redis
from silvasonic.test_utils.helpers import build_postgres_url, build_redis_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.mark.integration
class TestControllerLifecycleRedis:
    """Verify ControllerService lifecycle with real Redis."""

    async def test_setup_creates_heartbeat(self, redis_container: RedisContainer) -> None:
        """After _setup(), heartbeat is active and resource_collector is present."""
        from silvasonic.controller.__main__ import ControllerService

        url = build_redis_url(redis_container)
        svc = ControllerService.__new__(ControllerService)
        # Manually init with Redis URL (bypass env-var based __init__)
        svc.__class__ = ControllerService
        from silvasonic.core.resources import HostResourceCollector

        svc._host_resources = HostResourceCollector()
        from silvasonic.core.service import SilvaService

        SilvaService.__init__(svc, redis_url=url, instance_id="ctrl-int-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            assert svc._ctx.heartbeat is not None, "Heartbeat not created with real Redis"
            assert svc._ctx.resource_collector is not None
        finally:
            await svc._teardown()

    async def test_heartbeat_contains_host_resources(self, redis_container: RedisContainer) -> None:
        """Redis heartbeat payload includes meta.host_resources from get_extra_meta()."""
        from silvasonic.controller.__main__ import ControllerService

        url = build_redis_url(redis_container)
        instance_id = "ctrl-hr-01"

        svc = ControllerService.__new__(ControllerService)
        from silvasonic.core.resources import HostResourceCollector
        from silvasonic.core.service import SilvaService

        svc._host_resources = HostResourceCollector()
        SilvaService.__init__(svc, redis_url=url, instance_id=instance_id, heartbeat_interval=0.1)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            svc.health.update_status("controller", True, "running")
            await asyncio.sleep(0.2)
        finally:
            await svc._teardown()

        redis = Redis.from_url(url, decode_responses=True)
        key = f"silvasonic:status:{instance_id}"
        raw = await redis.get(key)
        assert raw is not None, f"Heartbeat key {key} not found in Redis"

        payload = json.loads(raw)
        assert payload["service"] == "controller"
        assert payload["instance_id"] == instance_id
        assert "host_resources" in payload["meta"], "host_resources missing from heartbeat"
        hr = payload["meta"]["host_resources"]
        assert "cpu_percent" in hr
        assert "memory_used_mb" in hr

        await cast(Any, redis).aclose()

    async def test_heartbeat_health_status_in_redis(self, redis_container: RedisContainer) -> None:
        """Health status 'ok' appears in Redis after updating health components."""
        from silvasonic.controller.__main__ import ControllerService

        url = build_redis_url(redis_container)
        instance_id = "ctrl-hs-01"

        svc = ControllerService.__new__(ControllerService)
        from silvasonic.core.resources import HostResourceCollector
        from silvasonic.core.service import SilvaService

        svc._host_resources = HostResourceCollector()
        SilvaService.__init__(svc, redis_url=url, instance_id=instance_id, heartbeat_interval=0.1)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            svc.health.update_status("controller", True, "running")
            svc.health.update_status("database", True, "Connected")
            await asyncio.sleep(0.2)
        finally:
            await svc._teardown()

        redis = Redis.from_url(url, decode_responses=True)
        raw = await redis.get(f"silvasonic:status:{instance_id}")
        assert raw is not None

        payload = json.loads(raw)
        assert payload["health"]["status"] == "ok"
        assert payload["health"]["components"]["controller"]["healthy"] is True
        assert payload["health"]["components"]["database"]["healthy"] is True

        await cast(Any, redis).aclose()

    async def test_monitor_database_with_real_db(
        self,
        redis_container: RedisContainer,
        postgres_container: PostgresContainer,
    ) -> None:
        """_monitor_database() updates health to 'Connected' against real Postgres."""
        from silvasonic.controller.__main__ import ControllerService

        url = build_redis_url(redis_container)

        svc = ControllerService.__new__(ControllerService)
        from silvasonic.core.resources import HostResourceCollector
        from silvasonic.core.service import SilvaService

        svc._host_resources = HostResourceCollector()
        SilvaService.__init__(svc, redis_url=url, instance_id="ctrl-db-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            # Patch the session factory to point at the testcontainer DB
            pg_url = build_postgres_url(postgres_container)
            engine = create_async_engine(pg_url)
            session_factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )

            with patch(
                "silvasonic.core.database.session._get_session_factory",
                return_value=session_factory,
            ):
                # Run one iteration of _monitor_database
                task = asyncio.create_task(svc._monitor_database())
                await asyncio.sleep(0.5)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            await engine.dispose()

            # Verify health was updated
            status = svc.health.get_status()
            assert "database" in status["components"]
            assert status["components"]["database"]["healthy"] is True
            assert status["components"]["database"]["details"] == "Connected"
        finally:
            await svc._teardown()

    async def test_teardown_stops_heartbeat(self, redis_container: RedisContainer) -> None:
        """After _teardown(), the heartbeat background task is done."""
        from silvasonic.controller.__main__ import ControllerService

        url = build_redis_url(redis_container)

        svc = ControllerService.__new__(ControllerService)
        from silvasonic.core.resources import HostResourceCollector
        from silvasonic.core.service import SilvaService

        svc._host_resources = HostResourceCollector()
        SilvaService.__init__(svc, redis_url=url, instance_id="ctrl-td-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        heartbeat = svc._ctx.heartbeat
        assert heartbeat is not None
        assert heartbeat._task is not None
        assert not heartbeat._task.done()

        await svc._teardown()

        assert heartbeat._task.done()
