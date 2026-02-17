"""Unit tests for silvasonic-recorder service — 100 % coverage."""

import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecorderPackage:
    """Basic package-level tests."""

    def test_package_importable(self) -> None:
        """Recorder package is importable."""
        import silvasonic.recorder

        assert silvasonic.recorder is not None


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
                "silvasonic.recorder.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "silvasonic.recorder.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.recorder.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.recorder.__main__ import monitor_database

            with pytest.raises(asyncio.CancelledError):
                await monitor_database()

        mock_monitor.update_status.assert_called_once_with("database", True, "Connected")

    async def test_monitor_database_failed(self) -> None:
        """Updates HealthMonitor with 'Connection failed' when DB is down."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.recorder.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "silvasonic.recorder.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.recorder.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.recorder.__main__ import monitor_database

            with pytest.raises(asyncio.CancelledError):
                await monitor_database()

        mock_monitor.update_status.assert_called_once_with("database", False, "Connection failed")


# ---------------------------------------------------------------------------
# monitor_recording
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorRecording:
    """Tests for the monitor_recording coroutine."""

    async def test_recording_active(self) -> None:
        """Reports healthy when SIMULATE_RECORDING_HEALTH is True."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.recorder.__main__.SIMULATE_RECORDING_HEALTH",
                True,
            ),
            patch(
                "silvasonic.recorder.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.recorder.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.recorder.__main__ import monitor_recording

            with pytest.raises(asyncio.CancelledError):
                await monitor_recording()

        mock_monitor.update_status.assert_called_once_with("recording", True, "Recording active")

    async def test_recording_failed(self) -> None:
        """Reports unhealthy when SIMULATE_RECORDING_HEALTH is False."""
        mock_monitor = MagicMock()
        with (
            patch(
                "silvasonic.recorder.__main__.SIMULATE_RECORDING_HEALTH",
                False,
            ),
            patch(
                "silvasonic.recorder.__main__.HealthMonitor",
                return_value=mock_monitor,
            ),
            patch(
                "silvasonic.recorder.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            from silvasonic.recorder.__main__ import monitor_recording

            with pytest.raises(asyncio.CancelledError):
                await monitor_recording()

        mock_monitor.update_status.assert_called_once_with("recording", False, "Recording failed")


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
                "silvasonic.recorder.__main__.configure_logging",
                mock_configure,
            ),
            patch(
                "silvasonic.recorder.__main__.start_health_server",
                mock_health,
            ),
            patch(
                "silvasonic.recorder.__main__.monitor_database",
                side_effect=noop,
            ),
            patch(
                "silvasonic.recorder.__main__.monitor_recording",
                side_effect=noop,
            ),
        ):
            from silvasonic.recorder.__main__ import main

            # Schedule main and send ourselves SIGTERM after a tiny delay
            task = asyncio.create_task(main())
            await asyncio.sleep(0.01)

            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.01)

            # main() should have exited cleanly after the signal
            await asyncio.wait_for(task, timeout=2.0)

        mock_configure.assert_called_once_with("recorder")
        mock_health.assert_called_once()

    def test_main_guard(self) -> None:
        """The if __name__ == '__main__' guard calls asyncio.run(main())."""
        import runpy

        with patch("asyncio.run", MagicMock()) as mock_run:
            runpy.run_module("silvasonic.recorder.__main__", run_name="__main__")
            mock_run.assert_called_once()
