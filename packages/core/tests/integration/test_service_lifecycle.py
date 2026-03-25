"""Integration tests: SilvaService ↔ ServiceContext ↔ real Redis.

Verifies the complete service infrastructure with real Redis:

    SilvaService._setup()
    → ServiceContext.setup()
    → get_redis_connection() (real Redis)
    → HeartbeatPublisher.start() (real background task)
    → heartbeat → Redis SET + PUBLISH
    → SilvaService._teardown()

This is the cross-package integration test that was previously missing:
SilvaService (the base class for all background workers) composes
ServiceContext, which orchestrates health, heartbeat, Redis, and resources.
Unit tests mock all of this — these tests use a real Redis container.

Uses the shared ``redis_container`` fixture from ``silvasonic-test-utils``.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from redis.asyncio import Redis
from silvasonic.core.service import SilvaService
from silvasonic.core.service_context import ServiceContext
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer

# ---------------------------------------------------------------------------
# Tests: SilvaService lifecycle with real Redis
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSilvaServiceLifecycleRedis:
    """Verify SilvaService _setup/_teardown with real Redis.

    Tests the full chain: SilvaService → ServiceContext → Redis/Heartbeat.
    The health HTTP server is skipped (port conflicts in parallel tests).
    """

    async def test_setup_creates_heartbeat_with_real_redis(
        self, redis_container: RedisContainer
    ) -> None:
        """After _setup(), heartbeat is active and connected to real Redis."""
        url = build_redis_url(redis_container)

        class _TestService(SilvaService):
            service_name = "integ-setup"
            service_port = 19876

            async def run(self) -> None:
                pass

        svc = _TestService(redis_url=url, instance_id="setup-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            # Heartbeat should be active
            assert svc._ctx.heartbeat is not None, "Heartbeat not created with real Redis"
            assert svc._ctx.resource_collector is not None
        finally:
            await svc._teardown()

    async def test_heartbeat_data_in_redis_after_lifecycle(
        self, redis_container: RedisContainer
    ) -> None:
        """Heartbeat data is written to Redis during the service lifecycle."""
        url = build_redis_url(redis_container)
        instance_id = "lc-01"

        class _TestService(SilvaService):
            service_name = "lifecycle-test"
            service_port = 19877

            async def run(self) -> None:
                pass

        svc = _TestService(redis_url=url, instance_id=instance_id, heartbeat_interval=0.1)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            # Update health status and let heartbeat fire
            svc.health.update_status("main", True, "running")
            await asyncio.sleep(0.2)
        finally:
            await svc._teardown()

        # Verify heartbeat was written to Redis
        redis = Redis.from_url(url, decode_responses=True)
        key = f"silvasonic:status:{instance_id}"
        raw = await redis.get(key)
        assert raw is not None, f"Expected heartbeat key {key} in Redis"

        payload = json.loads(raw)
        assert payload["service"] == "lifecycle-test"
        assert payload["instance_id"] == instance_id
        assert "health" in payload
        assert payload["health"]["status"] == "ok"
        assert "meta" in payload
        assert "resources" in payload["meta"]

        await redis.aclose()

    async def test_teardown_stops_heartbeat_task(self, redis_container: RedisContainer) -> None:
        """After _teardown(), the heartbeat background task is stopped."""
        url = build_redis_url(redis_container)

        class _TestService(SilvaService):
            service_name = "teardown-test"
            service_port = 19878

            async def run(self) -> None:
                pass

        svc = _TestService(redis_url=url, instance_id="td-01", heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        heartbeat = svc._ctx.heartbeat
        assert heartbeat is not None
        assert heartbeat._task is not None
        assert not heartbeat._task.done()

        await svc._teardown()

        # After teardown, task should be done (cancelled)
        assert heartbeat._task.done()

    async def test_dying_gasp_writes_error_to_redis(self, redis_container: RedisContainer) -> None:
        """publish_dying_gasp writes an error heartbeat to Redis."""
        url = build_redis_url(redis_container)
        instance_id = "crash-01"

        class _TestService(SilvaService):
            service_name = "crash-test"
            service_port = 19879

            async def run(self) -> None:
                pass

        svc = _TestService(redis_url=url, instance_id=instance_id, heartbeat_interval=0.5)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            # Simulate a crash — publish dying gasp
            await svc._publish_dying_gasp(RuntimeError("intentional crash"))
        finally:
            await svc._teardown()

        # Verify dying-gasp was written
        redis = Redis.from_url(url, decode_responses=True)
        key = f"silvasonic:status:{instance_id}"
        raw = await redis.get(key)
        assert raw is not None, f"Dying-gasp key {key} not found in Redis"

        payload = json.loads(raw)
        assert payload["service"] == "crash-test"
        assert payload["health"]["status"] == "error"

        await redis.aclose()

    async def test_get_extra_meta_included_in_heartbeat(
        self, redis_container: RedisContainer
    ) -> None:
        """SilvaService.get_extra_meta() values appear in the Redis heartbeat."""
        url = build_redis_url(redis_container)
        instance_id = "meta-01"

        class _MetaService(SilvaService):
            service_name = "meta-test"
            service_port = 19880

            def get_extra_meta(self) -> dict[str, object]:
                return {"custom_key": "custom_value", "db_level": -42.5}

            async def run(self) -> None:
                pass

        svc = _MetaService(redis_url=url, instance_id=instance_id, heartbeat_interval=0.1)

        with patch("silvasonic.core.service_context.start_health_server"):
            await svc._setup()

        try:
            svc.health.update_status("main", True, "ok")
            await asyncio.sleep(0.2)
        finally:
            await svc._teardown()

        redis = Redis.from_url(url, decode_responses=True)
        key = f"silvasonic:status:{instance_id}"
        raw = await redis.get(key)
        assert raw is not None

        payload = json.loads(raw)
        assert payload["meta"]["custom_key"] == "custom_value"
        assert payload["meta"]["db_level"] == -42.5

        await redis.aclose()


# ---------------------------------------------------------------------------
# Tests: ServiceContext Pub/Sub with real Redis
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestServiceContextPubSub:
    """Verify ServiceContext heartbeat loop publishes to Redis Pub/Sub.

    Complements the existing heartbeat_redis tests by testing the full chain
    when driven from ServiceContext (not direct HeartbeatPublisher usage).
    """

    async def test_heartbeat_received_via_pubsub(self, redis_container: RedisContainer) -> None:
        """A subscriber receives heartbeat messages published by ServiceContext."""
        url = build_redis_url(redis_container)

        # Set up subscriber BEFORE starting the context
        subscriber = Redis.from_url(url, decode_responses=True)
        pubsub = subscriber.pubsub()
        await pubsub.subscribe("silvasonic:status")
        # Drain subscription confirmation
        await pubsub.get_message(timeout=2.0)

        with patch("silvasonic.core.service_context.start_health_server"):
            async with ServiceContext(
                service_name="pubsub-lifecycle",
                service_port=19881,
                instance_id="ps-01",
                redis_url=url,
                heartbeat_interval=0.1,
                skip_health_server=True,
            ) as ctx:
                ctx.health.update_status("test", True, "ok")
                # Wait for at least one heartbeat to fire
                await asyncio.sleep(0.2)

        # Check that at least one message was received
        msg = await pubsub.get_message(timeout=5.0)
        assert msg is not None, "No heartbeat received on silvasonic:status channel"
        assert msg["type"] == "message"

        payload = json.loads(msg["data"])
        assert payload["service"] == "pubsub-lifecycle"
        assert payload["instance_id"] == "ps-01"

        await pubsub.unsubscribe("silvasonic:status")
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await subscriber.aclose()
