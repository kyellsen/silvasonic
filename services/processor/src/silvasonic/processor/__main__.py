"""Silvasonic Processor — Data ingestion & storage retention (ADR-0019).

The Processor is an **immutable Tier 1** service responsible for:
- **Indexer:** Scans Recorder workspace for promoted WAV files, extracts
  metadata, and registers them in the ``recordings`` table (Phase 3).
- **Janitor:** Monitors disk utilization and enforces the escalating
  retention policy to prevent storage exhaustion (Phase 4).

Inherits the full ``SilvaService`` managed lifecycle: structured logging,
health monitoring, Redis heartbeats with liveness watchdog, and graceful
shutdown.

v0.5.0: Skeleton — placeholder ``run()`` with DB config loading.
Phase 3+4 will add Indexer and Janitor as periodic async tasks.
"""

import asyncio
from typing import Any

import structlog
from silvasonic.core.config_schemas import ProcessorSettings
from silvasonic.core.database.session import get_session
from silvasonic.core.service import SilvaService
from silvasonic.processor.settings import ProcessorEnvSettings

log = structlog.get_logger()


class ProcessorService(SilvaService):
    """Processor service — data ingestion and storage retention.

    Class Attributes:
        service_name: ``"processor"``
        service_port: Default ``9200``, overridden by ``SILVASONIC_PROCESSOR_PORT``.
    """

    service_name = "processor"
    service_port = 9200  # Static default — overridden in __init__

    def __init__(self) -> None:
        """Initialize with settings from environment."""
        cfg = ProcessorEnvSettings()
        self.service_port = cfg.PROCESSOR_PORT
        super().__init__(
            instance_id="processor",
            redis_url=cfg.REDIS_URL,
        )
        # Runtime config from DB — loaded in load_config(), defaults until then
        self._settings = ProcessorSettings()

    async def load_config(self) -> None:
        """Read ProcessorSettings from system_config table (ADR-0023).

        Called by ``SilvaService._setup()`` before ``run()``.  Best-effort:
        if the DB is unreachable the base class logs a warning and the
        service starts with Pydantic defaults.
        """
        from silvasonic.core.database.models.system import SystemConfig

        async with get_session() as session:
            row = await session.get(SystemConfig, "processor")
            if row is not None and isinstance(row.value, dict):
                self._settings = ProcessorSettings(**row.value)
                log.info(
                    "processor.config_loaded",
                    janitor_warning=self._settings.janitor_threshold_warning,
                    janitor_critical=self._settings.janitor_threshold_critical,
                    janitor_emergency=self._settings.janitor_threshold_emergency,
                    janitor_interval=self._settings.janitor_interval_seconds,
                    indexer_interval=self._settings.indexer_poll_interval,
                )
            else:
                log.info("processor.config_using_defaults")

    def get_extra_meta(self) -> dict[str, Any]:
        """Service-specific heartbeat metadata (ADR-0019 §2.4).

        Phase 1: empty. Phase 3+4 add indexer/janitor metrics.
        """
        return {}

    async def run(self) -> None:
        """Main service loop — placeholder for Phase 3+4.

        Phase 3 will add the Indexer periodic task.
        Phase 4 will add the Janitor periodic task.
        """
        self.health.update_status("processor", True, "running")
        log.info(
            "processor.started",
            indexer_interval=self._settings.indexer_poll_interval,
            janitor_interval=self._settings.janitor_interval_seconds,
        )

        while not self._shutdown_event.is_set():
            self.health.touch()
            await asyncio.sleep(1)


if __name__ == "__main__":
    ProcessorService().start()
