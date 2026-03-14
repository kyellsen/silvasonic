"""Unit tests for silvasonic-recorder service — 100 % coverage.

Tests the RecorderService (SilvaService subclass) including:
- Package import
- Service configuration
- Background health monitor (_monitor_recording)
- run() lifecycle with shutdown event
- __main__ guard
"""

import asyncio
import os
import sys
import warnings
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.health import HealthMonitor

if TYPE_CHECKING:
    from silvasonic.recorder.__main__ import RecorderService


@pytest.fixture
def bare_service() -> "RecorderService":
    """Create a bare RecorderService without triggering SilvaService.__init__.

    Sets up a mock _ctx with a real HealthMonitor so the `svc.health` property
    works without mypy complaints.
    """
    from silvasonic.recorder.__main__ import RecorderService

    svc = RecorderService.__new__(RecorderService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
    return svc


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

    def test_package_exports_version(self) -> None:
        """Package re-exports __version__ from core."""
        from silvasonic.recorder import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecorderConfig:
    """Tests for service-level configuration."""

    def test_service_name(self) -> None:
        """service_name is 'recorder'."""
        from silvasonic.recorder.__main__ import RecorderService

        assert RecorderService.service_name == "recorder"

    def test_service_port(self) -> None:
        """service_port is 9500."""
        from silvasonic.recorder.__main__ import RecorderService

        assert RecorderService.service_port == 9500

    def test_init_uses_env_redis_url(self) -> None:
        """__init__ reads SILVASONIC_REDIS_URL from environment."""
        with (
            patch.dict(os.environ, {"SILVASONIC_REDIS_URL": "redis://custom:1234/5"}),
            patch("silvasonic.core.service.SilvaService.__init__") as mock_super,
        ):
            from silvasonic.recorder.__main__ import RecorderService

            RecorderService()
            mock_super.assert_called_once_with(
                instance_id="recorder", redis_url="redis://custom:1234/5"
            )


# ---------------------------------------------------------------------------
# _monitor_recording
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorRecording:
    """Tests for the _monitor_recording coroutine."""

    async def test_recording_active(self, bare_service: "RecorderService") -> None:
        """Reports healthy when _recording_active is True."""
        bare_service._recording_active = True

        with (
            patch(
                "silvasonic.recorder.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await bare_service._monitor_recording()

        status = bare_service.health.get_status()
        assert status["components"]["recording"]["healthy"] is True
        assert status["components"]["recording"]["details"] == "Recording active"

    async def test_recording_failed(self, bare_service: "RecorderService") -> None:
        """Reports unhealthy when _recording_active is False."""
        bare_service._recording_active = False

        with (
            patch(
                "silvasonic.recorder.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await bare_service._monitor_recording()

        status = bare_service.health.get_status()
        assert status["components"]["recording"]["healthy"] is False
        assert status["components"]["recording"]["details"] == "Recording failed"


# ---------------------------------------------------------------------------
# RecorderService.run()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecorderServiceRun:
    """Tests for the run() coroutine."""

    async def test_run_starts_monitor_and_exits_on_shutdown(
        self, bare_service: "RecorderService"
    ) -> None:
        """run() starts background task and exits when shutdown_event is set."""
        bare_service._shutdown_event = asyncio.Event()

        # Mock the monitor method to be a no-op
        async def noop_rec() -> None:
            await asyncio.Event().wait()

        with patch.object(bare_service, "_monitor_recording", side_effect=noop_rec):
            # Set shutdown after a short delay
            async def trigger_shutdown() -> None:
                await asyncio.sleep(0.05)
                bare_service._shutdown_event.set()

            shutdown_task = asyncio.create_task(trigger_shutdown())
            await bare_service.run()
            await shutdown_task

        # Health should have been initialized
        status = bare_service.health.get_status()
        assert "recorder" in status["components"]

    async def test_run_handles_cancellation(self, bare_service: "RecorderService") -> None:
        """run() catches CancelledError in the recording loop and exits cleanly."""
        bare_service._shutdown_event = asyncio.Event()

        async def noop_rec() -> None:
            await asyncio.Event().wait()

        call_count = 0

        async def sleep_then_cancel(_delay: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            # First call: let the loop iterate once

        with (
            patch.object(bare_service, "_monitor_recording", side_effect=noop_rec),
            patch("silvasonic.recorder.__main__.asyncio.sleep", side_effect=sleep_then_cancel),
        ):
            await bare_service.run()

        # run() should have exited cleanly (CancelledError caught internally)
        status = bare_service.health.get_status()
        assert "recorder" in status["components"]


# ---------------------------------------------------------------------------
# __main__ guard
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMainGuard:
    """Tests for the if __name__ == '__main__' guard."""

    def test_main_guard(self) -> None:
        """The if __name__ == '__main__' guard calls RecorderService().start()."""
        import runpy

        # Remove cached module to prevent RuntimeWarning
        sys.modules.pop("silvasonic.recorder.__main__", None)

        with (
            patch("silvasonic.core.service.SilvaService.start", MagicMock()) as mock_start,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("silvasonic.recorder.__main__", run_name="__main__")
            mock_start.assert_called_once()
