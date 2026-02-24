"""Silvasonic Controller — Orchestration service (ADR-0019).

The Controller is a **mutable Tier 1** service that manages the lifecycle of
Tier 2 services (Recorder instances).  It inherits the full ``SilvaService``
managed lifecycle: structured logging, health monitoring, Redis heartbeats
with liveness watchdog, and graceful shutdown.

In addition to per-process resource metrics (inherited), the Controller
publishes **host-level** resource metrics (CPU, RAM) via ``get_extra_meta()``
so the Web-Interface dashboard can display system-wide utilisation.
"""

import asyncio
import os
from typing import Any, NoReturn

from silvasonic.core.database.check import check_database_connection
from silvasonic.core.resources import HostResourceCollector
from silvasonic.core.service import SilvaService

# TODO(placeholder): Replace with actual recorder-spawn detection logic.
SIMULATE_RECORDER_SPAWN = True


class ControllerService(SilvaService):
    """Controller service — orchestrates Tier 2 services.

    Class Attributes:
        service_name: ``"controller"``
        service_port: From ``SILVASONIC_CONTROLLER_PORT`` env (default ``9100``).
    """

    service_name = "controller"
    service_port = int(os.environ.get("SILVASONIC_CONTROLLER_PORT", "9100"))

    def __init__(self) -> None:
        """Initialize with Redis URL from environment."""
        super().__init__(
            instance_id="controller",
            redis_url=os.environ.get("SILVASONIC_REDIS_URL", "redis://localhost:6379/0"),
        )
        self._host_resources = HostResourceCollector()

    def get_extra_meta(self) -> dict[str, Any]:
        """Include host-level resource metrics in heartbeat (ADR-0019 §2.4)."""
        return {"host_resources": self._host_resources.collect()}

    async def run(self) -> None:
        """Main orchestration loop.

        Starts background health monitors and runs until shutdown.
        Calls ``self.health.touch()`` each iteration to keep the
        liveness watchdog alive.
        """
        self.health.update_status("controller", True, "running")

        # Start background health monitors
        db_task = asyncio.create_task(self._monitor_database())
        spawn_task = asyncio.create_task(self._monitor_recorder_spawn())
        try:
            # TODO(placeholder): Replace with actual orchestration logic
            # (e.g. spawning recorders, managing schedules, handling commands).
            while not self._shutdown_event.is_set():
                self.health.touch()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            db_task.cancel()
            spawn_task.cancel()

    async def _monitor_database(self) -> NoReturn:
        """Periodically check database connectivity and update health status."""
        while True:
            is_connected = await check_database_connection()
            self.health.update_status(
                "database", is_connected, "Connected" if is_connected else "Connection failed"
            )
            await asyncio.sleep(10)

    async def _monitor_recorder_spawn(self) -> NoReturn:
        """Periodically check if a recorder has been spawned.

        TODO(placeholder): Currently uses a hardcoded boolean. Will be replaced
        with actual subprocess / container health checks once recorder spawning
        is implemented (v0.3.0).
        """
        while True:
            has_spawned_recorder = SIMULATE_RECORDER_SPAWN
            self.health.update_status(
                "recorder_spawn",
                has_spawned_recorder,
                "Recorder spawned" if has_spawned_recorder else "No recorder spawned",
            )
            await asyncio.sleep(5)


if __name__ == "__main__":
    ControllerService().start()
