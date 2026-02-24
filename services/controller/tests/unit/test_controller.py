"""Unit tests for silvasonic-controller service — 100 % coverage.

Tests the ControllerService (SilvaService subclass) including:
- Package import
- Service configuration (port from env)
- Background health monitors (_monitor_database, _monitor_recorder_spawn)
- get_extra_meta() providing host_resources
- run() lifecycle with shutdown event
- __main__ guard
"""

import asyncio
import importlib
import os
import sys
import warnings
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.health import HealthMonitor

if TYPE_CHECKING:
    from silvasonic.controller.__main__ import ControllerService


def _make_bare_service() -> "ControllerService":
    """Create a bare ControllerService without triggering SilvaService.__init__.

    Sets up a mock _ctx with a real HealthMonitor so the `svc.health` property
    works without mypy complaints.
    """
    from silvasonic.controller.__main__ import ControllerService

    svc = ControllerService.__new__(ControllerService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerConfig:
    """Tests for service-level configuration."""

    def test_health_port_default(self) -> None:
        """service_port defaults to 9100."""
        os.environ.pop("SILVASONIC_CONTROLLER_PORT", None)
        mod = importlib.import_module("silvasonic.controller.__main__")
        importlib.reload(mod)
        assert mod.ControllerService.service_port == 9100

    def test_health_port_env_override(self) -> None:
        """service_port respects the SILVASONIC_CONTROLLER_PORT env var."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_PORT": "7777"}):
            mod = importlib.import_module("silvasonic.controller.__main__")
            importlib.reload(mod)
            assert mod.ControllerService.service_port == 7777

    def test_service_name(self) -> None:
        """service_name is 'controller'."""
        from silvasonic.controller.__main__ import ControllerService

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
# _monitor_recorder_spawn
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorRecorderSpawn:
    """Tests for the _monitor_recorder_spawn coroutine."""

    async def test_recorder_spawned(self) -> None:
        """Reports healthy when SIMULATE_RECORDER_SPAWN is True."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.SIMULATE_RECORDER_SPAWN",
                True,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_recorder_spawn()

        status = svc.health.get_status()
        assert status["components"]["recorder_spawn"]["healthy"] is True
        assert status["components"]["recorder_spawn"]["details"] == "Recorder spawned"

    async def test_recorder_not_spawned(self) -> None:
        """Reports unhealthy when SIMULATE_RECORDER_SPAWN is False."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.SIMULATE_RECORDER_SPAWN",
                False,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_recorder_spawn()

        status = svc.health.get_status()
        assert status["components"]["recorder_spawn"]["healthy"] is False
        assert status["components"]["recorder_spawn"]["details"] == "No recorder spawned"


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetExtraMeta:
    """Tests for the get_extra_meta() override."""

    def test_returns_host_resources(self) -> None:
        """get_extra_meta() includes host_resources from HostResourceCollector."""
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
        async def noop_db() -> None:
            await asyncio.Event().wait()

        async def noop_spawn() -> None:
            await asyncio.Event().wait()

        with (
            patch.object(svc, "_monitor_database", side_effect=noop_db),
            patch.object(svc, "_monitor_recorder_spawn", side_effect=noop_spawn),
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
