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
from typing import TYPE_CHECKING, Any

import structlog
from silvasonic.core.config_schemas import ProcessorSettings
from silvasonic.core.database.session import get_session
from silvasonic.core.service import SilvaService
from silvasonic.processor import indexer, janitor, reconciliation
from silvasonic.processor.janitor import RetentionMode
from silvasonic.processor.settings import ProcessorEnvSettings

if TYPE_CHECKING:
    from silvasonic.processor.modules.indexer_stats import IndexerStats
    from silvasonic.processor.modules.janitor_stats import JanitorStats

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
        self._env_config = ProcessorEnvSettings()
        self.service_port = self._env_config.PROCESSOR_PORT
        super().__init__(
            instance_id="processor",
            redis_url=self._env_config.REDIS_URL,
            heartbeat_interval=self._env_config.HEARTBEAT_INTERVAL_S,
        )
        # Runtime config from DB — loaded in load_config(), defaults until then
        self._settings = ProcessorSettings()
        self._recordings_dir = Path(self._env_config.RECORDINGS_DIR)

        # Indexer metrics (reported in heartbeat)
        self._total_indexed: int = 0
        self._last_indexed_at: datetime | None = None
        self._reconciled_count: int = 0

        # Janitor metrics (reported in heartbeat)
        self._disk_usage_percent: float = 0.0
        self._janitor_mode: str = RetentionMode.IDLE.value
        self._cloud_sync_fallback: bool = False
        self._files_deleted_total: int = 0
        self._janitor_counter: int = 0
        self._janitor_every_n: int = 1

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
        extra = {
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

        # Upload Worker metrics
        if hasattr(self, "_upload_worker"):
            uw = self._upload_worker.stats
            extra["cloud_sync"] = {
                "total_pending": uw.total_pending,
                "uploaded_count": uw.uploaded_count,
                "failed_count": uw.failed_count,
                "last_upload_at": uw.last_upload_at,
            }

        return extra

    async def _run_reconciliation_audit_once(self) -> None:
        """Run Reconciliation Audit once on startup (Split-Brain healing)."""
        try:
            async with get_session() as session:
                self._reconciled_count = await reconciliation.run_audit(
                    session, self._recordings_dir
                )
            self.health.update_status("indexer", True, "reconciliation_complete")
        except Exception:
            log.exception("processor.reconciliation_failed")
            self.health.update_status("indexer", False, "reconciliation_failed")

    async def _run_indexer_cycle(self, errored_files: set[str], stats: "IndexerStats") -> None:
        """Run one cycle of the Indexer."""
        try:
            async with get_session() as session:
                result = await indexer.index_recordings(
                    session, self._recordings_dir, errored_files=errored_files, stats=stats
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
            errored_files.update(result.error_details)
            if errored_files:
                log.info(
                    "processor.errored_files_blacklisted",
                    count=len(errored_files),
                )
        except Exception:
            log.exception("processor.indexer_error")
            self.health.update_status("indexer", False, "error")

    async def _run_janitor_cycle(self, stats: "JanitorStats") -> None:
        """Run one cycle of the Janitor, respecting the n-cycle interval."""
        self._janitor_counter += 1
        if self._janitor_counter >= self._janitor_every_n:
            self._janitor_counter = 0
            try:
                jr = await janitor.run_cleanup_safe(
                    self._recordings_dir, self._settings, stats=stats
                )
                self._disk_usage_percent = jr.disk_usage_percent
                self._janitor_mode = jr.mode.value
                self._cloud_sync_fallback = jr.cloud_sync_fallback
                self._files_deleted_total += jr.files_deleted
                healthy = jr.errors == 0
                detail = f"{jr.mode.value} - deleted {jr.files_deleted}"
                self.health.update_status("janitor", healthy, detail)
            except Exception:
                log.exception("processor.janitor_error")
                self.health.update_status("janitor", False, "error")

    async def run(self) -> None:
        """Main service loop — Reconciliation Audit + Indexer polling.

        1. Run Reconciliation Audit once on startup (Split-Brain healing).
        2. Start the UploadWorker as a background task.
        3. Periodic Indexer loop: scan workspace, register new recordings.
        """
        self.health.update_status("processor", True, "running")

        # Initialize Upload Worker
        from silvasonic.processor.modules.indexer_stats import IndexerStats
        from silvasonic.processor.modules.janitor_stats import JanitorStats
        from silvasonic.processor.modules.upload_stats import UploadStats
        from silvasonic.processor.upload_worker import UploadWorker

        upload_stats = UploadStats(
            startup_duration_s=self._env_config.PROCESSOR_LOG_STARTUP_S,
            summary_interval_s=self._env_config.PROCESSOR_LOG_SUMMARY_INTERVAL_S,
        )
        self._indexer_stats = IndexerStats(
            startup_duration_s=self._env_config.PROCESSOR_LOG_STARTUP_S,
            summary_interval_s=self._env_config.PROCESSOR_LOG_SUMMARY_INTERVAL_S,
        )
        self._janitor_stats = JanitorStats(
            startup_duration_s=self._env_config.PROCESSOR_LOG_STARTUP_S,
            summary_interval_s=self._env_config.PROCESSOR_LOG_SUMMARY_INTERVAL_S,
        )
        self._upload_worker = UploadWorker(
            get_session, self.health, self._recordings_dir, stats=upload_stats
        )

        # --- Phase 1: Reconciliation Audit (once on startup) ---
        await self._run_reconciliation_audit_once()

        # Start Upload Worker in background
        self._upload_task = asyncio.create_task(self._upload_worker.run())

        # --- Phase 2: Indexer + Janitor polling loop ---
        self._janitor_every_n = max(
            1,
            int(self._settings.janitor_interval_seconds / self._settings.indexer_poll_interval),
        )
        self._janitor_counter = 0

        log.info(
            "processor.indexer_started",
            interval=self._settings.indexer_poll_interval,
            recordings_dir=str(self._recordings_dir),
        )
        log.info(
            "processor.janitor_started",
            interval=self._settings.janitor_interval_seconds,
            every_n_cycles=self._janitor_every_n,
            batch_size=self._settings.janitor_batch_size,
        )

        # Prevent log-flood: files that fail metadata extraction (corrupt WAV)
        # are skipped for the remainder of this process lifetime.  After restart
        # they get one fresh attempt — intentional, since the segment file could
        # theoretically have been replaced on disk.
        errored_files: set[str] = set()

        while not self._shutdown_event.is_set():
            # --- Indexer (every cycle) ---
            await self._run_indexer_cycle(errored_files, self._indexer_stats)
            self._indexer_stats.maybe_emit_summary()

            # --- Janitor (every N cycles) ---
            await self._run_janitor_cycle(self._janitor_stats)
            self._janitor_stats.maybe_emit_summary(
                mode=self._janitor_mode,
                disk_usage_percent=self._disk_usage_percent,
                cloud_sync_fallback=self._cloud_sync_fallback,
            )

            self.health.touch()
            await asyncio.sleep(self._settings.indexer_poll_interval)

        # Emit final shutdown summaries
        self._indexer_stats.emit_final_summary()
        self._janitor_stats.emit_final_summary()


if __name__ == "__main__":
    ProcessorService().start()
