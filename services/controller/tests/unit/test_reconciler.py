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


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        """Initialize FakeResult with static items."""
        self._items = items

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items


class FakeSession:
    def __init__(self, devices: list[Any], profile: Any = None) -> None:
        """Initialize FakeSession with static devices and profile."""
        self._devices = devices
        self._profile = profile

    async def execute(self, stmt: Any) -> FakeResult:
        return FakeResult(self._devices)

    async def get(self, model: Any, ident: Any) -> Any:
        return self._profile


@pytest.mark.unit
class TestDeviceStateEvaluator:
    """Tests for DeviceStateEvaluator edge cases using FakeSession doubles."""

    async def test_evaluate_no_eligible_devices(self) -> None:
        """evaluate() returns empty list when no devices match criteria."""
        session = FakeSession(devices=[])

        evaluator = DeviceStateEvaluator()
        # FakeSession doesn't extend from a real session, so we ignore typing here
        specs = await evaluator.evaluate(session)  # type: ignore

        assert len(specs) == 0

    async def test_evaluate_missing_profile(self) -> None:
        """evaluate() skips device when linked profile is missing."""
        device = MagicMock()
        device.name = "mic-02"
        device.profile_slug = "nonexistent"
        device.config = {}

        session = FakeSession(devices=[device], profile=None)

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)  # type: ignore

        assert len(specs) == 0

    async def test_evaluate_missing_profile_rate_limited(self) -> None:
        """Second call for same device+slug logs debug instead of warning."""
        device = MagicMock()
        device.name = "mic-02"
        device.profile_slug = "nonexistent"
        device.config = {}

        session = FakeSession(devices=[device], profile=None)

        evaluator = DeviceStateEvaluator()

        # First call — should log warning
        with patch("silvasonic.controller.reconciler.log") as mock_log:
            await evaluator.evaluate(session)  # type: ignore
            mock_log.warning.assert_called_once()
            mock_log.debug.assert_called_once()  # reconciler.evaluated

        # Second call — same device+slug → debug only, no new warning
        with patch("silvasonic.controller.reconciler.log") as mock_log:
            await evaluator.evaluate(session)  # type: ignore
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

        session = FakeSession(devices=[device], profile=profile)

        evaluator = DeviceStateEvaluator()

        with patch(
            "silvasonic.controller.reconciler.build_recorder_spec",
            side_effect=ValueError("invalid config"),
        ):
            specs = await evaluator.evaluate(session)  # type: ignore

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
        loop = ReconciliationLoop(mgr, interval=1.0)

        assert not loop._trigger_event.is_set()
        loop.trigger()
        assert loop._trigger_event.is_set()

    async def test_reconcile_once(self) -> None:
        """_reconcile_once() calls evaluate and reconcile."""
        mgr = MagicMock()
        mgr.list_managed.return_value = []
        mgr.sync_state = MagicMock()

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

        mgr.sync_state.assert_called_once()
        args = mgr.sync_state.call_args[0]
        assert args[0] == [mock_spec]
        assert args[1] == [{"name": "existing"}]

    async def test_reconcile_once_with_scanner_calls_rescan(self) -> None:
        """_reconcile_once() calls _rescan_hardware when scanner is present."""
        mgr = MagicMock()
        mgr.list_managed.return_value = []
        mgr.sync_state = MagicMock()

        scanner = MagicMock()
        matcher = MagicMock()
        loop = ReconciliationLoop(
            mgr, device_scanner=scanner, profile_matcher=matcher, interval=1.0
        )

        with (
            patch.object(
                loop._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
            patch.object(
                loop,
                "_rescan_hardware",
                new_callable=AsyncMock,
            ) as mock_rescan,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await loop._reconcile_once()

        mock_rescan.assert_awaited_once()

    async def test_rescan_hardware_upserts_devices_with_matcher(self) -> None:
        """_rescan_hardware upserts detected devices with profile matching."""
        from silvasonic.controller.device_scanner import DeviceInfo
        from silvasonic.controller.profile_matcher import MatchResult

        mgr = MagicMock()
        scanner = MagicMock()
        matcher = MagicMock()

        device_info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id="16d0",
            usb_product_id="0b40",
            usb_serial="ABC",
        )
        scanner.scan_all.return_value = [device_info]

        match_result = MatchResult(
            profile_slug="ultramic_384",
            score=100,
            auto_enroll=True,
        )
        matcher.match = AsyncMock(return_value=match_result)

        loop = ReconciliationLoop(
            mgr,
            device_scanner=scanner,
            profile_matcher=matcher,
            interval=1.0,
        )

        mock_session = AsyncMock()
        # Mock online devices query for offline-marking
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.upsert_device",
                new_callable=AsyncMock,
                return_value=MagicMock(config={}),
            ) as mock_upsert,
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()
            await loop._rescan_hardware()

        mock_upsert.assert_awaited_once()
        # Should have been called with profile_slug from matcher
        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["profile_slug"] == "ultramic_384"
        assert call_kwargs.kwargs["enrollment_status"] == "enrolled"

    async def test_rescan_hardware_sets_workspace_name(self) -> None:
        """_rescan_hardware persists workspace_name on enrolled devices.

        Regression test for Bug #1: The Controller must compute and store
        ``devices.workspace_name`` during enrollment. The Processor Indexer
        uses this column to resolve filesystem paths to the device's identity.

        If this test fails, the cross-service contract is broken and the
        Indexer will silently skip all recordings (``device_not_registered``).

        See: Log Analysis Report 2026-03-30 — Bug #1 (Name-Mismatch).
        """
        from silvasonic.controller.device_scanner import DeviceInfo
        from silvasonic.controller.profile_matcher import MatchResult

        mgr = MagicMock()
        scanner = MagicMock()
        matcher = MagicMock()

        device_info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K EVO",
            alsa_device="hw:2,0",
            usb_vendor_id="0869",
            usb_product_id="0389",
            usb_serial="00000000034F",
        )
        scanner.scan_all.return_value = [device_info]

        match_result = MatchResult(
            profile_slug="ultramic_384_evo",
            score=100,
            auto_enroll=True,
        )
        matcher.match = AsyncMock(return_value=match_result)

        loop = ReconciliationLoop(
            mgr,
            device_scanner=scanner,
            profile_matcher=matcher,
            interval=1.0,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Mock device returned by upsert — starts without workspace_name
        mock_device = MagicMock()
        mock_device.name = "0869-0389-00000000034F"
        mock_device.config = {
            "usb_serial": "00000000034F",
            "usb_vendor_id": "0869",
            "usb_product_id": "0389",
        }
        mock_device.workspace_name = None
        mock_device.profile_slug = "ultramic_384_evo"

        with (
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.upsert_device",
                new_callable=AsyncMock,
                return_value=mock_device,
            ),
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()
            await loop._rescan_hardware()

        # Critical assertion: workspace_name must be set
        assert mock_device.workspace_name == "ultramic-384-evo-034f", (
            f"Contract violation: Reconciler did not set workspace_name. "
            f"Device '{mock_device.name}' has workspace_name="
            f"{mock_device.workspace_name!r} instead of 'ultramic-384-evo-034f'."
        )

    async def test_rescan_hardware_respects_manual_enrollment_workspace_name(self) -> None:
        """_rescan_hardware persists workspace_name on manually enrolled devices.

        Regression test: When auto_enroll is False, but the device object loaded
        from DB already contains a profile_slug, generate_workspace_name must still
        run to ensure cross-service processor contract is fulfilled.
        """
        from silvasonic.controller.device_scanner import DeviceInfo
        from silvasonic.controller.profile_matcher import MatchResult

        mgr = MagicMock()
        scanner = MagicMock()
        matcher = MagicMock()

        device_info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K EVO",
            alsa_device="hw:2,0",
            usb_vendor_id="0869",
            usb_product_id="0389",
            usb_serial="00000000034F",
        )
        scanner.scan_all.return_value = [device_info]

        # auto_enroll is FALSE here (manual UI assignment scenario)
        match_result = MatchResult(
            profile_slug=None,
            score=0,
            auto_enroll=False,
        )
        matcher.match = AsyncMock(return_value=match_result)

        loop = ReconciliationLoop(
            mgr,
            device_scanner=scanner,
            profile_matcher=matcher,
            interval=1.0,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Mock device returned by upsert — starts without workspace_name, but HAS a profile_slug!
        mock_device = MagicMock()
        mock_device.name = "0869-0389-00000000034F"
        mock_device.config = {
            "usb_serial": "00000000034F",
            "usb_vendor_id": "0869",
            "usb_product_id": "0389",
        }
        mock_device.workspace_name = None
        mock_device.profile_slug = "ultramic_384_evo"  # Simulates persistent manual assignment

        with (
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.upsert_device",
                new_callable=AsyncMock,
                return_value=mock_device,
            ),
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()
            await loop._rescan_hardware()

        # Critical assertion: workspace_name must be set, because mock_device.profile_slug is truthy
        assert mock_device.workspace_name == "ultramic-384-evo-034f", (
            f"Contract violation: Reconciler did not set workspace_name for manually "
            f"enrolled device. Device '{mock_device.name}' has workspace_name="
            f"{mock_device.workspace_name!r} instead of 'ultramic-384-evo-034f'."
        )

    async def test_rescan_hardware_without_matcher(self) -> None:
        """_rescan_hardware upserts devices with pending status when no matcher."""
        from silvasonic.controller.device_scanner import DeviceInfo

        mgr = MagicMock()
        scanner = MagicMock()

        device_info = DeviceInfo(
            alsa_card_index=0,
            alsa_name="Generic USB",
            alsa_device="hw:0,0",
        )
        scanner.scan_all.return_value = [device_info]

        loop = ReconciliationLoop(
            mgr,
            device_scanner=scanner,
            profile_matcher=None,
            interval=1.0,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Provide a mock device to avoid AsyncMock fallbacks for device.profile_slug
        mock_device = MagicMock()
        mock_device.profile_slug = None

        with (
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.upsert_device",
                new_callable=AsyncMock,
                return_value=mock_device,
            ) as mock_upsert,
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()
            await loop._rescan_hardware()

        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["profile_slug"] is None
        assert call_kwargs.kwargs["enrollment_status"] == "pending"

    async def test_rescan_hardware_ignores_missing_within_grace_period(self) -> None:
        """_rescan_hardware does not mark devices offline if within grace period."""
        mgr = MagicMock()
        scanner = MagicMock()
        scanner.scan_all.return_value = []  # No devices found

        loop = ReconciliationLoop(
            mgr,
            device_scanner=scanner,
            profile_matcher=None,
            interval=1.0,
            grace_period_s=3.0,
        )

        mock_device = MagicMock()
        mock_device.name = "old-device-001"
        mock_device.status = "online"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_device]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch("time.monotonic", return_value=100.0),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()

            # Initial scan, device missing -> records time but keeps online
            await loop._rescan_hardware()
            assert mock_device.status == "online"
            assert "old-device-001" in loop._missing_devices
            assert loop._missing_devices["old-device-001"] == 100.0

            # Second scan 2 seconds later -> still online
            with patch("time.monotonic", return_value=102.0):
                await loop._rescan_hardware()
            assert mock_device.status == "online"

    async def test_rescan_hardware_marks_offline_after_grace_period(self) -> None:
        """_rescan_hardware marks devices offline after grace period expires."""
        mgr = MagicMock()
        scanner = MagicMock()
        scanner.scan_all.return_value = []

        loop = ReconciliationLoop(
            mgr,
            device_scanner=scanner,
            profile_matcher=None,
            interval=1.0,
            grace_period_s=3.0,
        )
        # Device already missing since t=100.0
        loop._missing_devices["old-device-001"] = 100.0

        mock_device = MagicMock()
        mock_device.name = "old-device-001"
        mock_device.status = "online"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_device]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch("time.monotonic", return_value=103.1),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()

            await loop._rescan_hardware()

        assert mock_device.status == "offline"
        mock_session.commit.assert_awaited_once()
        assert "old-device-001" not in loop._missing_devices

    async def test_rescan_hardware_clears_tracker_if_reconnected(self) -> None:
        """_rescan_hardware removes device from missing tracker if it reconnects during grace."""
        mgr = MagicMock()
        scanner = MagicMock()

        loop = ReconciliationLoop(mgr, device_scanner=scanner, interval=1.0)
        loop._missing_devices["old-device-001"] = 100.0

        mock_device = MagicMock()
        mock_device.stable_device_id = "old-device-001"

        scanner.scan_all.return_value = [mock_device]
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_upserted_device = MagicMock()
        mock_upserted_device.profile_slug = None

        with (
            patch("silvasonic.controller.reconciler.get_session") as mock_get_session,
            patch(
                "silvasonic.controller.reconciler.upsert_device",
                new_callable=AsyncMock,
                return_value=mock_upserted_device,
            ),
            patch(
                "silvasonic.controller.reconciler.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()

            await loop._rescan_hardware()

        assert "old-device-001" not in loop._missing_devices

    async def test_rescan_hardware_no_scanner(self) -> None:
        """_rescan_hardware is a no-op when scanner is None."""
        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, device_scanner=None, interval=1.0)

        # Should return immediately without errors
        await loop._rescan_hardware()


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


# ===================================================================
# ReconciliationLoop + ControllerStats Integration
# ===================================================================


@pytest.mark.unit
class TestReconciliationLoopStats:
    """Tests for stats tracking in ReconciliationLoop."""

    def test_set_stats_wires_instance(self) -> None:
        """set_stats() stores the ControllerStats reference."""
        from silvasonic.controller.controller_stats import ControllerStats

        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=1.0)

        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=300.0)
        loop.set_stats(stats)

        assert loop._stats is stats

    async def test_reconcile_cycle_records_stats(self) -> None:
        """Successful reconciliation cycle records in stats."""
        import asyncio

        from silvasonic.controller.controller_stats import ControllerStats

        mgr = MagicMock()
        mgr.list_managed.return_value = []
        mgr.sync_state = MagicMock()

        loop = ReconciliationLoop(mgr, interval=0.01)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        loop.set_stats(stats)

        call_count = 0

        async def mock_reconcile() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError

        with (
            patch.object(loop, "_reconcile_once", side_effect=mock_reconcile),
            pytest.raises(asyncio.CancelledError),
        ):
            await loop.run()

        # 2 successful cycles before cancel on 3rd
        assert stats._total_reconcile_cycles == 2

    async def test_reconcile_error_records_stats(self) -> None:
        """Failed reconciliation cycle records error in stats."""
        import asyncio

        from silvasonic.controller.controller_stats import ControllerStats

        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=0.01)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        loop.set_stats(stats)

        call_count = 0

        async def failing_reconcile() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            raise RuntimeError("DB down")

        with (
            patch.object(loop, "_reconcile_once", side_effect=failing_reconcile),
            pytest.raises(asyncio.CancelledError),
        ):
            await loop.run()

        assert stats._total_reconcile_errors == 1

    async def test_reconcile_once_tracks_container_start(self) -> None:
        """_reconcile_once records container starts when desired > actual."""
        from unittest.mock import patch as _patch

        from silvasonic.controller.controller_stats import ControllerStats

        mgr = MagicMock()
        mgr.list_managed.return_value = []  # No containers running
        mgr.sync_state = MagicMock()

        spec = _make_spec(name="silvasonic-recorder-new-mic")
        reconciler = ReconciliationLoop(mgr, interval=1.0)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        reconciler.set_stats(stats)

        with (
            patch.object(
                reconciler._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[spec],  # One desired container
            ),
            _patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
            _patch(
                "silvasonic.controller.controller_stats.log",
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await reconciler._reconcile_once()

        assert stats._total_containers_started == 1

    async def test_reconcile_once_tracks_container_stop(self) -> None:
        """_reconcile_once records container stops when actual > desired."""
        from unittest.mock import patch as _patch

        from silvasonic.controller.controller_stats import ControllerStats

        mgr = MagicMock()
        mgr.list_managed.return_value = [
            {"name": "silvasonic-recorder-orphaned", "status": "running"}
        ]
        mgr.sync_state = MagicMock()

        reconciler = ReconciliationLoop(mgr, interval=1.0)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        reconciler.set_stats(stats)

        with (
            patch.object(
                reconciler._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[],  # No desired containers
            ),
            _patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
            _patch(
                "silvasonic.controller.controller_stats.log",
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await reconciler._reconcile_once()

        assert stats._total_containers_stopped == 1

    async def test_reconcile_once_tracks_config_drift(self) -> None:
        """_reconcile_once tracks container restarts due to config drift."""
        from unittest.mock import patch as _patch

        from silvasonic.controller.controller_stats import ControllerStats

        mgr = MagicMock()
        # Actual running container has an OLD config hash label
        mgr.list_managed.return_value = [
            {
                "name": "silvasonic-recorder-drift",
                "status": "running",
                "labels": {"io.silvasonic.config_hash": "old_hash_123"},
            }
        ]
        mgr.sync_state = MagicMock()

        # Desired spec has a NEW config hash (simulating config drift)
        spec = _make_spec(
            name="silvasonic-recorder-drift",
            labels={"io.silvasonic.config_hash": "new_hash_456"},
        )

        reconciler = ReconciliationLoop(mgr, interval=1.0)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        reconciler.set_stats(stats)

        from unittest.mock import PropertyMock

        with (
            _patch(
                "silvasonic.controller.container_spec.Tier2ServiceSpec.config_hash",
                new_callable=PropertyMock,
                return_value="new_hash_456",
            ),
            patch.object(
                reconciler._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[spec],
            ),
            _patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
            _patch(
                "silvasonic.controller.controller_stats.log",
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await reconciler._reconcile_once()

        # Both a stop and a start should be tracked due to the drift restart
        assert stats._total_containers_stopped == 1
        assert stats._total_containers_started == 1


# ===================================================================
# NudgeSubscriber + ControllerStats Integration
# ===================================================================


@pytest.mark.unit
class TestNudgeSubscriberStats:
    """Tests for stats tracking in NudgeSubscriber."""

    def test_set_stats_wires_instance(self) -> None:
        """set_stats() stores the ControllerStats reference."""
        from silvasonic.controller.controller_stats import ControllerStats

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=300.0)
        sub.set_stats(stats)

        assert sub._stats is stats

    def test_reconcile_nudge_records_stats(self) -> None:
        """Reconcile nudge increments nudge counter in stats."""
        from silvasonic.controller.controller_stats import ControllerStats

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=300.0)
        sub.set_stats(stats)

        sub._handle_message({"type": "message", "data": b"reconcile"})
        sub._handle_message({"type": "message", "data": b"reconcile"})

        assert stats._total_nudges == 2

    def test_non_reconcile_nudge_no_stats(self) -> None:
        """Non-reconcile messages do not increment nudge counter."""
        from silvasonic.controller.controller_stats import ControllerStats

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=300.0)
        sub.set_stats(stats)

        sub._handle_message({"type": "message", "data": b"restart"})

        assert stats._total_nudges == 0
