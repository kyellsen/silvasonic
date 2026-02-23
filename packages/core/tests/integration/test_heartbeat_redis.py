"""Integration tests: ServiceContext ↔ Redis / HeartbeatPublisher.

Verifies the real data-flow through the chain:

    ServiceContext.setup()
    → get_redis_connection()
    → HeartbeatPublisher.publish_once()
    → Redis SET + PUBLISH

Uses the shared ``redis_container`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``).  Requires Podman on the host.
The container is started once per session and shared across all tests.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from silvasonic.core.health import HealthMonitor
from silvasonic.core.heartbeat import HeartbeatPublisher
from silvasonic.core.redis import get_redis_connection
from silvasonic.core.service_context import ServiceContext
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer


@pytest.mark.integration
class TestRedisConnection:
    """Verify ``get_redis_connection()`` against a real Redis instance."""

    async def test_redis_connection_real(self, redis_container: RedisContainer) -> None:
        """get_redis_connection() returns a working Redis client, not None."""
        url = build_redis_url(redis_container)
        redis = await get_redis_connection(url)

        assert redis is not None, "Expected a Redis client but got None"
        # Verify the connection actually works
        pong: Any = await cast(Any, redis).ping()
        assert pong is True
        await cast(Any, redis).aclose()


@pytest.mark.integration
class TestHeartbeatPublishRedis:
    """Verify HeartbeatPublisher writes to real Redis."""

    async def test_heartbeat_publish_set_and_ttl(self, redis_container: RedisContainer) -> None:
        """publish_once() writes a key with TTL and valid JSON payload."""
        url = build_redis_url(redis_container)
        redis = await get_redis_connection(url)
        assert redis is not None

        pub = HeartbeatPublisher(
            redis=redis,
            service_name="test-integration",
            instance_id="int-01",
            interval=10.0,
        )

        # Wire up a real health monitor
        hm = HealthMonitor()
        hm.update_status("test", True, "ok")
        pub.set_health_provider(hm.get_status)

        # Publish a single heartbeat
        await pub.publish_once({"cpu_percent": 5.0, "memory_mb": 128.0})

        # Verify the key exists and is valid JSON
        key = "silvasonic:status:int-01"
        raw = await redis.get(key)
        assert raw is not None, f"Key {key} not found in Redis"

        payload = json.loads(raw)
        assert payload["service"] == "test-integration"
        assert payload["instance_id"] == "int-01"
        assert "health" in payload
        assert "meta" in payload
        assert payload["meta"]["resources"]["cpu_percent"] == 5.0

        # Verify TTL is set (should be ≤ 30s)
        ttl = await redis.ttl(key)
        assert 0 < ttl <= 30, f"Expected TTL 1-30s, got {ttl}"

        await cast(Any, redis).aclose()

    async def test_heartbeat_publish_pubsub(self, redis_container: RedisContainer) -> None:
        """A SUBSCRIBE listener receives the heartbeat message."""
        url = build_redis_url(redis_container)
        redis = await get_redis_connection(url)
        assert redis is not None

        # Create a second connection for the subscriber (Redis requirement)
        subscriber_redis = Redis.from_url(url, decode_responses=True)
        pubsub = subscriber_redis.pubsub()
        await pubsub.subscribe("silvasonic:status")

        # Drain the subscription confirmation message
        await pubsub.get_message(timeout=2.0)

        pub = HeartbeatPublisher(
            redis=redis,
            service_name="test-pubsub",
            instance_id="pubsub-01",
            interval=10.0,
        )
        await pub.publish_once({"cpu_percent": 1.0})

        # Wait for the published message (with timeout)
        msg = await pubsub.get_message(timeout=5.0)
        assert msg is not None, "No message received on silvasonic:status channel"
        assert msg["type"] == "message"

        payload = json.loads(msg["data"])
        assert payload["service"] == "test-pubsub"
        assert payload["instance_id"] == "pubsub-01"

        await pubsub.unsubscribe("silvasonic:status")
        await cast(Any, pubsub).aclose()
        await cast(Any, subscriber_redis).aclose()
        await cast(Any, redis).aclose()


@pytest.mark.integration
class TestServiceContextLifecycle:
    """Verify full ServiceContext lifecycle with real Redis."""

    async def test_service_context_full_lifecycle(self, redis_container: RedisContainer) -> None:
        """ServiceContext setup → heartbeat publish → teardown, all against real Redis."""
        url = build_redis_url(redis_container)

        async with ServiceContext(
            service_name="integration-test",
            service_port=19876,
            instance_id="ctx-01",
            redis_url=url,
            heartbeat_interval=1.0,
            skip_health_server=True,
        ) as ctx:
            # Verify heartbeat was started
            assert ctx.heartbeat is not None, "Heartbeat should be active after setup"
            assert ctx.resource_collector is not None

            # Let the heartbeat loop fire at least once
            await asyncio.sleep(1.5)

        # After teardown: verify the key was written to Redis
        redis = Redis.from_url(url, decode_responses=True)
        key = "silvasonic:status:ctx-01"
        raw = await redis.get(key)
        assert raw is not None, f"Expected heartbeat key {key} in Redis after lifecycle"

        payload = json.loads(raw)
        assert payload["service"] == "integration-test"
        assert payload["instance_id"] == "ctx-01"

        await cast(Any, redis).aclose()
