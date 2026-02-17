import asyncio
import signal
from typing import NoReturn

from silvasonic.core.health import HealthMonitor, start_health_server
from silvasonic.core.logging import configure_logging

background_tasks: set[asyncio.Task[NoReturn]] = set()


# TODO(placeholder): Replace with actual recording-health detection logic.
SIMULATE_RECORDING_HEALTH = True


async def monitor_recording() -> NoReturn:
    """Periodically check recording status.

    TODO(placeholder): Currently uses a hardcoded boolean. Will be replaced
    with actual checks (e.g. verifying .wav file growth, audio device status)
    once the recording pipeline is implemented.
    """
    monitor = HealthMonitor()
    while True:
        # In the future, this will check if .wav files are actually being written
        is_recording = SIMULATE_RECORDING_HEALTH

        monitor.update_status(
            "recording", is_recording, "Recording active" if is_recording else "Recording failed"
        )
        await asyncio.sleep(5)


async def main() -> None:
    """Start the recorder service.

    The recorder is an immutable Tier 2 service. It has NO database access
    and receives all configuration via environment variables (Profile Injection)
    from the Controller. Multiple recorder instances may run concurrently.
    """
    configure_logging("recorder")

    # Start health server in a separate thread (default port 9500)
    start_health_server()

    # Start background health checks
    _health_task_rec = asyncio.create_task(monitor_recording())
    background_tasks.add(_health_task_rec)
    _health_task_rec.add_done_callback(background_tasks.discard)

    # TODO(placeholder): Replace with the actual recording loop
    # (e.g. opening audio device, writing .wav chunks, rotating files).
    # For now, just keep the loop running until a signal is received.
    stop_event = asyncio.Event()

    def handle_signal() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, handle_signal)
    loop.add_signal_handler(signal.SIGINT, handle_signal)

    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
