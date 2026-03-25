"""Silvasonic Recorder — Audio capture service (ADR-0019).

The Recorder is an **immutable Tier 2** service. It has NO database access
and receives all configuration via environment variables (Profile Injection)
from the Controller. Multiple recorder instances may run concurrently.

Inherits the full ``SilvaService`` managed lifecycle: structured logging,
health monitoring, Redis heartbeats with liveness watchdog, and graceful
shutdown.

v0.4.0: Captures audio from USB microphones using ``sounddevice`` +
``soundfile``, writes segmented WAV files, and manages the buffer→data
promotion workflow.
"""

import asyncio
from typing import Any

import sounddevice as sd
import structlog
from silvasonic.core.service import SilvaService
from silvasonic.recorder.pipeline import AudioPipeline, PipelineConfig
from silvasonic.recorder.settings import RecorderSettings
from silvasonic.recorder.workspace import ensure_workspace

log = structlog.get_logger()


class RecorderService(SilvaService):
    """Recorder service — captures audio from USB microphones.

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
            self._pipeline_config = PipelineConfig.from_profile(profile)
            log.info(
                "recorder.profile_loaded",
                sample_rate=self._pipeline_config.sample_rate,
                channels=self._pipeline_config.channels,
                format=self._pipeline_config.format,
            )
        else:
            self._pipeline_config = PipelineConfig()
            log.info("recorder.using_defaults")

        self._pipeline: AudioPipeline | None = None

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
                "xruns": self._pipeline.xrun_count if self._pipeline else 0,
            },
        }
        return meta

    async def run(self) -> None:
        """Main recording loop.

        1. Ensure workspace directories exist.
        2. Start the audio pipeline.
        3. Drain the audio queue and write segments.
        4. On shutdown: stop pipeline and promote final segment.
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

        if not self._validate_device(device):
            self.health.update_status("recorder", False, "Device validation failed")
            await self._shutdown_event.wait()
            return

        # Step 3: Start pipeline
        self._pipeline = AudioPipeline(
            config=self._pipeline_config,
            workspace=workspace,
            device=device,
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

        # Step 4: Start background health monitor
        rec_task = asyncio.create_task(self._monitor_recording())

        try:
            # Step 5: Main loop — drain audio queue and keep watchdog alive
            while not self._shutdown_event.is_set():
                self.health.touch()
                # Drain available audio data from the queue
                await asyncio.to_thread(self._pipeline.drain_queue)
                await asyncio.sleep(0.05)  # ~20 Hz drain cycle
        except asyncio.CancelledError:
            pass
        finally:
            rec_task.cancel()
            # Step 6: Stop pipeline (drains remaining + promotes final segment)
            if self._pipeline is not None:
                self._pipeline.stop()
                self._pipeline = None

    def _validate_device(self, device: str) -> bool:
        """Validate that the audio device exists and is queryable.

        Logs all available input devices for diagnostics if the
        configured device cannot be found.  This provides a clear
        error message instead of an opaque ``PortAudioError``.

        Args:
            device: ALSA device string (e.g. ``"hw:2,0"``).

        Returns:
            ``True`` if the device was found, ``False`` otherwise.
        """
        try:
            info = sd.query_devices(device)
            log.info(
                "recorder.device_validated",
                device=device,
                name=info["name"],
                default_samplerate=info["default_samplerate"],
                max_input_channels=info["max_input_channels"],
            )
            return True
        except Exception:
            available = [
                {"idx": i, "name": d["name"], "inputs": d["max_input_channels"]}
                for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0
            ]
            log.error(
                "recorder.device_not_found",
                device=device,
                available_input_devices=available,
            )
            return False

    async def _monitor_recording(self) -> None:
        """Periodically check recording status and update health.

        Reports pipeline activity and xrun count to the health monitor.
        """
        while True:
            if self._pipeline is not None:
                is_recording = self._pipeline.is_active
                xruns = self._pipeline.xrun_count
                details = (
                    f"Recording active (xruns: {xruns})" if is_recording else "Recording stopped"
                )
            else:
                is_recording = False
                details = "Pipeline not initialized"

            self.health.update_status("recording", is_recording, details)
            await asyncio.sleep(5)


if __name__ == "__main__":
    RecorderService().start()
