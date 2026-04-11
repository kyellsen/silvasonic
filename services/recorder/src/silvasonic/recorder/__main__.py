"""Silvasonic Recorder — Audio capture service (ADR-0019, ADR-0024).

The Recorder is an **immutable Tier 2** service. It has NO database access
and receives all configuration via environment variables (Profile Injection)
from the Controller. Multiple recorder instances may run concurrently.

Inherits the full ``SilvaService`` managed lifecycle: structured logging,
health monitoring, Redis heartbeats with liveness watchdog, and graceful
shutdown.

v0.5.0: Captures audio via FFmpeg subprocess (ADR-0024).  FFmpeg handles
ALSA capture, dual-stream segmentation, and resampling.  Python manages
the subprocess lifecycle and atomic segment promotion.
"""

import asyncio
import contextlib
from typing import Any

import structlog
from silvasonic.core.service import SilvaService
from silvasonic.recorder.ffmpeg_pipeline import FFmpegConfig, FFmpegPipeline
from silvasonic.recorder.recording_stats import RecordingStats
from silvasonic.recorder.settings import RecorderSettings
from silvasonic.recorder.watchdog import RecordingWatchdog
from silvasonic.recorder.workspace import ensure_workspace

log = structlog.get_logger()


class RecorderService(SilvaService):
    """Recorder service — captures audio from USB microphones via FFmpeg.

    Class Attributes:
        service_name: ``"recorder"``
        service_port: ``9500`` (health endpoint, internal to silvasonic-net).
    """

    service_name = "recorder"
    service_port = 9500

    def __init__(self) -> None:
        """Initialize with settings from environment."""
        self._cfg = RecorderSettings()
        super().__init__(
            instance_id=self._cfg.INSTANCE_ID,
            redis_url=self._cfg.REDIS_URL,
            heartbeat_interval=self._cfg.HEARTBEAT_INTERVAL_S,
        )
        # Build pipeline config from controller-injected config (or defaults)
        injected_config = self._cfg.parse_injected_config()
        if injected_config is not None:
            self._pipeline_config = FFmpegConfig.from_injected_config(injected_config)
            log.info(
                "recorder.config_loaded",
                sample_rate=self._pipeline_config.sample_rate,
                channels=self._pipeline_config.channels,
                format=self._pipeline_config.format,
                raw_enabled=self._pipeline_config.raw_enabled,
                processed_enabled=self._pipeline_config.processed_enabled,
            )
        else:
            self._pipeline_config = FFmpegConfig()
            log.info("recorder.using_defaults")

        self._pipeline: FFmpegPipeline | None = None
        self._watchdog: RecordingWatchdog | None = None

    def get_extra_meta(self) -> dict[str, Any]:
        """Include recording metadata in heartbeat (ADR-0019 §2.4)."""
        meta: dict[str, Any] = {
            "recording": {
                "device": self._cfg.RECORDER_DEVICE,
                "sample_rate": self._pipeline_config.sample_rate,
                "channels": self._pipeline_config.channels,
                "format": self._pipeline_config.format,
                "segment_duration_s": self._pipeline_config.segment_duration_s,
                "active": self._pipeline.is_active if self._pipeline else False,
                "segments_promoted": (self._pipeline.segments_promoted if self._pipeline else 0),
                "ffmpeg_pid": self._pipeline.ffmpeg_pid if self._pipeline else None,
                "raw_enabled": self._pipeline_config.raw_enabled,
                "processed_enabled": self._pipeline_config.processed_enabled,
                "watchdog_restarts": self._watchdog.restart_count if self._watchdog else 0,
                "watchdog_max_restarts": self._watchdog.max_restarts
                if self._watchdog
                else self._cfg.RECORDER_WATCHDOG_MAX_RESTARTS,
                "watchdog_giving_up": self._watchdog.is_giving_up if self._watchdog else False,
                "watchdog_last_failure": self._watchdog.last_failure_reason
                if self._watchdog
                else None,
            },
        }
        return meta

    async def run(self) -> None:
        """Main recording lifecycle.

        1. Ensure workspace directories exist.
        2. Start FFmpeg pipeline with controller-injected device.
        3. Wait for shutdown signal (FFmpeg works autonomously).
        4. Stop pipeline and promote final segments.

        Device validation is **not** done here — the Controller already verified
        the device via ``/proc/asound/cards`` + sysfs before injecting it.
        If the device is unavailable, FFmpeg will fail and the multi-level
        recovery chain (Watchdog → Container Restart → Reconciliation) handles it.
        """
        self.health.update_status("recorder", True, "running")

        # Step 1: Ensure workspace
        workspace = self._cfg.workspace_path
        ensure_workspace(workspace)

        # Step 2: Resolve device and mock settings
        device = self._cfg.RECORDER_DEVICE
        use_mock = self._cfg.RECORDER_MOCK_SOURCE

        # Step 3: Create stats tracker + FFmpeg pipeline
        stats = RecordingStats(
            startup_duration_s=self._cfg.RECORDER_LOG_STARTUP_S,
            summary_interval_s=self._cfg.RECORDER_LOG_SUMMARY_INTERVAL_S,
        )
        self._pipeline = FFmpegPipeline(
            config=self._pipeline_config,
            workspace=workspace,
            device=device,
            mock_source=use_mock,
            ffmpeg_binary=self._cfg.FFMPEG_BINARY,
            ffmpeg_loglevel=self._cfg.FFMPEG_LOGLEVEL,
            stats=stats,
        )

        try:
            self._pipeline.start()
        except Exception as exc:
            log.exception(
                "recorder.pipeline_start_failed",
                device=device,
                sample_rate=self._pipeline_config.sample_rate,
                format=self._pipeline_config.format,
            )
            self.health.update_status("recorder", False, "Pipeline start failed")
            raise RuntimeError("Initial pipeline start failed") from exc

        # Step 4: Start watchdog + monitor loop
        self._watchdog = RecordingWatchdog(
            self._pipeline,
            max_restarts=self._cfg.RECORDER_WATCHDOG_MAX_RESTARTS,
            check_interval_s=self._cfg.RECORDER_WATCHDOG_CHECK_INTERVAL_S,
            stall_timeout_s=self._cfg.RECORDER_WATCHDOG_STALL_TIMEOUT_S,
            base_backoff_s=self._cfg.RECORDER_WATCHDOG_BASE_BACKOFF_S,
        )
        rec_task = asyncio.create_task(self._monitor_recording())

        try:
            # Watchdog handles monitoring + restarts; exits on shutdown or give-up
            await self._watchdog.watch(self._shutdown_event)
        except asyncio.CancelledError:  # pragma: no cover — integration-tested
            pass
        finally:
            rec_task.cancel()
            # Step 5: Stop pipeline (promotes remaining segments)
            if self._pipeline is not None:
                self._pipeline.stop()
                self._pipeline = None

    def _monitor_recording_once(self) -> None:
        """Check FFmpeg status and update health synchronously."""
        if self._pipeline is not None:
            is_recording = self._pipeline.is_active
            segments = self._pipeline.segments_promoted
            errors = len(self._pipeline.stderr_errors)
            if is_recording:
                details = f"Recording active (segments: {segments}, errors: {errors})"
            else:
                log.warning(
                    "recording.ffmpeg_exited_unexpectedly",
                    segments=segments,
                    errors=errors,
                )
                details = "FFmpeg process exited unexpectedly"
        else:
            is_recording = False
            details = "Pipeline not initialized"

        self.health.update_status("recording", is_recording, details)

    async def _monitor_recording(self) -> None:
        """Periodically check FFmpeg status and update health.

        Reports pipeline activity and segment count to the health
        monitor.
        """
        while not self._shutdown_event.is_set():
            self._monitor_recording_once()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._cfg.RECORDER_HEALTH_POLL_INTERVAL_S,
                )


if __name__ == "__main__":
    RecorderService().start()
