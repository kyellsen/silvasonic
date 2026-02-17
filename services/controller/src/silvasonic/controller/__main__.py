import asyncio
import os
import signal
from typing import NoReturn

from silvasonic.core.database.check import check_database_connection
from silvasonic.core.health import HealthMonitor, start_health_server
from silvasonic.core.logging import configure_logging

CONTROLLER_HEALTH_PORT = int(os.environ.get("SILVASONIC_CONTROLLER_PORT", "9100"))
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


SIMULATE_RECORDER_SPAWN = True


async def monitor_recorder_spawn() -> NoReturn:
    """Periodically check if a recorder has been spawned (simulated for now)."""
    monitor = HealthMonitor()
    while True:
        # In the future, this will check if the controller has successfully spawned a recorder
        has_spawned_recorder = SIMULATE_RECORDER_SPAWN

        monitor.update_status(
            "recorder_spawn",
            has_spawned_recorder,
            "Recorder spawned" if has_spawned_recorder else "No recorder spawned",
        )
        await asyncio.sleep(5)


async def main() -> None:
    """Start the controller service."""
    configure_logging("controller")

    # Start health server in a separate thread (it uses http.server)
    start_health_server(port=CONTROLLER_HEALTH_PORT)

    # Start background health checks
    # Create a strong reference to the task to avoid    # Start background health checks
    _health_task_db = asyncio.create_task(monitor_database())
    _health_task_spawn = asyncio.create_task(monitor_recorder_spawn())

    # Keep strong references to avoid GC
    background_tasks = {_health_task_db, _health_task_spawn}
    _health_task_db.add_done_callback(background_tasks.discard)
    _health_task_spawn.add_done_callback(background_tasks.discard)

    # Placeholder — will be replaced with actual orchestration logic.
    # For now, just keep the loop running until a signal is received.
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, handle_signal)
    loop.add_signal_handler(signal.SIGINT, handle_signal)

    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
