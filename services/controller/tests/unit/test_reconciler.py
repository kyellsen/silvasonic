"""Unit tests for DeviceStateEvaluator, ReconciliationLoop, and NudgeSubscriber.

Covers device eligibility evaluation, reconciliation triggering, and Redis
pub/sub message handling.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.nudge_subscriber import NudgeSubscriber
from silvasonic.controller.reconciler import (
    DEFAULT_RECONCILE_INTERVAL_S,
    DeviceStateEvaluator,
    ReconciliationLoop,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def _make_spec(**overrides: Any) -> Tier2ServiceSpec:
    """Create a minimal Tier2ServiceSpec for testing."""
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


# ===================================================================
# DeviceStateEvaluator
# ===================================================================


@pytest.mark.unit
class TestDeviceStateEvaluator:
    """Tests for the DeviceStateEvaluator class."""

    async def test_evaluate_eligible_device(self) -> None:
        """evaluate() returns specs for eligible devices."""
        device = MagicMock()
        device.name = "0869-0389-00000000034F"
        device.status = "online"
        device.enabled = True
        device.enrollment_status = "enrolled"
        device.profile_slug = "test_profile"
        device.config = {"alsa_device": "hw:1,0", "usb_serial": "00000000034F"}

        profile = MagicMock()
        profile.slug = "test_profile"
        profile.config = {"sample_rate": 48000, "channels": 1}

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=profile)

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)

        assert len(specs) == 1
        assert specs[0].name == "silvasonic-recorder-test-profile-034f"

    async def test_evaluate_no_eligible_devices(self) -> None:
        """evaluate() returns empty list when no devices match criteria."""
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)

        assert len(specs) == 0

    async def test_evaluate_missing_profile(self) -> None:
        """evaluate() skips device when linked profile is missing."""
        device = MagicMock()
        device.name = "mic-02"
        device.profile_slug = "nonexistent"
        device.config = {}

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=None)  # Profile not found

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)

        assert len(specs) == 0

    async def test_evaluate_missing_profile_rate_limited(self) -> None:
        """Second call for same device+slug logs debug instead of warning."""
        device = MagicMock()
        device.name = "mic-02"
        device.profile_slug = "nonexistent"
        device.config = {}

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=None)

        evaluator = DeviceStateEvaluator()

        # First call — should log warning
        with patch("silvasonic.controller.reconciler.log") as mock_log:
            await evaluator.evaluate(session)
            mock_log.warning.assert_called_once()
            mock_log.debug.assert_called_once()  # reconciler.evaluated

        # Second call — same device+slug → debug only, no new warning
        with patch("silvasonic.controller.reconciler.log") as mock_log:
            await evaluator.evaluate(session)
            mock_log.warning.assert_not_called()
            # 2 debug calls: missing_profile (rate-limited) + reconciler.evaluated
            assert mock_log.debug.call_count == 2

    async def test_spec_build_failed_skips_device(self) -> None:
        """Evaluator skips devices where build_recorder_spec raises."""
        device = MagicMock()
        device.name = "broken-mic"
        device.status = "online"
        device.enabled = True
        device.enrollment_status = "enrolled"
        device.profile_slug = "broken_profile"

        profile = MagicMock()
        profile.slug = "broken_profile"

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=profile)

        evaluator = DeviceStateEvaluator()

        with patch(
            "silvasonic.controller.reconciler.build_recorder_spec",
            side_effect=ValueError("invalid config"),
        ):
            specs = await evaluator.evaluate(session)

        assert len(specs) == 0


# ===================================================================
# ReconciliationLoop
# ===================================================================


@pytest.mark.unit
class TestReconciliationLoop:
    """Tests for the ReconciliationLoop class."""

    def test_trigger_sets_event(self) -> None:
        """trigger() sets the asyncio Event for immediate reconciliation."""
        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=DEFAULT_RECONCILE_INTERVAL_S)

        assert not loop._trigger_event.is_set()
        loop.trigger()
        assert loop._trigger_event.is_set()

    async def test_reconcile_once(self) -> None:
        """_reconcile_once() calls evaluate and reconcile."""
        mgr = MagicMock()
        mgr.list_managed.return_value = []
        mgr.reconcile = MagicMock()

        reconciler = ReconciliationLoop(mgr, interval=1.0)

        with (
            patch.object(
                reconciler._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await reconciler._reconcile_once()

    async def test_run_loop_handles_exception_and_continues(self) -> None:
        """run() catches exceptions in _reconcile_once and continues."""
        import asyncio

        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=0.01)

        call_count = 0

        async def failing_reconcile() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            raise RuntimeError("DB unavailable")

        with (
            patch.object(loop, "_reconcile_once", side_effect=failing_reconcile),
            pytest.raises(asyncio.CancelledError),
        ):
            await loop.run()

        assert call_count >= 2

    async def test_trigger_wakes_run_loop(self) -> None:
        """trigger() wakes the run loop before the interval expires."""
        import asyncio

        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=999.0)  # Very long interval

        call_count = 0

        async def mock_reconcile() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with patch.object(loop, "_reconcile_once", side_effect=mock_reconcile):

            async def trigger_and_cancel() -> None:
                await asyncio.sleep(0.01)
                loop.trigger()

            task = asyncio.create_task(trigger_and_cancel())
            with pytest.raises(asyncio.CancelledError):
                await loop.run()
            await task

        assert call_count >= 2

    async def test_reconcile_once_calls_evaluate_and_reconcile(self) -> None:
        """_reconcile_once() queries DB, lists containers, and reconciles."""
        mgr = MagicMock()
        mgr.list_managed.return_value = [{"name": "existing"}]
        mock_spec = _make_spec()

        loop = ReconciliationLoop(mgr, interval=1.0)

        with (
            patch.object(
                loop._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[mock_spec],
            ),
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            await loop._reconcile_once()

        mgr.reconcile.assert_called_once()
        args = mgr.reconcile.call_args[0]
        assert args[0] == [mock_spec]
        assert args[1] == [{"name": "existing"}]


# ===================================================================
# NudgeSubscriber
# ===================================================================


@pytest.mark.unit
class TestNudgeSubscriber:
    """Tests for the NudgeSubscriber class."""

    def test_init(self) -> None:
        """NudgeSubscriber initializes with reconciler and redis_url."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://test:6379/0")
        assert sub._redis_url == "redis://test:6379/0"
        assert sub._reconciler is reconciler

    def test_handle_reconcile_triggers(self) -> None:
        """_handle_message() triggers reconciliation on 'reconcile' payload."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": b"reconcile"})
        reconciler.trigger.assert_called_once()

    def test_handle_subscribe_ignored(self) -> None:
        """_handle_message() ignores non-message types (e.g. 'subscribe')."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "subscribe", "data": b"silvasonic:nudge"})
        reconciler.trigger.assert_not_called()

    def test_handle_unknown_payload_ignored(self) -> None:
        """_handle_message() ignores unknown message payloads."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": b"restart"})
        reconciler.trigger.assert_not_called()

    def test_handle_string_data(self) -> None:
        """_handle_message() handles string data (not bytes)."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": "reconcile"})
        reconciler.trigger.assert_called_once()

    async def test_run_reconnects_on_error(self) -> None:
        """run() reconnects automatically after Redis disconnection."""
        import asyncio

        import redis.asyncio as aioredis

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://fake:6379/0")

        call_count = 0

        def fake_from_url(url: str, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            raise ConnectionError("Redis unavailable")

        with (
            patch.object(aioredis, "from_url", side_effect=fake_from_url),
            patch(
                "silvasonic.controller.nudge_subscriber.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await sub.run()

        assert call_count >= 2
