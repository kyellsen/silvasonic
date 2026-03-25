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
import subprocess
from typing import Any

import structlog
from silvasonic.core.service import SilvaService
from silvasonic.recorder.ffmpeg_pipeline import FFmpegConfig, FFmpegPipeline
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
            instance_id=self._cfg.instance_id,
            redis_url=self._cfg.redis_url,
        )
        # Build pipeline config from injected profile (or defaults)
        profile = self._cfg.parse_profile()
        if profile is not None:
            self._pipeline_config = FFmpegConfig.from_profile(profile)
            log.info(
                "recorder.profile_loaded",
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
                "device": self._cfg.recorder_device,
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
                else self._cfg.recorder_watchdog_max_restarts,
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
        2. Pre-flight device validation (optional).
        3. Start FFmpeg pipeline.
        4. Wait for shutdown signal (FFmpeg works autonomously).
        5. Stop pipeline and promote final segments.
        """
        self.health.update_status("recorder", True, "running")

        # Step 1: Ensure workspace
        workspace = self._cfg.workspace_path
        ensure_workspace(workspace)

        # Step 2: Pre-flight device validation
        device = self._cfg.recorder_device

        if self._cfg.skip_device_check:
            log.info("recorder.device_check_skipped")
            self.health.update_status("recorder", True, "idle — device check skipped")
            await self._shutdown_event.wait()
            return

        use_mock = self._cfg.recorder_mock_source

        if not use_mock and not self._validate_device(device):
            self.health.update_status("recorder", False, "Device validation failed")
            await self._shutdown_event.wait()
            return

        # Step 3: Start FFmpeg pipeline
        self._pipeline = FFmpegPipeline(
            config=self._pipeline_config,
            workspace=workspace,
            device=device,
            mock_source=use_mock,
            ffmpeg_binary=self._cfg.ffmpeg_binary,
            ffmpeg_loglevel=self._cfg.ffmpeg_loglevel,
        )

        try:
            self._pipeline.start()
        except Exception:
            log.exception(
                "recorder.pipeline_start_failed",
                device=device,
                sample_rate=self._pipeline_config.sample_rate,
                format=self._pipeline_config.format,
            )
            self.health.update_status("recorder", False, "Pipeline start failed")
            return

        # Step 4: Start watchdog + monitor loop
        self._watchdog = RecordingWatchdog(
            self._pipeline,
            max_restarts=self._cfg.recorder_watchdog_max_restarts,
            check_interval_s=self._cfg.recorder_watchdog_check_interval_s,
            stall_timeout_s=self._cfg.recorder_watchdog_stall_timeout_s,
        )
        rec_task = asyncio.create_task(self._monitor_recording())

        try:
            # Watchdog handles monitoring + restarts; exits on shutdown or give-up
            await self._watchdog.watch(self._shutdown_event)
        except asyncio.CancelledError:
            pass
        finally:
            rec_task.cancel()
            # Step 5: Stop pipeline (promotes remaining segments)
            if self._pipeline is not None:
                self._pipeline.stop()
                self._pipeline = None

    def _validate_device(self, device: str) -> bool:
        """Validate that the ALSA audio device exists.

        Uses ``arecord -l`` to list available capture devices and
        checks if the configured device can be found.

        Args:
            device: ALSA device string (e.g. ``"hw:2,0"``).

        Returns:
            ``True`` if the device was found, ``False`` otherwise.
        """
        try:
            result = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout

            # Extract card number from device string (e.g. "hw:2,0" → "2")
            card_num = device.split(":")[1].split(",")[0] if ":" in device else device
            card_marker = f"card {card_num}:"

            if card_marker in output:
                # Find the device name for logging
                for line in output.splitlines():
                    if card_marker in line:
                        log.info(
                            "recorder.device_validated",
                            device=device,
                            info=line.strip(),
                        )
                        return True

            # Device not found — log available devices
            available_lines = [
                line.strip() for line in output.splitlines() if line.strip().startswith("card ")
            ]
            log.error(
                "recorder.device_not_found",
                device=device,
                available_devices=available_lines,
            )
            return False

        except (subprocess.TimeoutExpired, FileNotFoundError):
            log.exception("recorder.device_validation_failed", device=device)
            return False

    async def _monitor_recording(self) -> None:
        """Periodically check FFmpeg status and update health.

        Reports pipeline activity and segment count to the health
        monitor.
        """
        while True:
            if self._pipeline is not None:
                is_recording = self._pipeline.is_active
                segments = self._pipeline.segments_promoted
                errors = len(self._pipeline.stderr_errors)
                if is_recording:
                    details = f"Recording active (segments: {segments}, errors: {errors})"
                else:
                    details = "FFmpeg process exited unexpectedly"
            else:
                is_recording = False
                details = "Pipeline not initialized"

            self.health.update_status("recording", is_recording, details)
            await asyncio.sleep(5)


if __name__ == "__main__":
    RecorderService().start()
