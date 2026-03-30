"""Silvasonic Processor — Data ingestion & storage retention (ADR-0019).

The Processor is an **immutable Tier 1** service responsible for:
- **Indexer:** Scans Recorder workspace for promoted WAV files, extracts
  metadata, and registers them in the ``recordings`` table.
- **Janitor:** Monitors disk utilization and enforces the escalating
  retention policy to prevent storage exhaustion (ADR-0011 §6).

Inherits the full ``SilvaService`` managed lifecycle: structured logging,
health monitoring, Redis heartbeats with liveness watchdog, and graceful
shutdown.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from silvasonic.core.config_schemas import ProcessorSettings
from silvasonic.core.database.session import get_session
from silvasonic.core.service import SilvaService
from silvasonic.processor import indexer, janitor, reconciliation
from silvasonic.processor.janitor import RetentionMode
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
            heartbeat_interval=cfg.HEARTBEAT_INTERVAL_S,
        )
        # Runtime config from DB — loaded in load_config(), defaults until then
        self._settings = ProcessorSettings()
        self._recordings_dir = Path(cfg.RECORDINGS_DIR)

        # Indexer metrics (reported in heartbeat)
        self._total_indexed: int = 0
        self._last_indexed_at: datetime | None = None
        self._reconciled_count: int = 0

        # Janitor metrics (reported in heartbeat)
        self._disk_usage_percent: float = 0.0
        self._janitor_mode: str = RetentionMode.IDLE.value
        self._files_deleted_total: int = 0

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
        """Service-specific heartbeat metadata (ADR-0019 §2.4)."""
        return {
            "indexer": {
                "total_indexed": self._total_indexed,
                "last_indexed_at": (
                    self._last_indexed_at.isoformat() if self._last_indexed_at else None
                ),
                "reconciled_count": self._reconciled_count,
            },
            "janitor": {
                "disk_usage_percent": round(self._disk_usage_percent, 1),
                "current_mode": self._janitor_mode,
                "files_deleted_total": self._files_deleted_total,
            },
        }

    async def run(self) -> None:
        """Main service loop — Reconciliation Audit + Indexer polling.

        1. Run Reconciliation Audit once on startup (Split-Brain healing).
        2. Periodic Indexer loop: scan workspace, register new recordings.
        """
        self.health.update_status("processor", True, "running")

        # --- Phase 1: Reconciliation Audit (once on startup) ---
        try:
            async with get_session() as session:
                self._reconciled_count = await reconciliation.run_audit(
                    session, self._recordings_dir
                )
            self.health.update_status("indexer", True, "reconciliation_complete")
        except Exception:
            log.exception("processor.reconciliation_failed")
            self.health.update_status("indexer", False, "reconciliation_failed")

        # --- Phase 2: Indexer + Janitor polling loop ---
        janitor_every_n = max(
            1,
            int(self._settings.janitor_interval_seconds / self._settings.indexer_poll_interval),
        )
        janitor_counter = 0

        log.info(
            "processor.indexer_started",
            interval=self._settings.indexer_poll_interval,
            recordings_dir=str(self._recordings_dir),
        )
        log.info(
            "processor.janitor_started",
            interval=self._settings.janitor_interval_seconds,
            every_n_cycles=janitor_every_n,
            batch_size=self._settings.janitor_batch_size,
        )

        # Bug #2 fix: persist error blacklist across indexer cycles
        skip_files: set[str] = set()

        while not self._shutdown_event.is_set():
            # --- Indexer (every cycle) ---
            try:
                async with get_session() as session:
                    result = await indexer.index_recordings(
                        session, self._recordings_dir, skip_files=skip_files
                    )
                if result.new > 0:
                    self._total_indexed += result.new
                    self._last_indexed_at = datetime.now(UTC)
                    self.health.update_status("indexer", True, f"indexed {result.new} new")
                elif result.errors > 0:
                    self.health.update_status("indexer", False, f"{result.errors} errors")
                else:
                    self.health.update_status("indexer", True, "idle")
                # Accumulate error files into blacklist for next cycle
                skip_files.update(result.error_details)
            except Exception:
                log.exception("processor.indexer_error")
                self.health.update_status("indexer", False, "error")

            # --- Janitor (every N cycles) ---
            janitor_counter += 1
            if janitor_counter >= janitor_every_n:
                janitor_counter = 0
                try:
                    jr = await janitor.run_cleanup_safe(self._recordings_dir, self._settings)
                    self._disk_usage_percent = jr.disk_usage_percent
                    self._janitor_mode = jr.mode.value
                    self._files_deleted_total += jr.files_deleted
                    healthy = jr.errors == 0
                    detail = f"{jr.mode.value} - deleted {jr.files_deleted}"
                    self.health.update_status("janitor", healthy, detail)
                except Exception:
                    log.exception("processor.janitor_error")
                    self.health.update_status("janitor", False, "error")

            self.health.touch()
            await asyncio.sleep(self._settings.indexer_poll_interval)


if __name__ == "__main__":
    ProcessorService().start()
