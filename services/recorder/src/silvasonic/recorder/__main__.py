"""Silvasonic Recorder — Audio capture service (ADR-0019).

The Recorder is an **immutable Tier 2** service. It has NO database access
and receives all configuration via environment variables (Profile Injection)
from the Controller. Multiple recorder instances may run concurrently.

Inherits the full ``SilvaService`` managed lifecycle: structured logging,
health monitoring, Redis heartbeats with liveness watchdog, and graceful
shutdown.
"""

import asyncio

from silvasonic.core.service import SilvaService
from silvasonic.recorder.settings import RecorderSettings


class RecorderService(SilvaService):
    """Recorder service — captures audio from USB microphones.

    Class Attributes:
        service_name: ``"recorder"``
        service_port: ``9500`` (health endpoint, internal to silvasonic-net).
    """

    service_name = "recorder"
    service_port = 9500
    # TODO(placeholder): Replace with actual recording-health detection logic.
    _recording_active: bool = True

    def __init__(self) -> None:
        """Initialize with Redis URL from environment."""
        cfg = RecorderSettings()
        super().__init__(
            instance_id=cfg.instance_id,
            redis_url=cfg.redis_url,
        )

    async def run(self) -> None:
        """Main recording loop.

        Starts background health monitors and runs until shutdown.
        Calls ``self.health.touch()`` each iteration to keep the
        liveness watchdog alive.
        """
        self.health.update_status("recorder", True, "running")

        # Start background health monitors
        rec_task = asyncio.create_task(self._monitor_recording())
        try:
            # TODO(placeholder): Replace with the actual recording loop
            # (e.g. opening audio device, writing .wav chunks, rotating files).
            while not self._shutdown_event.is_set():
                self.health.touch()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            rec_task.cancel()

    async def _monitor_recording(self) -> None:
        """Periodically check recording status.

        TODO(placeholder): Currently uses a hardcoded boolean. Will be replaced
        with actual checks (e.g. verifying .wav file growth, audio device status)
        once the recording pipeline is implemented (v0.4.0).
        """
        while True:
            is_recording = self._recording_active
            self.health.update_status(
                "recording",
                is_recording,
                "Recording active" if is_recording else "Recording failed",
            )
            await asyncio.sleep(5)


if __name__ == "__main__":
    RecorderService().start()
