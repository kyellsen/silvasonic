"""Unit tests for silvasonic-recorder service.

Tests the RecorderService (SilvaService subclass) including:
- Package import
- Service configuration and settings
- RecorderSettings injected config parsing
- Background health monitor (_monitor_recording)
- run() lifecycle with shutdown event
- __main__ guard
"""

import asyncio
import json
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
    from silvasonic.recorder.ffmpeg_pipeline import FFmpegConfig

    svc = RecorderService.__new__(RecorderService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
    svc._cfg = MagicMock()
    svc._cfg.RECORDER_DEVICE = "hw:mock,0"
    svc._cfg.RECORDER_MOCK_SOURCE = False
    svc._cfg.workspace_path = MagicMock()
    svc._cfg.FFMPEG_BINARY = "ffmpeg"
    svc._cfg.FFMPEG_LOGLEVEL = "warning"
    svc._cfg.RECORDER_WATCHDOG_MAX_RESTARTS = 5
    svc._cfg.RECORDER_WATCHDOG_CHECK_INTERVAL_S = 5.0
    svc._cfg.RECORDER_WATCHDOG_STALL_TIMEOUT_S = 60.0
    svc._cfg.RECORDER_HEALTH_POLL_INTERVAL_S = 5.0
    svc._pipeline_config = FFmpegConfig()
    svc._pipeline = None
    svc._watchdog = None
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
                instance_id="recorder",
                redis_url="redis://custom:1234/5",
                heartbeat_interval=10.0,
            )

    def test_init_with_injected_config_json(self) -> None:
        """__init__ uses from_injected_config when valid config JSON is present."""
        config = {"audio": {"sample_rate": 96000, "channels": 1, "format": "S16LE"}}
        with (
            patch.dict(os.environ, {"SILVASONIC_RECORDER_CONFIG_JSON": json.dumps(config)}),
            patch("silvasonic.core.service.SilvaService.__init__"),
        ):
            from silvasonic.recorder.__main__ import RecorderService

            svc = RecorderService()
            assert svc._pipeline_config.sample_rate == 96000
            assert svc._pipeline_config.raw_enabled is True
            assert svc._pipeline_config.processed_enabled is True


# ---------------------------------------------------------------------------
# RecorderSettings
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecorderSettings:
    """Tests for RecorderSettings — environment parsing and profile loading."""

    def test_defaults(self) -> None:
        """Default settings have expected values."""
        from silvasonic.recorder.settings import RecorderSettings

        settings = RecorderSettings()
        assert settings.INSTANCE_ID == "recorder"
        assert settings.RECORDER_DEVICE == "hw:1,0"
        assert settings.RECORDER_CONFIG_JSON is None
        assert settings.FFMPEG_BINARY == "ffmpeg"
        assert settings.FFMPEG_LOGLEVEL == "warning"

    def test_env_override(self) -> None:
        """Environment variables override defaults."""
        with patch.dict(
            os.environ,
            {
                "SILVASONIC_INSTANCE_ID": "mic-1",
                "SILVASONIC_RECORDER_DEVICE": "hw:3,0",
                "SILVASONIC_RECORDER_WORKSPACE": "/custom/workspace",
            },
        ):
            from silvasonic.recorder.settings import RecorderSettings

            settings = RecorderSettings()
            assert settings.INSTANCE_ID == "mic-1"
            assert settings.RECORDER_DEVICE == "hw:3,0"
            assert settings.workspace_path.as_posix() == "/custom/workspace"

    def test_parse_injected_config_none(self) -> None:
        """parse_injected_config() returns None when no config JSON is set."""
        from silvasonic.recorder.settings import RecorderSettings

        settings = RecorderSettings()
        assert settings.parse_injected_config() is None

    def test_health_poll_interval_default(self) -> None:
        """recorder_health_poll_interval_s defaults to 5.0."""
        from silvasonic.recorder.settings import RecorderSettings

        settings = RecorderSettings()
        assert settings.RECORDER_HEALTH_POLL_INTERVAL_S == 5.0

    def test_health_poll_interval_env_override(self) -> None:
        """recorder_health_poll_interval_s respects env override."""
        with patch.dict(
            os.environ,
            {"SILVASONIC_RECORDER_HEALTH_POLL_INTERVAL_S": "10.0"},
        ):
            from silvasonic.recorder.settings import RecorderSettings

            settings = RecorderSettings()
            assert settings.RECORDER_HEALTH_POLL_INTERVAL_S == 10.0

    def test_parse_injected_config_valid(self) -> None:
        """parse_injected_config() returns InjectedRecorderConfig for valid JSON."""
        config = {
            "audio": {
                "sample_rate": 384000,
                "channels": 1,
                "format": "S16LE",
            },
        }
        with patch.dict(
            os.environ,
            {"SILVASONIC_RECORDER_CONFIG_JSON": json.dumps(config)},
        ):
            from silvasonic.recorder.settings import RecorderSettings

            settings = RecorderSettings()
            parsed = settings.parse_injected_config()
            assert parsed is not None
            assert parsed.audio.sample_rate == 384000

    def test_parse_injected_config_invalid_json(self) -> None:
        """parse_injected_config() returns None for invalid JSON."""
        with patch.dict(
            os.environ,
            {"SILVASONIC_RECORDER_CONFIG_JSON": "not json{{{"},
        ):
            from silvasonic.recorder.settings import RecorderSettings

            settings = RecorderSettings()
            assert settings.parse_injected_config() is None

    def test_parse_injected_config_missing_audio(self) -> None:
        """parse_injected_config() returns None when 'audio' section is missing."""
        with patch.dict(
            os.environ,
            {"SILVASONIC_RECORDER_CONFIG_JSON": json.dumps({"processing": {}})},
        ):
            from silvasonic.recorder.settings import RecorderSettings

            settings = RecorderSettings()
            assert settings.parse_injected_config() is None


# ---------------------------------------------------------------------------
# _monitor_recording
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorRecording:
    """Tests for the _monitor_recording coroutine."""

    async def test_recording_active(self, bare_service: "RecorderService") -> None:
        """Reports healthy when pipeline is active."""
        mock_pipeline = MagicMock()
        mock_pipeline.is_active = True
        mock_pipeline.segments_promoted = 5
        mock_pipeline.stderr_errors = []
        bare_service._pipeline = mock_pipeline

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
        assert "Recording active" in status["components"]["recording"]["details"]

    async def test_recording_not_initialized(self, bare_service: "RecorderService") -> None:
        """Reports unhealthy when pipeline is None."""
        bare_service._pipeline = None

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
        assert "Pipeline not initialized" in status["components"]["recording"]["details"]

    async def test_recording_ffmpeg_exited(self, bare_service: "RecorderService") -> None:
        """Reports unhealthy when FFmpeg process exited unexpectedly."""
        mock_pipeline = MagicMock()
        mock_pipeline.is_active = False
        mock_pipeline.segments_promoted = 10
        mock_pipeline.stderr_errors = ["[alsa] overrun"]
        bare_service._pipeline = mock_pipeline

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
        assert "exited" in status["components"]["recording"]["details"]


# ---------------------------------------------------------------------------
# RecorderService.run()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecorderServiceRun:
    """Tests for the run() coroutine."""

    async def test_run_starts_pipeline_and_exits_on_shutdown(
        self, bare_service: "RecorderService", tmp_path: MagicMock
    ) -> None:
        """run() starts pipeline and exits when shutdown_event is set."""
        bare_service._shutdown_event = asyncio.Event()
        bare_service._cfg.workspace_path = tmp_path  # type: ignore[misc]

        mock_pipeline = MagicMock()
        mock_pipeline.is_active = True
        mock_pipeline.segments_promoted = 0
        mock_pipeline.stderr_errors = []

        mock_watchdog = MagicMock()
        mock_watchdog.watch = AsyncMock()

        with (
            patch("silvasonic.recorder.__main__.FFmpegPipeline", return_value=mock_pipeline),
            patch("silvasonic.recorder.__main__.RecordingWatchdog", return_value=mock_watchdog),
            patch("silvasonic.recorder.__main__.ensure_workspace"),
        ):
            # Configure watchdog.watch to set shutdown after a short delay
            async def fake_watch(event: asyncio.Event) -> None:
                await asyncio.sleep(0.1)
                event.set()

            mock_watchdog.watch.side_effect = fake_watch

            await bare_service.run()

        mock_pipeline.start.assert_called_once()
        mock_pipeline.stop.assert_called_once()

    async def test_run_crashes_on_pipeline_start_failure(
        self, bare_service: "RecorderService", tmp_path: MagicMock
    ) -> None:
        """run() crashes when pipeline fails to start (Level-2 Recovery)."""
        bare_service._shutdown_event = asyncio.Event()
        bare_service._cfg.workspace_path = tmp_path  # type: ignore[misc]

        mock_pipeline = MagicMock()
        mock_pipeline.start.side_effect = RuntimeError("No audio device")

        with (
            patch("silvasonic.recorder.__main__.FFmpegPipeline", return_value=mock_pipeline),
            patch("silvasonic.recorder.__main__.ensure_workspace"),
            pytest.raises(RuntimeError, match="Initial pipeline start failed"),
        ):
            await bare_service.run()

    async def test_run_handles_cancellation(
        self, bare_service: "RecorderService", tmp_path: MagicMock
    ) -> None:
        """run() catches CancelledError and stops the pipeline cleanly."""
        bare_service._shutdown_event = asyncio.Event()
        bare_service._cfg.workspace_path = tmp_path  # type: ignore[misc]

        mock_pipeline = MagicMock()
        mock_pipeline.is_active = True
        mock_pipeline.segments_promoted = 0
        mock_pipeline.stderr_errors = []

        mock_watchdog = MagicMock()
        mock_watchdog.watch = AsyncMock()

        with (
            patch("silvasonic.recorder.__main__.FFmpegPipeline", return_value=mock_pipeline),
            patch("silvasonic.recorder.__main__.RecordingWatchdog", return_value=mock_watchdog),
            patch("silvasonic.recorder.__main__.ensure_workspace"),
        ):

            async def fake_watch(event: asyncio.Event) -> None:
                await asyncio.sleep(0.1)
                event.set()

            mock_watchdog.watch.side_effect = fake_watch

            await bare_service.run()

        # Pipeline should have been stopped
        mock_pipeline.stop.assert_called_once()


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetExtraMeta:
    """Tests for heartbeat metadata."""

    def test_extra_meta_no_pipeline(self, bare_service: "RecorderService") -> None:
        """Returns recording metadata even without active pipeline."""
        meta = bare_service.get_extra_meta()
        assert "recording" in meta
        assert meta["recording"]["active"] is False
        assert meta["recording"]["segments_promoted"] == 0
        assert meta["recording"]["ffmpeg_pid"] is None
        assert meta["recording"]["raw_enabled"] is True
        assert meta["recording"]["processed_enabled"] is True
        # Watchdog fields present even without watchdog
        assert meta["recording"]["watchdog_restarts"] == 0
        assert meta["recording"]["watchdog_max_restarts"] == 5
        assert meta["recording"]["watchdog_giving_up"] is False
        assert meta["recording"]["watchdog_last_failure"] is None

    def test_extra_meta_with_pipeline(self, bare_service: "RecorderService") -> None:
        """Returns recording metadata from active pipeline."""
        mock_pipeline = MagicMock()
        mock_pipeline.is_active = True
        mock_pipeline.segments_promoted = 42
        mock_pipeline.ffmpeg_pid = 1234
        bare_service._pipeline = mock_pipeline

        meta = bare_service.get_extra_meta()
        assert meta["recording"]["active"] is True
        assert meta["recording"]["segments_promoted"] == 42
        assert meta["recording"]["ffmpeg_pid"] == 1234
        assert meta["recording"]["raw_enabled"] is True
        assert meta["recording"]["processed_enabled"] is True

    def test_extra_meta_includes_watchdog(self, bare_service: "RecorderService") -> None:
        """Heartbeat metadata includes watchdog fields when watchdog is set."""
        mock_watchdog = MagicMock()
        mock_watchdog.restart_count = 2
        mock_watchdog.max_restarts = 5
        mock_watchdog.is_giving_up = False
        mock_watchdog.last_failure_reason = "FFmpeg process exited (returncode=-9)"
        bare_service._watchdog = mock_watchdog

        meta = bare_service.get_extra_meta()
        assert meta["recording"]["watchdog_restarts"] == 2
        assert meta["recording"]["watchdog_max_restarts"] == 5
        assert meta["recording"]["watchdog_giving_up"] is False
        assert "returncode=-9" in meta["recording"]["watchdog_last_failure"]


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
