"""Unit tests for silvasonic-controller service — 100 % coverage."""

import asyncio
import importlib
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    """Tests for module-level configuration variables."""

    def test_health_port_default(self) -> None:
        """CONTROLLER_HEALTH_PORT defaults to 9100."""
        os.environ.pop("SILVASONIC_CONTROLLER_PORT", None)
        mod = importlib.import_module("silvasonic.controller.__main__")
        importlib.reload(mod)
        assert mod.CONTROLLER_HEALTH_PORT == 9100

    def test_health_port_env_override(self) -> None:
        """CONTROLLER_HEALTH_PORT respects the environment variable."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_PORT": "7777"}):
            mod = importlib.import_module("silvasonic.controller.__main__")
            importlib.reload(mod)
            assert mod.CONTROLLER_HEALTH_PORT == 7777


# ---------------------------------------------------------------------------
# monitor_database
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorDatabase:
    """Tests for the monitor_database coroutine."""

    async def test_monitor_database_connected(self) -> None:
        """Updates HealthMonitor with 'Connected' when DB is reachable."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "silvasonic.controller.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.controller.__main__ import monitor_database

            with pytest.raises(asyncio.CancelledError):
                await monitor_database()

        mock_monitor.update_status.assert_called_once_with("database", True, "Connected")

    async def test_monitor_database_failed(self) -> None:
        """Updates HealthMonitor with 'Connection failed' when DB is down."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "silvasonic.controller.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.controller.__main__ import monitor_database

            with pytest.raises(asyncio.CancelledError):
                await monitor_database()

        mock_monitor.update_status.assert_called_once_with("database", False, "Connection failed")


# ---------------------------------------------------------------------------
# monitor_recorder_spawn
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorRecorderSpawn:
    """Tests for the monitor_recorder_spawn coroutine."""

    async def test_recorder_spawned(self) -> None:
        """Reports healthy when SIMULATE_RECORDER_SPAWN is True."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.controller.__main__.SIMULATE_RECORDER_SPAWN",
                True,
            ),
            patch(
                "silvasonic.controller.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.controller.__main__ import monitor_recorder_spawn

            with pytest.raises(asyncio.CancelledError):
                await monitor_recorder_spawn()

        mock_monitor.update_status.assert_called_once_with(
            "recorder_spawn", True, "Recorder spawned"
        )

    async def test_recorder_not_spawned(self) -> None:
        """Reports unhealthy when SIMULATE_RECORDER_SPAWN is False."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.controller.__main__.SIMULATE_RECORDER_SPAWN",
                False,
            ),
            patch(
                "silvasonic.controller.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.controller.__main__ import monitor_recorder_spawn

            with pytest.raises(asyncio.CancelledError):
                await monitor_recorder_spawn()

        mock_monitor.update_status.assert_called_once_with(
            "recorder_spawn", False, "No recorder spawned"
        )


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMain:
    """Tests for the main() coroutine."""

    async def test_main_starts_services_and_handles_signal(self) -> None:
        """main() wires up logging, health, tasks, signals, and exits on SIGTERM."""
        mock_configure = MagicMock()
        mock_health = MagicMock()

        # Mock the monitor coroutines so they don't actually run
        async def noop() -> None:
            await asyncio.Event().wait()  # block forever

        with (
            patch(
                "silvasonic.controller.__main__.configure_logging",
                mock_configure,
            ),
            patch(
                "silvasonic.controller.__main__.start_health_server",
                mock_health,
            ),
            patch(
                "silvasonic.controller.__main__.monitor_database",
                side_effect=noop,
            ),
            patch(
                "silvasonic.controller.__main__.monitor_recorder_spawn",
                side_effect=noop,
            ),
        ):
            from silvasonic.controller.__main__ import main

            # Schedule main and send ourselves SIGTERM after a tiny delay
            task = asyncio.create_task(main())
            await asyncio.sleep(0.01)

            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.01)

            # main() should have exited cleanly after the signal
            await asyncio.wait_for(task, timeout=2.0)

        mock_configure.assert_called_once_with("controller")
        mock_health.assert_called_once()

    def test_main_guard(self) -> None:
        """The if __name__ == '__main__' guard calls asyncio.run(main())."""
        import runpy

        with patch("asyncio.run", MagicMock()) as mock_run:
            runpy.run_module("silvasonic.controller.__main__", run_name="__main__")
            mock_run.assert_called_once()
