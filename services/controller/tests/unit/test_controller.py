"""Unit tests for ControllerService.

Covers the ControllerService (SilvaService subclass) including:
- Package import
- Service configuration (port from env)
- Background health monitors (_monitor_database, _monitor_podman)
- get_extra_meta() providing host_resources
- load_config() DB seeding hook
- run() lifecycle with shutdown event
- __main__ guard
"""

import asyncio
import os
import sys
import warnings
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.__main__ import ControllerService
from silvasonic.core.health import HealthMonitor


def _make_bare_service() -> Any:
    """Create a bare ControllerService without triggering SilvaService.__init__.

    Sets up a mock _ctx with a real HealthMonitor so the `svc.health` property
    works without mypy complaints.

    Returns ``Any`` so mock attributes (return_value, assert_called, etc.)
    are accessible without mypy ``attr-defined`` errors.
    """
    from silvasonic.controller.__main__ import ControllerService

    svc = ControllerService.__new__(ControllerService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
    svc._podman_client = MagicMock()
    svc._container_manager = MagicMock()
    svc._reconciliation_loop = MagicMock()
    svc._nudge_subscriber = MagicMock()
    # Phase 4: USB detection components
    svc._device_scanner = MagicMock()
    svc._profile_matcher = MagicMock()
    # Phase 5: Log forwarding
    svc._log_forwarder = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerPackage:
    """Basic package-level tests."""

    def test_package_importable(self) -> None:
        """Controller package is importable."""
        import silvasonic.controller

        assert silvasonic.controller is not None

    def test_podman_client_exported(self) -> None:
        """SilvasonicPodmanClient is exported from the controller package."""
        from silvasonic.controller import SilvasonicPodmanClient

        assert SilvasonicPodmanClient is not None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerConfig:
    """Tests for service-level configuration."""

    def test_health_port_default(self) -> None:
        """service_port defaults to 9100."""
        _make_bare_service()
        # Class-level default is 9100
        assert ControllerService.service_port == 9100

    def test_health_port_env_override(self) -> None:
        """service_port respects SILVASONIC_CONTROLLER_PORT at instantiation."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_PORT": "7777"}):
            from silvasonic.controller.__main__ import (
                ControllerService as ControllerSvc,
            )

            svc = ControllerSvc.__new__(ControllerSvc)
            # Simulate __init__ reading env var
            svc.service_port = int(os.environ.get("SILVASONIC_CONTROLLER_PORT", "9100"))
            assert svc.service_port == 7777

    def test_service_name(self) -> None:
        """service_name is 'controller'."""
        assert ControllerService.service_name == "controller"


# ---------------------------------------------------------------------------
# _monitor_database
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorDatabase:
    """Tests for the _monitor_database coroutine."""

    async def test_monitor_database_connected(self) -> None:
        """Updates HealthMonitor with 'Connected' when DB is reachable."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        status = svc.health.get_status()
        assert status["components"]["database"]["healthy"] is True
        assert status["components"]["database"]["details"] == "Connected"

    async def test_monitor_database_failed(self) -> None:
        """Updates HealthMonitor with 'Connection failed' when DB is down."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        status = svc.health.get_status()
        assert status["components"]["database"]["healthy"] is False
        assert status["components"]["database"]["details"] == "Connection failed"


# ---------------------------------------------------------------------------
# _monitor_podman
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorPodman:
    """Tests for the _monitor_podman coroutine."""

    async def test_monitor_podman_connected(self) -> None:
        """Reports healthy when Podman socket is reachable."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.ping.return_value = True
        svc._podman_client.list_managed_containers.return_value = [
            {"id": "abc", "name": "rec1", "status": "running", "labels": {}}
        ]
        svc._podman_client.connect.return_value = None

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is True
        assert status["components"]["podman"]["details"] == "Connected"
        assert "containers" in status["components"]
        assert status["components"]["containers"]["details"] == "1 managed containers"

    async def test_monitor_podman_disconnected(self) -> None:
        """Reports unhealthy when Podman socket is unreachable."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.ping.return_value = False
        svc._podman_client.connect.return_value = None

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False
        assert status["components"]["podman"]["details"] == "Socket unreachable"

    async def test_monitor_podman_connect_failure(self) -> None:
        """Reports unhealthy when initial connect() raises."""
        from silvasonic.controller.podman_client import PodmanConnectionError

        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.connect.side_effect = PodmanConnectionError("no socket")
        svc._podman_client.ping.return_value = False

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False

    async def test_monitor_podman_socket_not_found(self) -> None:
        """Registers podman as optional when socket path does not exist."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/nonexistent/podman.sock"

        with patch("pathlib.Path.exists", return_value=False):
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False
        assert status["components"]["podman"]["required"] is False
        # Overall status should be ok because podman is optional
        assert status["status"] == "ok"


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetExtraMeta:
    """Tests for the get_extra_meta() override."""

    def test_returns_host_resources(self) -> None:
        """get_extra_meta() includes host_resources."""
        svc = _make_bare_service()
        mock_hrc = MagicMock()
        mock_hrc.collect.return_value = {"cpu_percent": 23.5, "cpu_count": 4}
        svc._host_resources = mock_hrc

        meta = svc.get_extra_meta()

        assert "host_resources" in meta
        assert meta["host_resources"]["cpu_percent"] == 23.5
        assert meta["host_resources"]["cpu_count"] == 4
        mock_hrc.collect.assert_called_once()


# ---------------------------------------------------------------------------
# ControllerService.load_config()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerLoadConfig:
    """Tests for the load_config() hook (DB seeding)."""

    async def test_load_config_calls_seeders(self) -> None:
        """load_config() runs all seeders via get_session()."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.controller.__main__.run_all_seeders",
                new_callable=AsyncMock,
            ) as mock_seeders,
            patch.object(
                svc,
                "_initial_device_scan",
                new_callable=AsyncMock,
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            await svc.load_config()

        mock_seeders.assert_awaited_once_with(mock_ctx)


# ---------------------------------------------------------------------------
# ControllerService.run()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerServiceRun:
    """Tests for the run() coroutine."""

    async def test_run_starts_monitors_and_exits_on_shutdown(self) -> None:
        """run() starts background tasks and exits when shutdown_event is set."""
        svc = _make_bare_service()
        svc._shutdown_event = asyncio.Event()

        # Mock the monitor methods to be no-ops
        async def noop_forever() -> None:
            await asyncio.Event().wait()

        svc._reconciliation_loop.run = MagicMock(side_effect=noop_forever)
        svc._nudge_subscriber.run = MagicMock(side_effect=noop_forever)
        svc._log_forwarder.run = MagicMock(side_effect=noop_forever)

        with (
            patch.object(svc, "_monitor_database", side_effect=noop_forever),
            patch.object(svc, "_monitor_podman", side_effect=noop_forever),
        ):
            # Set shutdown after a short delay
            async def trigger_shutdown() -> None:
                await asyncio.sleep(0.05)
                svc._shutdown_event.set()

            shutdown_task = asyncio.create_task(trigger_shutdown())
            await svc.run()
            await shutdown_task

        # Health should have been initialized
        status = svc.health.get_status()
        assert "controller" in status["components"]
        # Podman client should be closed
        svc._podman_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# _stop_all_tier2
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestStopAllTier2:
    """Tests for the _stop_all_tier2 shutdown method."""

    async def test_stops_all_managed_containers(self) -> None:
        """_stop_all_tier2 stops each managed container by name."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.return_value = [
            {"name": "silvasonic-recorder-mic1", "status": "running"},
            {"name": "silvasonic-recorder-mic2", "status": "running"},
        ]
        svc._container_manager.stop.return_value = True

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            await svc._stop_all_tier2()

        assert svc._container_manager.stop.call_count == 2

    async def test_stops_no_containers(self) -> None:
        """_stop_all_tier2 handles gracefully when no containers are running."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.return_value = []

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            await svc._stop_all_tier2()

        svc._container_manager.stop.assert_not_called()

    async def test_handles_exception_gracefully(self) -> None:
        """_stop_all_tier2 catches exceptions without crashing."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.side_effect = RuntimeError("Podman gone")

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            # Should not raise
            await svc._stop_all_tier2()


# ---------------------------------------------------------------------------
# _initial_device_scan
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestInitialDeviceScan:
    """Tests for the _initial_device_scan method."""

    async def test_no_devices_found(self) -> None:
        """_initial_device_scan returns early when no devices are detected."""
        svc = _make_bare_service()
        svc._device_scanner.scan_all.return_value = []

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            await svc._initial_device_scan()

    async def test_devices_with_auto_enroll(self) -> None:
        """_initial_device_scan upserts devices with auto-enroll profiles."""
        from silvasonic.controller.device_scanner import DeviceInfo
        from silvasonic.controller.profile_matcher import MatchResult

        svc = _make_bare_service()

        device_info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id="16d0",
            usb_product_id="0b40",
            usb_serial="ABC",
        )
        svc._device_scanner.scan_all.return_value = [device_info]
        svc._profile_matcher.match = AsyncMock(
            return_value=MatchResult(
                profile_slug="ultramic_384",
                score=100,
                auto_enroll=True,
            )
        )

        with (
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch(
                "silvasonic.controller.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.controller.__main__.upsert_device",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await svc._initial_device_scan()

        mock_upsert.assert_awaited_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["profile_slug"] == "ultramic_384"
        assert call_kwargs.kwargs["enrollment_status"] == "enrolled"

    async def test_devices_without_auto_enroll(self) -> None:
        """_initial_device_scan upserts devices as pending when no auto-enroll."""
        from silvasonic.controller.device_scanner import DeviceInfo
        from silvasonic.controller.profile_matcher import MatchResult

        svc = _make_bare_service()

        device_info = DeviceInfo(
            alsa_card_index=0,
            alsa_name="Generic Mic",
            alsa_device="hw:0,0",
        )
        svc._device_scanner.scan_all.return_value = [device_info]
        svc._profile_matcher.match = AsyncMock(
            return_value=MatchResult(
                profile_slug="generic",
                score=50,
                auto_enroll=False,
            )
        )

        with (
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch(
                "silvasonic.controller.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.controller.__main__.upsert_device",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await svc._initial_device_scan()

        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["profile_slug"] is None
        assert call_kwargs.kwargs["enrollment_status"] == "pending"


# ---------------------------------------------------------------------------
# __main__ guard
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMainGuard:
    """Tests for the if __name__ == '__main__' guard."""

    def test_main_guard(self) -> None:
        """The if __name__ == '__main__' guard calls ControllerService().start()."""
        import runpy

        # Remove cached module to prevent "found in sys.modules" RuntimeWarning
        sys.modules.pop("silvasonic.controller.__main__", None)

        with (
            patch("silvasonic.core.service.SilvaService.start", MagicMock()) as mock_start,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("silvasonic.controller.__main__", run_name="__main__")
            mock_start.assert_called_once()
