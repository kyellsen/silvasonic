"""Unit tests for HeartbeatPayload, HeartbeatPublisher, and get_redis_connection.

Covers payload validation, publish/subscribe, activity labelling,
meta/health providers, loop execution, and Redis connection handling.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.heartbeat import (
    DEFAULT_HEARTBEAT_TTL_S,
    HeartbeatPayload,
    HeartbeatPublisher,
)


@pytest.mark.unit
class TestHeartbeatPayload:
    """Tests for the Pydantic heartbeat payload model."""

    def test_valid_payload(self) -> None:
        """A valid payload instantiates and serializes correctly."""
        p = HeartbeatPayload(
            service="recorder",
            instance_id="ultramic-01",
            timestamp=1706612400.123,
            health={"status": "ok", "components": {}},
            activity="recording",
            meta={"resources": {"cpu_percent": 12.3}},
        )

        d = p.model_dump()
        assert d["service"] == "recorder"
        assert d["instance_id"] == "ultramic-01"
        assert d["activity"] == "recording"

    def test_missing_field_raises(self) -> None:
        """Missing required fields raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HeartbeatPayload(service="test")  # type: ignore[call-arg]


@pytest.mark.unit
class TestHeartbeatPublisher:
    """Tests for the HeartbeatPublisher."""

    def _make_publisher(self) -> tuple[HeartbeatPublisher, AsyncMock]:
        """Create a publisher with a mocked Redis client."""
        redis_mock = AsyncMock()
        pub = HeartbeatPublisher(
            redis=redis_mock,
            service_name="test-service",
            instance_id="test-01",
            interval=0.01,
        )
        return pub, redis_mock

    def test_build_payload_returns_pydantic_model(self) -> None:
        """_build_payload returns a HeartbeatPayload instance."""
        pub, _ = self._make_publisher()
        payload = pub._build_payload({"cpu_percent": 5.0})

        assert isinstance(payload, HeartbeatPayload)
        assert payload.service == "test-service"
        assert payload.instance_id == "test-01"
        assert payload.meta["resources"]["cpu_percent"] == 5.0

    def test_build_payload_with_health_provider(self) -> None:
        """Health provider function is called and integrated."""
        pub, _ = self._make_publisher()
        pub.set_health_provider(
            lambda: {
                "status": "ok",
                "components": {"main": {"healthy": True}},
            }
        )
        payload = pub._build_payload({})

        assert payload.health["status"] == "ok"
        assert "main" in payload.health["components"]

    def test_build_payload_health_provider_error(self) -> None:
        """Gracefully handles health provider exceptions."""
        pub, _ = self._make_publisher()

        def broken_health() -> dict[str, Any]:
            raise RuntimeError("broken")

        pub.set_health_provider(broken_health)
        payload = pub._build_payload({})

        assert payload.health["status"] == "error"

    def test_build_payload_with_meta_provider(self) -> None:
        """Meta provider fields are merged into meta."""
        pub, _ = self._make_publisher()
        pub.set_meta_provider(lambda: {"db_level": -45.2})
        payload = pub._build_payload({"cpu_percent": 1.0})

        assert payload.meta["db_level"] == -45.2
        assert payload.meta["resources"]["cpu_percent"] == 1.0

    def test_meta_provider_exception_handled(self) -> None:
        """Meta provider exception results in meta without extra fields."""
        pub, _ = self._make_publisher()

        def broken_meta() -> dict[str, Any]:
            raise RuntimeError("broken meta")

        pub.set_meta_provider(broken_meta)
        payload = pub._build_payload({"cpu_percent": 1.0})

        assert "resources" in payload.meta
        assert payload.meta["resources"]["cpu_percent"] == 1.0

    def test_meta_provider_non_dict_ignored(self) -> None:
        """Meta provider returning non-dict is not merged."""
        pub, _ = self._make_publisher()

        def bad_meta() -> Any:
            return "not a dict"

        pub.set_meta_provider(bad_meta)
        payload = pub._build_payload({})

        assert "resources" in payload.meta

    def test_set_activity(self) -> None:
        """Activity label is included in payload."""
        pub, _ = self._make_publisher()
        pub.set_activity("recording")
        payload = pub._build_payload({})

        assert payload.activity == "recording"

    async def test_publish_once_calls_set_and_publish(self) -> None:
        """publish_once performs both SET (with TTL) and PUBLISH."""
        pub, redis_mock = self._make_publisher()
        await pub.publish_once({"cpu_percent": 3.0})

        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        assert call_args[0][0] == "silvasonic:status:test-01"
        assert call_args[1]["ex"] == DEFAULT_HEARTBEAT_TTL_S

        redis_mock.publish.assert_called_once()
        pub_args = redis_mock.publish.call_args
        assert pub_args[0][0] == "silvasonic:status"

    async def test_publish_once_handles_redis_error(self) -> None:
        """publish_once catches Redis errors without raising."""
        pub, redis_mock = self._make_publisher()
        redis_mock.set.side_effect = ConnectionError("Redis down")

        # Should NOT raise
        await pub.publish_once({})

    async def test_start_and_stop(self) -> None:
        """Start creates a background task, stop cancels it."""
        pub, _ = self._make_publisher()
        collector = MagicMock()
        collector.collect.return_value = {}

        task = pub.start(collector)
        assert isinstance(task, asyncio.Task)
        assert not task.done()

        await pub.stop()
        assert task.done()

    async def test_loop_collects_and_publishes(self) -> None:
        """The _loop coroutine calls collect() and publish_once()."""
        pub, redis_mock = self._make_publisher()
        collector = MagicMock()
        collector.collect.return_value = {"cpu_percent": 5.0}

        pub.start(collector)
        await asyncio.sleep(0.05)
        await pub.stop()

        collector.collect.assert_called()
        redis_mock.set.assert_called()

    async def test_loop_handles_exception(self) -> None:
        """_loop continues after a non-cancellation exception."""
        pub, _ = self._make_publisher()
        collector = MagicMock()
        collector.collect.side_effect = [
            RuntimeError("oops"),
            {"cpu": 1.0},
        ]

        pub.start(collector)
        await asyncio.sleep(0.05)
        await pub.stop()

        assert collector.collect.call_count >= 1


@pytest.mark.unit
class TestGetRedisConnection:
    """Tests for the shared Redis connection helper."""

    @patch("silvasonic.core.redis.Redis")
    async def test_successful_connection(self, mock_redis_cls: MagicMock) -> None:
        """Returns a Redis client on success."""
        from silvasonic.core.redis import get_redis_connection

        mock_client = AsyncMock()
        mock_redis_cls.from_url.return_value = mock_client

        result = await get_redis_connection("redis://localhost:6379/0")

        assert result is mock_client
        mock_client.ping.assert_awaited_once()

    @patch("silvasonic.core.redis.Redis")
    async def test_connection_failure_returns_none(self, mock_redis_cls: MagicMock) -> None:
        """Returns None if Redis is unreachable."""
        from silvasonic.core.redis import get_redis_connection

        mock_client = AsyncMock()
        mock_client.ping.side_effect = ConnectionError("unreachable")
        mock_redis_cls.from_url.return_value = mock_client

        result = await get_redis_connection("redis://localhost:6379/0")

        assert result is None
