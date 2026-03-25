"""Silvasonic Controller — Orchestration service (ADR-0019).

The Controller is a **mutable Tier 1** service that manages the lifecycle of
Tier 2 services (Recorder instances).  It inherits the full ``SilvaService``
managed lifecycle: structured logging, health monitoring, Redis heartbeats
with liveness watchdog, and graceful shutdown.

In addition to per-process resource metrics (inherited), the Controller
publishes **host-level** resource metrics (CPU, RAM) via ``get_extra_meta()``
so the Web-Interface dashboard can display system-wide utilisation.

v0.3.0: Connects to the host Podman engine via ``SilvasonicPodmanClient``,
seeds default configuration (ADR-0023), runs the reconciliation loop
with nudge subscriber (ADR-0013), and detects USB microphones via
sysfs-based USB detection (Phase 4).
"""

import asyncio
from pathlib import Path
from typing import Any, NoReturn

import structlog
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.device_scanner import DeviceScanner
from silvasonic.controller.log_forwarder import LogForwarder
from silvasonic.controller.nudge_subscriber import NudgeSubscriber
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.reconciler import ReconciliationLoop
from silvasonic.controller.seeder import run_all_seeders
from silvasonic.controller.settings import ControllerSettings
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.session import get_session
from silvasonic.core.resources import HostResourceCollector
from silvasonic.core.service import SilvaService

log = structlog.get_logger()


class ControllerService(SilvaService):
    """Controller service — orchestrates Tier 2 services.

    Class Attributes:
        service_name: ``"controller"``
        service_port: Default ``9100``, overridden by ``SILVASONIC_CONTROLLER_PORT``.
    """

    service_name = "controller"
    service_port = 9100  # Static default — overridden in __init__

    def __init__(self) -> None:
        """Initialize with Redis URL and Podman client from environment."""
        cfg = ControllerSettings()
        self.service_port = cfg.CONTROLLER_PORT
        super().__init__(
            instance_id="controller",
            redis_url=cfg.REDIS_URL,
        )
        self._host_resources = HostResourceCollector()
        self._podman_client = SilvasonicPodmanClient()
        self._container_manager = ContainerManager(self._podman_client)
        # Phase 4: USB device detection
        self._device_scanner = DeviceScanner()
        self._profile_matcher = ProfileMatcher()
        self._reconciliation_loop = ReconciliationLoop(
            self._container_manager,
            device_scanner=self._device_scanner,
            profile_matcher=self._profile_matcher,
        )
        self._nudge_subscriber = NudgeSubscriber(
            self._reconciliation_loop,
            redis_url=cfg.REDIS_URL,
        )
        # Phase 5: Live Log Streaming (ADR-0022)
        self._log_forwarder = LogForwarder(
            self._podman_client,
            redis_url=cfg.REDIS_URL,
        )

    def get_extra_meta(self) -> dict[str, Any]:
        """Include host-level resource metrics in heartbeat (ADR-0019 §2.4)."""
        return {"host_resources": self._host_resources.collect()}

    async def load_config(self) -> None:
        """Bootstrap DB with factory defaults (idempotent, ADR-0023).

        Called by ``SilvaService._setup()`` before ``run()``.  Best-effort:
        if the DB is unreachable the base class logs a warning and the
        service starts with hardcoded defaults.
        """
        async with get_session() as session:
            await run_all_seeders(session)

        # Phase 4: Initial device scan after seeding
        count = await self._reconciliation_loop.scan_and_sync_devices()
        log.info("controller.initial_scan", devices_found=count)

    async def run(self) -> None:
        """Main orchestration loop.

        Starts background health monitors and runs until shutdown.
        Calls ``self.health.touch()`` each iteration to keep the
        liveness watchdog alive.
        """
        self.health.update_status("controller", True, "running")

        # Start all background tasks as a managed group
        tasks = [
            asyncio.create_task(self._monitor_database()),
            asyncio.create_task(self._monitor_podman()),
            asyncio.create_task(self._reconciliation_loop.run()),
            asyncio.create_task(self._nudge_subscriber.run()),
            asyncio.create_task(self._log_forwarder.run()),
        ]
        try:
            while not self._shutdown_event.is_set():
                self.health.touch()
                await asyncio.sleep(1)
        except asyncio.CancelledError:  # pragma: no cover — integration-tested
            pass
        finally:
            for task in tasks:
                task.cancel()
            # Phase 6: Graceful Shutdown — stop all owned Tier 2 containers
            await self._stop_all_tier2()
            self._podman_client.close()

    async def _stop_all_tier2(self) -> None:
        """Stop all owned Tier 2 containers on shutdown (Phase 6).

        Called during graceful shutdown to ensure all Recorder instances
        are cleanly stopped before the Controller exits.  Best-effort:
        if Podman is unreachable, logs a warning and continues.
        """
        try:
            containers = await asyncio.to_thread(
                self._container_manager.list_managed,
            )
            for container in containers:
                name = str(container.get("name", ""))
                if name:
                    log.info("controller.shutdown.stopping", name=name)
                    await asyncio.to_thread(
                        self._container_manager.stop_and_remove,
                        name,
                    )
            log.info(
                "controller.shutdown.all_removed",
                count=len(containers),
            )
        except Exception:
            log.exception("controller.shutdown.failed")

    async def _monitor_database(self) -> NoReturn:
        """Periodically check database connectivity and update health status."""
        while True:
            is_connected = await check_database_connection()
            self.health.update_status(
                "database", is_connected, "Connected" if is_connected else "Connection failed"
            )
            await asyncio.sleep(10)

    async def _monitor_podman(self) -> None:
        """Periodically verify Podman socket connectivity (ADR-0013).

        On first call, attempts to connect to the Podman socket with
        retry logic.  Then periodically pings the engine and reports
        the number of managed containers.

        If the socket path does not exist on disk (e.g. in smoke-test
        containers without a mounted Podman socket), the component is
        registered as **optional** (``required=False``) so it does not
        affect the aggregated health status.
        """
        socket_path = self._podman_client.socket_path
        if not Path(socket_path).exists():
            self.health.update_status(
                "podman",
                False,
                f"Socket not found: {socket_path}",
                required=False,
            )
            return  # Nothing to monitor — exit coroutine

        # Initial connection with retry
        try:
            await asyncio.to_thread(self._podman_client.connect)
        except Exception:
            self.health.update_status("podman", False, "Socket unreachable")

        while True:
            is_alive = await asyncio.to_thread(self._podman_client.ping)
            self.health.update_status(
                "podman",
                is_alive,
                "Connected" if is_alive else "Socket unreachable",
            )
            if is_alive:
                containers = await asyncio.to_thread(
                    self._podman_client.list_managed_containers,
                )
                self.health.update_status(
                    "containers",
                    True,
                    f"{len(containers)} managed containers",
                )
            await asyncio.sleep(10)


if __name__ == "__main__":
    ControllerService().start()
