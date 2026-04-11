"""Janitor — Data retention and storage management.

Monitors NVMe disk utilization and enforces an escalating retention policy
(ADR-0011 §6) to prevent storage exhaustion.  The Janitor is the **only**
service authorized to delete files from the Recorder workspace (ADR-0009).

Three escalating modes:

- **Housekeeping** (>70%): Delete uploaded + fully analyzed recordings.
- **Defensive** (>80%): Delete uploaded recordings (analysis state ignored).
- **Panic** (>90%): Delete oldest files regardless of any status.

**Cloud-Sync-Fallback:** When ``CloudSyncSettings.enabled`` is ``false``
(no upload target configured), the ``uploaded`` condition is skipped in Housekeeping and
Defensive modes.  This prevents the Janitor from remaining idle until Panic
threshold is reached when the Cloud Sync feature is disabled.
The fallback is clearly logged at WARNING level.

**Batch size:** Deletions are limited to ``janitor_batch_size`` per cycle
to avoid I/O storms and excessive DB load.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import structlog
from silvasonic.core.schemas.system_config import ProcessorSettings
from silvasonic.processor.modules.janitor_stats import JanitorStats
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


class RetentionMode(StrEnum):
    """Janitor operating mode based on disk utilization."""

    IDLE = "idle"
    HOUSEKEEPING = "housekeeping"
    DEFENSIVE = "defensive"
    PANIC = "panic"


@dataclass
class JanitorResult:
    """Result of a single Janitor cleanup cycle."""

    mode: RetentionMode
    disk_usage_percent: float
    files_deleted: int = 0
    errors: int = 0
    cloud_sync_fallback: bool = False
    error_details: list[str] = field(default_factory=list)


def get_disk_usage(path: Path) -> float:
    """Return disk usage percentage for the filesystem containing *path*.

    Args:
        path: Any path on the target filesystem.

    Returns:
        Usage percentage (0.0-100.0).
    """
    usage = shutil.disk_usage(path)
    return (usage.used / usage.total) * 100.0


def evaluate_mode(disk_pct: float, settings: ProcessorSettings) -> RetentionMode:
    """Map disk utilization percentage to a retention mode.

    Args:
        disk_pct: Current disk usage percentage.
        settings: Processor settings with threshold values.

    Returns:
        The active retention mode.
    """
    if disk_pct >= settings.janitor_threshold_emergency:
        return RetentionMode.PANIC
    if disk_pct >= settings.janitor_threshold_critical:
        return RetentionMode.DEFENSIVE
    if disk_pct >= settings.janitor_threshold_warning:
        return RetentionMode.HOUSEKEEPING
    return RetentionMode.IDLE


async def is_cloud_sync_enabled(session: AsyncSession) -> bool:
    """Check whether cloud sync is enabled in the system configuration.

    Returns ``False`` when ``CloudSyncSettings.enabled`` is ``false``,
    which triggers the Cloud-Sync-Fallback in Housekeeping and Defensive modes.
    """
    result = await session.execute(
        text("SELECT value->>'enabled' FROM system_config WHERE key = 'cloud_sync'")
    )
    row = result.fetchone()
    if row is not None and row[0] is not None:
        return bool(str(row[0]).lower() == "true")
    return False


async def find_deletable(
    session: AsyncSession,
    mode: RetentionMode,
    batch_size: int,
    cloud_sync_active: bool,
) -> list[tuple[int, str, str]]:
    """Query recordings eligible for deletion in the given mode.

    Args:
        session: Active async DB session.
        mode: Current retention mode.
        batch_size: Maximum rows to return.
        cloud_sync_active: Whether Cloud Sync is enabled.

    Returns:
        List of ``(id, file_raw, file_processed)`` tuples, sorted oldest first.
    """
    if mode == RetentionMode.HOUSEKEEPING:
        if cloud_sync_active:
            query = text("""
                SELECT id, file_raw, file_processed
                FROM recordings
                WHERE local_deleted = false
                  AND uploaded = true
                  AND NOT EXISTS (
                      SELECT 1 FROM jsonb_each_text(analysis_state) AS kv
                      WHERE kv.value != 'true'
                  )
                ORDER BY time ASC
                LIMIT :batch
            """)
        else:
            # Cloud-Sync-Fallback: skip uploaded condition
            query = text("""
                SELECT id, file_raw, file_processed
                FROM recordings
                WHERE local_deleted = false
                  AND NOT EXISTS (
                      SELECT 1 FROM jsonb_each_text(analysis_state) AS kv
                      WHERE kv.value != 'true'
                  )
                ORDER BY time ASC
                LIMIT :batch
            """)

    elif mode == RetentionMode.DEFENSIVE:
        if cloud_sync_active:
            query = text("""
                SELECT id, file_raw, file_processed
                FROM recordings
                WHERE local_deleted = false
                  AND uploaded = true
                ORDER BY time ASC
                LIMIT :batch
            """)
        else:
            # Cloud-Sync-Fallback: skip uploaded condition
            query = text("""
                SELECT id, file_raw, file_processed
                FROM recordings
                WHERE local_deleted = false
                ORDER BY time ASC
                LIMIT :batch
            """)

    elif mode == RetentionMode.PANIC:
        query = text("""
            SELECT id, file_raw, file_processed
            FROM recordings
            WHERE local_deleted = false
            ORDER BY time ASC
            LIMIT :batch
        """)

    else:
        return []

    result = await session.execute(query, {"batch": batch_size})
    return [(row[0], row[1], row[2]) for row in result.fetchall()]


def delete_files(
    recordings_dir: Path,
    file_raw: str,
    file_processed: str | None,
) -> int:
    """Physically delete raw and processed WAV files from disk.

    Args:
        recordings_dir: Root of the Recorder workspace.
        file_raw: Relative path to raw WAV.
        file_processed: Relative path to processed WAV (``None`` for raw-only devices).

    Returns:
        Number of files actually removed.
    """
    removed = 0
    for rel_path in filter(None, (file_raw, file_processed)):
        full = recordings_dir / rel_path
        if full.exists():
            full.unlink()
            removed += 1
    return removed


async def soft_delete(
    session: AsyncSession,
    recording_id: int,
) -> None:
    """Mark a recording as locally deleted in the database.

    The row is preserved for historical inventory — only the
    ``local_deleted`` flag is set to ``TRUE`` (Soft Delete pattern).
    """
    await session.execute(
        text("UPDATE recordings SET local_deleted = true WHERE id = :id"),
        {"id": recording_id},
    )


def panic_filesystem_fallback(
    recordings_dir: Path,
    batch_size: int,
) -> int:
    """Blind cleanup by mtime when the database is unreachable.

    Deletes the oldest WAV files across all sensor directories, sorted
    by modification time.  This is the last-resort fallback for Panic
    Mode when the DB is offline.

    Args:
        recordings_dir: Root of the Recorder workspace.
        batch_size: Maximum files to delete.

    Returns:
        Number of files deleted.
    """
    all_wavs: list[tuple[float, Path]] = []
    for wav_path in recordings_dir.glob("*/data/*/*.wav"):
        try:
            mtime = os.path.getmtime(wav_path)
            all_wavs.append((mtime, wav_path))
        except OSError:
            continue

    # Sort oldest first
    all_wavs.sort(key=lambda x: x[0])

    deleted = 0
    for _, wav_path in all_wavs[:batch_size]:
        try:
            wav_path.unlink()
            deleted += 1
            log.warning(
                "janitor.panic_fallback_deleted",
                file=str(wav_path.name),
                reason="panic_filesystem_fallback",
            )
        except OSError:
            log.exception("janitor.panic_fallback_error", file=str(wav_path.name))

    return deleted


async def run_cleanup(
    session: AsyncSession,
    recordings_dir: Path,
    settings: ProcessorSettings,
    stats: JanitorStats | None = None,
) -> JanitorResult:
    """Execute one Janitor cleanup cycle.

    1. Measure disk usage.
    2. Evaluate retention mode.
    3. Find deletable recordings (DB query).
    4. Physically delete files + soft-delete in DB.

    In Panic mode, if the DB query fails, falls back to filesystem
    ``mtime``-based blind cleanup.

    Args:
        session: Database session
        recordings_dir: Root directory for recordings
        settings: Active ProcessorSettings with intervals and batch sizes
        stats: Two-Phase Logging stats object.

    Returns:
        JanitorResult with mode, deletions, and error counts.
    """
    disk_pct = get_disk_usage(recordings_dir)
    mode = evaluate_mode(disk_pct, settings)

    result = JanitorResult(mode=mode, disk_usage_percent=disk_pct)

    if mode == RetentionMode.IDLE:
        return result

    log.info(
        "janitor.cycle_start",
        mode=mode.value,
        disk_usage_percent=round(disk_pct, 1),
        batch_size=settings.janitor_batch_size,
    )

    # Check Cloud Sync availability (for Housekeeping/Defensive fallback)
    cloud_sync_active = await is_cloud_sync_enabled(session)
    if not cloud_sync_active and mode in (RetentionMode.HOUSEKEEPING, RetentionMode.DEFENSIVE):
        result.cloud_sync_fallback = True
        log.warning(
            "janitor.cloud_sync_fallback_active",
            mode=mode.value,
            reason="upload_disabled",
            detail=(
                "Cloud sync not enabled — skipping 'uploaded' condition. "
                "Files will be deleted based on analysis state only "
                "(Housekeeping) or age only (Defensive)."
            ),
        )

    # Find deletable recordings
    rows = await find_deletable(session, mode, settings.janitor_batch_size, cloud_sync_active)

    # Delete files + soft-delete in DB
    for rec_id, file_raw, file_processed in rows:
        try:
            delete_files(recordings_dir, file_raw, file_processed)
            await soft_delete(session, rec_id)
            result.files_deleted += 1
            if stats:
                stats.record_deleted(
                    recording_id=rec_id,
                    file_processed=file_processed,
                    mode=mode.value,
                    cloud_sync_fallback=result.cloud_sync_fallback,
                )
            else:
                log.info(
                    "janitor.deleted",
                    recording_id=rec_id,
                    file_processed=file_processed,
                    mode=mode.value,
                    cloud_sync_fallback=result.cloud_sync_fallback,
                )
        except Exception:
            result.errors += 1
            result.error_details.append(file_processed if file_processed else "")
            if stats:
                stats.record_error(rec_id, file_processed)
            else:
                log.exception(
                    "janitor.delete_error",
                    recording_id=rec_id,
                    file_processed=file_processed,
                )

    if result.files_deleted > 0:
        await session.commit()

    log.info(
        "janitor.cycle_complete",
        mode=mode.value,
        files_deleted=result.files_deleted,
        errors=result.errors,
        disk_usage_percent=round(disk_pct, 1),
        cloud_sync_fallback=result.cloud_sync_fallback,
    )

    return result


async def run_cleanup_safe(
    recordings_dir: Path,
    settings: ProcessorSettings,
    stats: JanitorStats | None = None,
) -> JanitorResult:
    """Top-level entry point with DB-failure protection.

    Wraps :func:`run_cleanup` in a try/except.  If the DB session
    fails during **Panic** mode, falls back to filesystem-based
    blind cleanup.  In non-Panic modes, DB failure causes the cycle
    to be skipped (no data loss risk).

    Args:
        recordings_dir: Root directory path
        settings: Active configuration
        stats: Two-Phase Logging stats object.

    Returns:
        JanitorResult.
    """
    from silvasonic.core.database.session import get_session

    disk_pct = get_disk_usage(recordings_dir)
    mode = evaluate_mode(disk_pct, settings)

    if mode == RetentionMode.IDLE:
        return JanitorResult(mode=mode, disk_usage_percent=disk_pct)

    try:
        async with get_session() as session:
            return await run_cleanup(session, recordings_dir, settings, stats=stats)
    except Exception:
        if mode == RetentionMode.PANIC:
            log.critical(
                "janitor.db_unavailable_panic_fallback",
                disk_usage_percent=round(disk_pct, 1),
                detail="Database unreachable during PANIC — falling back to mtime cleanup.",
            )
            deleted = panic_filesystem_fallback(recordings_dir, settings.janitor_batch_size)
            return JanitorResult(
                mode=RetentionMode.PANIC,
                disk_usage_percent=disk_pct,
                files_deleted=deleted,
            )
        # Non-panic: skip this cycle safely
        log.warning(
            "janitor.db_unavailable_skipped",
            mode=mode.value,
            disk_usage_percent=round(disk_pct, 1),
            detail=f"Database unreachable during {mode.value} — skipping cycle (no data loss).",
        )
        return JanitorResult(mode=mode, disk_usage_percent=disk_pct)
