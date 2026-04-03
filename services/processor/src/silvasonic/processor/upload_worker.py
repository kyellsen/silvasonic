"""Main upload worker orchestrator for Cloud Sync (v0.6.0).

Chains work polling, FLAC encoding, path building, uploading, and audit logging.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

import structlog
from silvasonic.core.config_schemas import CloudSyncSettings
from silvasonic.core.crypto import load_encryption_key
from silvasonic.core.database.models.system import SystemConfig
from silvasonic.core.health import HealthMonitor
from silvasonic.processor.modules.audit_logger import log_upload_attempt
from silvasonic.processor.modules.flac_encoder import FlacEncodingError, encode_wav_to_flac
from silvasonic.processor.modules.path_builder import build_remote_path
from silvasonic.processor.modules.rclone_client import RcloneClient
from silvasonic.processor.modules.upload_stats import UploadStats
from silvasonic.processor.modules.work_poller import find_pending_uploads
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


def _is_within_window(start_hour: int | None, end_hour: int | None) -> bool:
    """Return True if the current UTC time is within the allowed schedule window.

    If either hour is None, continuous upload is assumed.
    """
    if start_hour is None or end_hour is None:
        return True

    current_hour = datetime.now(UTC).hour
    if start_hour <= end_hour:
        return start_hour <= current_hour < end_hour
    # Overnight window (e.g., 22 to 6)
    return current_hour >= start_hour or current_hour < end_hour


class UploadWorker:
    """Orchestrates the background upload pipeline."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        health_monitor: HealthMonitor,
        stats: UploadStats | None = None,
    ) -> None:
        """Initialize the UploadWorker."""
        self.session_factory = session_factory
        self.health = health_monitor
        self.stats = stats or UploadStats()
        self._shutdown_event = asyncio.Event()

    async def _fetch_config(self) -> tuple[str, CloudSyncSettings | None]:
        """Fetch station name and cloud sync settings from the DB."""
        async with self.session_factory() as session:
            # Get station name
            sys_conf = await session.get(SystemConfig, "system")
            station_name = "silvasonic"
            if sys_conf and "station_name" in sys_conf.value:
                station_name = sys_conf.value["station_name"]

            # Get cloud sync settings
            sync_conf = await session.get(SystemConfig, "cloud_sync")
            if not sync_conf:
                return station_name, None

            try:
                settings = CloudSyncSettings(**sync_conf.value)
                return station_name, settings
            except Exception as e:
                log.error("upload_worker.config_invalid", error=str(e))
                return station_name, None

    async def _process_batch(
        self,
        station_name: str,
        settings: CloudSyncSettings,
        encryption_key: bytes,
    ) -> bool:
        """Process a single batch. Return False if connection error forces abort."""
        async with self.session_factory() as session:
            pending = await find_pending_uploads(session, batch_size=50)
            self.stats.update_pending(len(pending))

            if not pending:
                return True

            rclone = RcloneClient(settings, encryption_key)

            for item in pending:
                if self._shutdown_event.is_set():
                    break

                item.station_name = station_name

                # Verify file still exists on disk (Janitor might have deleted it)
                if not item.file_raw.exists():
                    log.warning("upload_worker.file_missing", file=item.file_raw.name)
                    # We do NOT mark it uploaded if it's missing, to avoid false audits.
                    # Janitor sets local_deleted=True, so it naturally falls out of the queue later.
                    continue

                target_filename = item.file_raw.with_suffix(".flac").name
                remote_path = build_remote_path(
                    item.station_name, item.sensor_id, item.time, target_filename
                )

                # 1. Encode
                try:
                    flac_path = await encode_wav_to_flac(item.file_raw, item.file_raw.parent)
                except FlacEncodingError as e:
                    self.stats.record_attempt(False, 0, item.file_raw.name, remote_path, 0.0)
                    await log_upload_attempt(
                        session,
                        item.recording_id,
                        target_filename,
                        remote_path,
                        item.file_raw.stat().st_size,
                        False,
                        str(e),
                        0.0,
                    )
                    await session.commit()
                    continue

                # 2. Upload
                try:
                    result = await rclone.upload_file(flac_path, remote_path)

                    self.stats.record_attempt(
                        result.success,
                        result.bytes_transferred,
                        item.file_raw.name,
                        remote_path,
                        result.duration_s,
                    )

                    # 3. Audit Logging
                    await log_upload_attempt(
                        session,
                        item.recording_id,
                        target_filename,
                        remote_path,
                        result.bytes_transferred if result.success else flac_path.stat().st_size,
                        result.success,
                        result.error_message,
                        result.duration_s,
                    )
                    await session.commit()

                    # If connection error, abort batch so we don't spam 50 timeouts
                    if result.is_connection_error:
                        return False

                finally:
                    # Always clean up the temporary FLAC file
                    if flac_path.exists():
                        flac_path.unlink()

            return True

    async def run(self) -> None:
        """Run the infinite polling loop."""
        log.info("upload_worker.started")

        try:
            encryption_key = load_encryption_key()
        except RuntimeError as e:
            log.error("upload_worker.fatal", error=str(e))
            self.health.update_status("upload_worker", False, "fatal: Missing encryption key")
            return

        while not self._shutdown_event.is_set():
            try:
                station_name, settings = await self._fetch_config()

                if not settings or not settings.enabled:
                    self.health.update_status("upload_worker", True, "state: disabled")
                    await self._sleep(60)  # Default sleep if inactive
                    continue

                if not settings.remote_type:
                    log.warning("upload_worker.no_remote_configured")
                    self.health.update_status("upload_worker", False, "error: no_target")
                    await self._sleep(settings.poll_interval)
                    continue

                if not _is_within_window(settings.schedule_start_hour, settings.schedule_end_hour):
                    self.health.update_status("upload_worker", True, "state: outside_window")
                    await self._sleep(settings.poll_interval)
                    continue

                # We are active and within window
                self.health.update_status(
                    "upload_worker",
                    True,
                    f"pending: {self.stats.total_pending}, target: {settings.remote_type}",
                )

                success = await self._process_batch(station_name, settings, encryption_key)

                if not success:
                    log.warning("upload_worker.batch_aborted_due_to_connection_error")
                    self.health.update_status("upload_worker", False, "error: connection_error")

                await self._sleep(settings.poll_interval)

            except Exception as e:
                log.exception("upload_worker.crash", exc_info=e)
                self.health.update_status("upload_worker", False, f"crash: {e}")
                await self._sleep(60)  # Fixed backoff on total crash

        self.stats.emit_final_summary()
        log.info("upload_worker.stopped")

    async def _sleep(self, seconds: int) -> None:
        """Sleep until timeout or shutdown is requested."""
        import contextlib

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=seconds)

    async def stop(self) -> None:
        """Signal the worker to shut down smoothly."""
        self._shutdown_event.set()
