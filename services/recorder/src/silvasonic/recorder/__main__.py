import asyncio
import signal
from typing import NoReturn

from silvasonic.core.database.check import check_database_connection
from silvasonic.core.health import HealthMonitor, start_health_server
from silvasonic.core.logging import configure_logging

background_tasks = set()


async def monitor_database() -> NoReturn:
    """Periodically check database connectivity and update health status."""
    monitor = HealthMonitor()
    while True:
        is_connected = await check_database_connection()
        monitor.update_status(
            "database", is_connected, "Connected" if is_connected else "Connection failed"
        )
        await asyncio.sleep(10)


SIMULATE_RECORDING_HEALTH = True


async def monitor_recording() -> NoReturn:
    """Periodically check recording status (simulated for now)."""
    monitor = HealthMonitor()
    while True:
        # In the future, this will check if .wav files are actually being written
        is_recording = SIMULATE_RECORDING_HEALTH

        monitor.update_status(
            "recording", is_recording, "Recording active" if is_recording else "Recording failed"
        )
        await asyncio.sleep(5)


async def main() -> None:
    """Start the recorder service."""
    configure_logging("recorder")

    # Start health server in a separate thread (default port 9500)
    start_health_server()

    # Start background health checks
    # Create a strong reference to the task to avoid garbage collection
    _health_task_db = asyncio.create_task(monitor_database())
    _health_task_rec = asyncio.create_task(monitor_recording())
    background_tasks.add(_health_task_db)
    background_tasks.add(_health_task_rec)
    _health_task_db.add_done_callback(background_tasks.discard)
    _health_task_rec.add_done_callback(background_tasks.discard)

    # Placeholder — will be replaced with the actual recording loop.
    # For now, just keep the loop running.
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, handle_signal)
    loop.add_signal_handler(signal.SIGINT, handle_signal)

    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
