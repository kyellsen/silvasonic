"""Unit tests for the Reconciler heartbeat health evaluation (Issue 006).

Covers the Redis heartbeat freshness check in ReconciliationLoop._reconcile_once()
(reconciler.py L225-284) which previously had 0% coverage.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.reconciler import (
    DeviceStateEvaluator,
    ReconciliationLoop,
)
from silvasonic.controller.worker_evaluator import SystemWorkerEvaluator


def _make_spec(**overrides: Any) -> Tier2ServiceSpec:
    defaults: dict[str, Any] = {
        "image": "localhost/silvasonic_recorder:latest",
        "name": "silvasonic-recorder-test",
        "network": "silvasonic-net",
        "memory_limit": "512m",
        "cpu_limit": 1.0,
        "oom_score_adj": -999,
        "labels": {
            "io.silvasonic.tier": "2",
            "io.silvasonic.owner": "controller",
            "io.silvasonic.service": "recorder",
        },
    }
    defaults.update(overrides)
    return Tier2ServiceSpec(**defaults)


class FakeEvaluator(DeviceStateEvaluator, SystemWorkerEvaluator):
    """Fake evaluator returning static specs."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return super().__new__(cls)

    def __init__(self, specs: list[Tier2ServiceSpec] | None = None) -> None:
        """Initialize with static specs to return."""
        self.specs = specs or []

    async def evaluate(self, session: Any) -> list[Tier2ServiceSpec]:
        return self.specs


def _make_heartbeat(
    *,
    timestamp: float | None = None,
    health_status: str = "ok",
) -> str:
    """Build a JSON heartbeat payload."""
    ts = timestamp if timestamp is not None else time.time()
    return json.dumps({"timestamp": ts, "health": {"status": health_status}})


def _make_loop(
    *,
    actual_containers: list[dict[str, Any]] | None = None,
    stale_timeout_s: float = 45.0,
) -> ReconciliationLoop:
    """Create a ReconciliationLoop with mocked dependencies."""
    mgr = MagicMock()
    mgr.list_managed.return_value = actual_containers or []
    mgr.sync_state = MagicMock()
    mgr.stop_and_remove = MagicMock()

    loop = ReconciliationLoop(
        mgr,
        hardware_evaluator=FakeEvaluator([]),
        sys_evaluator=FakeEvaluator([]),
        interval=1.0,
        redis_url="redis://fake:6379/0",
        stale_timeout_s=stale_timeout_s,
    )
    return loop


@pytest.mark.unit
class TestReconcilerHeartbeatHealth:
    """Tests for Redis heartbeat evaluation during reconciliation."""

    async def _run_with_redis(
        self,
        loop: ReconciliationLoop,
        redis_data: Mapping[str, str | None],
    ) -> tuple[Any, Any]:
        """Run _reconcile_once with mocked Redis and DB session.

        Returns (manager_mock, sync_state_call_args).
        """
        mock_redis = AsyncMock()

        async def fake_get(key: str) -> bytes | None:
            val = redis_data.get(key)
            return val.encode() if val else None

        mock_redis.get = fake_get
        mock_redis.aclose = AsyncMock()

        with (
            patch("silvasonic.controller.reconciler.get_session") as mock_session,
            patch(
                "silvasonic.core.redis.get_redis_connection",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await loop._reconcile_once()

        mgr: Any = loop._manager
        if mgr.sync_state.called:
            return mgr, mgr.sync_state.call_args[0]
        return mgr, ([], [])

    async def test_healthy_container_remains_in_actual(self) -> None:
        """Fresh heartbeat → container kept in actual list."""
        container = {
            "name": "silvasonic-recorder-mic1",
            "labels": {"io.silvasonic.device_id": "mic1"},
        }
        loop = _make_loop(actual_containers=[container])

        heartbeat = _make_heartbeat(timestamp=time.time(), health_status="ok")
        redis_data = {"silvasonic:status:mic1": heartbeat}

        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)

        assert len(actual) == 1
        assert actual[0]["name"] == "silvasonic-recorder-mic1"
        mgr.stop_and_remove.assert_not_called()

    async def test_missing_heartbeat_removes_container(self) -> None:
        """No Redis entry for device → treated as unhealthy, stopped."""
        container = {
            "name": "silvasonic-recorder-mic2",
            "labels": {"io.silvasonic.device_id": "mic2"},
        }
        loop = _make_loop(actual_containers=[container])

        mgr, (_desired, actual) = await self._run_with_redis(loop, {})

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once_with("silvasonic-recorder-mic2")

    async def test_stale_heartbeat_removes_container(self) -> None:
        """Heartbeat older than stale_timeout → unhealthy, stopped."""
        container = {
            "name": "silvasonic-recorder-mic3",
            "labels": {"io.silvasonic.device_id": "mic3"},
        }
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        old_ts = time.time() - 120.0  # 2 minutes ago
        heartbeat = _make_heartbeat(timestamp=old_ts, health_status="ok")
        redis_data = {"silvasonic:status:mic3": heartbeat}

        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once()

    async def test_error_health_status_removes_container(self) -> None:
        """Heartbeat with health.status != ok/starting → unhealthy."""
        container = {
            "name": "silvasonic-recorder-mic4",
            "labels": {"io.silvasonic.device_id": "mic4"},
        }
        loop = _make_loop(actual_containers=[container])

        heartbeat = _make_heartbeat(timestamp=time.time(), health_status="error")
        redis_data = {"silvasonic:status:mic4": heartbeat}

        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once()

    async def test_invalid_heartbeat_json_removes_container(self) -> None:
        """Unparseable JSON → treated as unhealthy."""
        container = {
            "name": "silvasonic-recorder-mic5",
            "labels": {"io.silvasonic.device_id": "mic5"},
        }
        loop = _make_loop(actual_containers=[container])

        redis_data = {"silvasonic:status:mic5": "not-valid-json{{{"}

        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once()

    async def test_container_without_device_label_always_healthy(
        self,
    ) -> None:
        """Non-recorder containers (no device_id label) skip check."""
        container = {
            "name": "silvasonic-processor",
            "labels": {"io.silvasonic.service": "processor"},
        }
        loop = _make_loop(actual_containers=[container])

        mgr, (_desired, actual) = await self._run_with_redis(loop, {})

        assert len(actual) == 1
        mgr.stop_and_remove.assert_not_called()
