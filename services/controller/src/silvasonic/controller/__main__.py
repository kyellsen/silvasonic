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
from typing import Any

import structlog
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.controller_stats import ControllerStats
from silvasonic.controller.device_scanner import DeviceScanner
from silvasonic.controller.log_forwarder import LogForwarder
from silvasonic.controller.nudge_subscriber import NudgeSubscriber
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.reconciler import ReconciliationLoop
from silvasonic.controller.seeder import run_all_seeders
from silvasonic.controller.settings import ControllerSettings
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.session import get_session_factory
from silvasonic.core.resources import HostResourceCollector
from silvasonic.core.service import SilvaService

log = structlog.get_logger()

# Internal tick rate for the main loop (health touch + summary check).
_MAIN_TICK_S: float = 1.0


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
        self._cfg = ControllerSettings()
        self.service_port = self._cfg.CONTROLLER_PORT
        super().__init__(
            instance_id="controller",
            redis_url=self._cfg.REDIS_URL,
            heartbeat_interval=self._cfg.HEARTBEAT_INTERVAL_S,
        )
        self._host_resources = HostResourceCollector()
        self._podman_client = SilvasonicPodmanClient()
        self._container_manager = ContainerManager(self._podman_client)
        # Stats tracker (created here, wired to reconciler in run())
        self._stats: ControllerStats | None = None
        # Phase 4: USB device detection
        self._device_scanner = DeviceScanner()
        self._profile_matcher = ProfileMatcher()
        self._reconciliation_loop = ReconciliationLoop(
            self._container_manager,
            device_scanner=self._device_scanner,
            profile_matcher=self._profile_matcher,
            interval=self._cfg.RECONCILE_INTERVAL_S,
            grace_period_s=self._cfg.DEVICE_OFFLINE_GRACE_PERIOD_S,
            redis_url=self._cfg.REDIS_URL,
        )
        self._nudge_subscriber = NudgeSubscriber(
            self._reconciliation_loop,
            redis_url=self._cfg.REDIS_URL,
        )
        # Phase 5: Live Log Streaming (ADR-0022)
        self._log_forwarder = LogForwarder(
            self._podman_client,
            redis_url=self._cfg.REDIS_URL,
            poll_interval=self._cfg.LOG_FORWARDER_POLL_INTERVAL_S,
        )
        # DB/Podman state tracking for state-change logging
        self._db_was_connected: bool | None = None
        self._podman_was_connected: bool | None = None

    def get_extra_meta(self) -> dict[str, Any]:
        """Include host-level resource metrics in heartbeat (ADR-0019 §2.4)."""
        return {"host_resources": self._host_resources.collect()}

    async def load_config(self) -> None:
        """Bootstrap DB with factory defaults and scan devices (ADR-0023).

        Called by ``SilvaService._setup()`` before ``run()``.  Seeding and
        device scanning are decoupled: a seeder failure must NOT prevent
        the initial device scan (Data Capture Integrity — AGENTS.md §1).
        """
        # Step 1: Seed factory defaults (best-effort)
        try:
            failed = await run_all_seeders(get_session_factory())
            if failed:
                log.warning("controller.seeding_partial", failed=failed)
        except Exception:
            log.exception("controller.seeding_failed")

        # Step 2: Initial device scan (MUST run even if seeding failed)
        try:
            count = await self._reconciliation_loop.scan_and_sync_devices()
            log.info("controller.initial_scan", devices_found=count)
        except Exception as exc:
            log.error("controller.initial_scan_failed", error=str(exc))

    async def run(self) -> None:
        """Main orchestration loop.

        Starts background health monitors and runs until shutdown.
        Calls ``self.health.touch()`` each iteration to keep the
        liveness watchdog alive.  Emits periodic status summaries.
        """
        self.health.update_status("controller", True, "running")

        # Create stats tracker with envvar-configured durations
        self._stats = ControllerStats(
            startup_duration_s=self._cfg.CONTROLLER_LOG_STARTUP_S,
            summary_interval_s=self._cfg.CONTROLLER_LOG_SUMMARY_INTERVAL_S,
        )
        # Wire stats into reconciler and nudge subscriber
        self._reconciliation_loop.set_stats(self._stats)
        self._nudge_subscriber.set_stats(self._stats)

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
                # Emit periodic status summary
                if self._stats is not None:
                    summary = self._stats.get_summary_if_due()
                    if summary is not None:
                        await self._emit_status_summary(summary)  # pragma: no cover — system-tested
                await asyncio.sleep(_MAIN_TICK_S)
        except asyncio.CancelledError:  # pragma: no cover — integration-tested
            pass
        finally:
            for task in tasks:
                task.cancel()
            # Emit final summary before shutdown
            if self._stats is not None:
                self._stats.emit_final_summary()
            # Tier 2 containers intentionally left running (ADR-0013 §2.4).
            # On restart, the Controller adopts them via label query.
            # Explicit teardown is handled by scripts/stop.py.
            self._podman_client.close()

    async def _emit_status_summary(self, summary: dict[str, object]) -> None:
        """Collect live state and emit a periodic controller status summary."""
        # Collect current container list
        try:
            containers = await asyncio.to_thread(
                self._container_manager.list_managed,
            )
            container_names = [str(c.get("name", "")) for c in containers]
        except Exception:
            container_names = []

        log.info(
            "controller.summary",
            containers_running=len(container_names),
            container_names=container_names,
            db_connected=self._db_was_connected,
            podman_connected=self._podman_was_connected,
            **summary,
        )

    async def _monitor_database(self) -> None:
        """Periodically check database connectivity and update health status.

        Logs state changes (connected ↔ disconnected) individually.
        """
        while not self._shutdown_event.is_set():
            is_connected = await check_database_connection()
            self.health.update_status(
                "database", is_connected, "Connected" if is_connected else "Connection failed"
            )
            # Log state changes
            if self._db_was_connected is not None and is_connected != self._db_was_connected:
                if is_connected:
                    log.info("controller.database_reconnected")
                else:
                    log.warning("controller.database_disconnected")
            elif self._db_was_connected is None:
                if is_connected:
                    log.info("controller.database_connected")
                else:
                    log.warning("controller.database_unreachable")
            self._db_was_connected = is_connected
            await asyncio.sleep(self._cfg.CONTROLLER_MONITOR_POLL_INTERVAL_S)

    async def _monitor_podman(self) -> None:
        """Periodically verify Podman socket connectivity (ADR-0013).

        On first call, attempts to connect to the Podman socket with
        retry logic.  Then periodically pings the engine and reports
        the number of managed containers.  Logs state changes.

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

        while not self._shutdown_event.is_set():
            is_alive = await asyncio.to_thread(self._podman_client.ping)
            self.health.update_status(
                "podman",
                is_alive,
                "Connected" if is_alive else "Socket unreachable",
            )
            # Log state changes
            if self._podman_was_connected is not None and is_alive != self._podman_was_connected:
                if is_alive:
                    log.info("controller.podman_reconnected")
                else:
                    log.warning("controller.podman_disconnected")
            elif self._podman_was_connected is None:
                if is_alive:
                    log.info("controller.podman_connected")
                else:
                    log.warning("controller.podman_unreachable")
            self._podman_was_connected = is_alive

            if is_alive:
                containers = await asyncio.to_thread(
                    self._podman_client.list_managed_containers,
                )
                self.health.update_status(
                    "containers",
                    True,
                    f"{len(containers)} managed containers",
                )
            await asyncio.sleep(self._cfg.CONTROLLER_MONITOR_POLL_INTERVAL_S)


if __name__ == "__main__":
    ControllerService().start()
