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
    MicrophoneStateEvaluator,
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


class FakeEvaluator(MicrophoneStateEvaluator, SystemWorkerEvaluator):
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

    async def test_missing_heartbeat_tolerated_during_grace(self) -> None:
        """No Redis entry yet → kept: the container may still be booting.

        Redis also loses every key on restart (``--save ""``); killing on the
        first missing heartbeat would take down every running Recorder.
        """
        container = {
            "name": "silvasonic-recorder-mic2",
            "labels": {"io.silvasonic.device_id": "mic2"},
        }
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        mgr, (_desired, actual) = await self._run_with_redis(loop, {})

        assert len(actual) == 1
        mgr.stop_and_remove.assert_not_called()

    async def test_missing_heartbeat_removes_container_after_grace(self) -> None:
        """Missing for longer than stale_timeout → unhealthy, stopped."""
        name = "silvasonic-recorder-mic2"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic2"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)
        loop._unhealthy_since[name] = time.monotonic() - 46.0

        mgr, (_desired, actual) = await self._run_with_redis(loop, {})

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once_with(name)
        assert name not in loop._unhealthy_since

    async def test_recovered_heartbeat_resets_grace(self) -> None:
        """A heartbeat that comes back clears the unhealthy mark."""
        name = "silvasonic-recorder-mic2"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic2"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)
        loop._unhealthy_since[name] = time.monotonic() - 30.0

        heartbeat = _make_heartbeat(timestamp=time.time(), health_status="ok")
        mgr, (_desired, actual) = await self._run_with_redis(
            loop, {"silvasonic:status:mic2": heartbeat}
        )

        assert len(actual) == 1
        mgr.stop_and_remove.assert_not_called()
        assert name not in loop._unhealthy_since

    async def test_unhealthy_mark_dropped_for_vanished_container(self) -> None:
        """Bookkeeping for a container that no longer exists is discarded."""
        loop = _make_loop(actual_containers=[])
        loop._unhealthy_since["silvasonic-recorder-gone"] = time.monotonic()
        loop._heartbeat_seen["silvasonic-recorder-gone"] = (time.time(), time.monotonic())

        await self._run_with_redis(loop, {})

        assert loop._unhealthy_since == {}
        assert loop._heartbeat_seen == {}

    async def test_stale_heartbeat_removes_container(self) -> None:
        """A heartbeat unchanged for longer than stale_timeout → stopped at once."""
        name = "silvasonic-recorder-mic3"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic3"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        ts = time.time() - 46.0
        loop._heartbeat_seen[name] = (ts, time.monotonic() - 46.0)
        heartbeat = _make_heartbeat(timestamp=ts, health_status="ok")

        mgr, (_desired, actual) = await self._run_with_redis(
            loop, {"silvasonic:status:mic3": heartbeat}
        )

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once_with(name)
        # The successor is judged on its own heartbeats
        assert name not in loop._heartbeat_seen

    async def test_forward_clock_step_does_not_evict(self) -> None:
        """An NTP step at boot makes the last heartbeat look hours old: kept.

        A Pi without a real-time clock boots with a stale time and jumps
        forward on its first NTP sync (Issue 002). Comparing the heartbeat
        with the wall clock replaced every Recorder at that moment.
        """
        name = "silvasonic-recorder-mic3"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic3"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        ts = time.time() - 3 * 3600.0  # written before the clock stepped 3 h ahead
        loop._heartbeat_seen[name] = (ts, time.monotonic() - 5.0)
        heartbeat = _make_heartbeat(timestamp=ts, health_status="ok")

        mgr, (_desired, actual) = await self._run_with_redis(
            loop, {"silvasonic:status:mic3": heartbeat}
        )

        assert len(actual) == 1
        mgr.stop_and_remove.assert_not_called()

    async def test_backward_clock_step_still_detects_a_hang(self) -> None:
        """A heartbeat from the future no longer hides a Recorder that stopped publishing."""
        name = "silvasonic-recorder-mic3"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic3"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        ts = time.time() + 3600.0  # written before the clock stepped 1 h back
        loop._heartbeat_seen[name] = (ts, time.monotonic() - 46.0)
        heartbeat = _make_heartbeat(timestamp=ts, health_status="ok")

        mgr, (_desired, actual) = await self._run_with_redis(
            loop, {"silvasonic:status:mic3": heartbeat}
        )

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once_with(name)

    async def test_new_heartbeat_restarts_the_clock(self) -> None:
        """Each new publish counts as fresh, whatever its timestamp says."""
        name = "silvasonic-recorder-mic3"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic3"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        loop._heartbeat_seen[name] = (time.time() - 60.0, time.monotonic() - 60.0)
        new_ts = time.time() - 50.0  # older than stale_timeout by the wall clock
        heartbeat = _make_heartbeat(timestamp=new_ts, health_status="ok")

        mgr, (_desired, actual) = await self._run_with_redis(
            loop, {"silvasonic:status:mic3": heartbeat}
        )

        assert len(actual) == 1
        mgr.stop_and_remove.assert_not_called()
        assert loop._heartbeat_seen[name][0] == new_ts

    async def test_error_health_status_removes_container_after_grace(self) -> None:
        """health.status != ok/starting → kept at first, stopped once it persists."""
        name = "silvasonic-recorder-mic4"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic4"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)

        heartbeat = _make_heartbeat(timestamp=time.time(), health_status="error")
        redis_data = {"silvasonic:status:mic4": heartbeat}

        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)
        assert len(actual) == 1
        mgr.stop_and_remove.assert_not_called()

        loop._unhealthy_since[name] = time.monotonic() - 46.0
        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once_with(name)

    async def test_invalid_heartbeat_json_removes_container_after_grace(self) -> None:
        """Unparseable JSON → treated as unhealthy once it persists."""
        name = "silvasonic-recorder-mic5"
        container = {"name": name, "labels": {"io.silvasonic.device_id": "mic5"}}
        loop = _make_loop(actual_containers=[container], stale_timeout_s=45.0)
        loop._unhealthy_since[name] = time.monotonic() - 46.0

        redis_data = {"silvasonic:status:mic5": "not-valid-json{{{"}

        mgr, (_desired, actual) = await self._run_with_redis(loop, redis_data)

        assert len(actual) == 0
        mgr.stop_and_remove.assert_called_once_with(name)

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
