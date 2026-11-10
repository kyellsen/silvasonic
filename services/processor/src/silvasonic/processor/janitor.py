"""Janitor — Data retention and storage management.

Monitors NVMe disk utilization and enforces an escalating retention policy
(ADR-0011 §6) to prevent storage exhaustion.  The Janitor is the **only**
service authorized to delete files from the Recorder workspace (ADR-0009).

Three escalating modes:

- **Housekeeping** (>70%): Delete uploaded + fully analyzed recordings.
- **Defensive** (>80%): Delete uploaded recordings (analysis state ignored).
- **Panic** (>90%): Delete oldest files regardless of any status.

**Cloud-Sync-Fallback:** When the ``cloud_sync`` module is switched off
(``modules`` row disabled or absent), the ``uploaded_at IS NOT NULL`` condition is
skipped in Housekeeping and Defensive modes.  This prevents the Janitor from
remaining idle until Panic threshold is reached when the Cloud Sync feature is
disabled.
The fallback is clearly logged at WARNING level.

**Batch size:** Deletions are limited to ``cleanup_batch_files`` per cycle
to avoid I/O storms and excessive DB load.

Every deletion sets ``deleted_at`` and ``deletion_reason = 'retention'``.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import structlog
from silvasonic.core.schemas.settings import StorageSettings
from silvasonic.processor.modules.janitor_stats import JanitorStats
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

#: ``recordings.deletion_reason`` for a deletion by the retention policy.
DELETION_REASON_RETENTION = "retention"

# A recording is fully analysed when every analyzer entry in
# ``analysis_state`` has the state ``done`` (silvasonic.core.schemas.analysis).
_FULLY_ANALYSED = """
                  analysis_state != '{}'::jsonb
                  AND NOT EXISTS (
                      SELECT 1 FROM jsonb_each(analysis_state) AS kv
                      WHERE kv.value->>'state' IS DISTINCT FROM 'done'
                  )"""


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
    recordings_deleted: int = 0
    errors: int = 0
    cloud_sync_fallback: bool = False
    error_details: list[str] = field(default_factory=list)


async def get_disk_usage(path: Path) -> float:
    """Return disk usage percentage for the filesystem containing *path*.

    Args:
        path: Any path on the target filesystem.

    Returns:
        Usage percentage (0.0-100.0).
    """

    def _sync_usage() -> float:
        usage = shutil.disk_usage(path)
        return (usage.used / usage.total) * 100.0

    return await asyncio.to_thread(_sync_usage)


def evaluate_mode(disk_pct: float, settings: StorageSettings) -> RetentionMode:
    """Map disk utilization percentage to a retention mode.

    Args:
        disk_pct: Current disk usage percentage.
        settings: Storage settings with threshold values.

    Returns:
        The active retention mode.
    """
    if disk_pct >= settings.emergency_percent:
        return RetentionMode.PANIC
    if disk_pct >= settings.critical_percent:
        return RetentionMode.DEFENSIVE
    if disk_pct >= settings.warning_percent:
        return RetentionMode.HOUSEKEEPING
    return RetentionMode.IDLE


async def is_cloud_sync_enabled(session: AsyncSession) -> bool:
    """Check whether the ``cloud_sync`` module is switched on.

    Returns ``False`` when its ``modules`` row is disabled or absent,
    which triggers the Cloud-Sync-Fallback in Housekeeping and Defensive modes.
    """
    result = await session.execute(text("SELECT enabled FROM modules WHERE id = 'cloud_sync'"))
    row = result.fetchone()
    return bool(row is not None and row[0])


async def find_deletable(
    session: AsyncSession,
    mode: RetentionMode,
    batch_size: int,
    cloud_sync_active: bool,
) -> list[tuple[uuid.UUID, str, str | None]]:
    """Query recordings eligible for deletion in the given mode.

    Args:
        session: Active async DB session.
        mode: Current retention mode.
        batch_size: Maximum rows to return.
        cloud_sync_active: Whether Cloud Sync is enabled.

    Returns:
        List of ``(id, raw_path, processed_path)`` tuples, sorted oldest first.
    """
    if mode == RetentionMode.HOUSEKEEPING:
        if cloud_sync_active:
            query = text(f"""
                SELECT id, raw_path, processed_path
                FROM recordings
                WHERE deleted_at IS NULL
                  AND uploaded_at IS NOT NULL
                  AND {_FULLY_ANALYSED}
                ORDER BY started_at ASC
                LIMIT :batch
            """)
        else:
            # Cloud-Sync-Fallback: skip uploaded condition
            query = text(f"""
                SELECT id, raw_path, processed_path
                FROM recordings
                WHERE deleted_at IS NULL
                  AND {_FULLY_ANALYSED}
                ORDER BY started_at ASC
                LIMIT :batch
            """)

    elif mode == RetentionMode.DEFENSIVE:
        if cloud_sync_active:
            query = text("""
                SELECT id, raw_path, processed_path
                FROM recordings
                WHERE deleted_at IS NULL
                  AND uploaded_at IS NOT NULL
                ORDER BY started_at ASC
                LIMIT :batch
            """)
        else:
            # Cloud-Sync-Fallback: skip uploaded condition
            query = text("""
                SELECT id, raw_path, processed_path
                FROM recordings
                WHERE deleted_at IS NULL
                ORDER BY started_at ASC
                LIMIT :batch
            """)

    elif mode == RetentionMode.PANIC:
        query = text("""
            SELECT id, raw_path, processed_path
            FROM recordings
            WHERE deleted_at IS NULL
            ORDER BY started_at ASC
            LIMIT :batch
        """)

    else:
        return []

    result = await session.execute(query, {"batch": batch_size})
    return [(row[0], row[1], row[2]) for row in result.fetchall()]


async def delete_files(
    recordings_dir: Path,
    raw_path: str,
    processed_path: str | None,
) -> int:
    """Physically delete raw and processed WAV files from disk.

    Args:
        recordings_dir: Root of the Recorder workspace.
        raw_path: Relative path to raw WAV.
        processed_path: Relative path to processed WAV (``None`` for raw-only microphones).

    Returns:
        Number of files actually removed.
    """

    def _unlink_sync() -> int:
        removed = 0
        for rel_path in filter(None, (raw_path, processed_path)):
            full = recordings_dir / rel_path
            try:
                if not full.resolve().is_relative_to(recordings_dir.resolve()):
                    continue
                full.unlink()
                removed += 1
            except FileNotFoundError:
                pass  # Already deleted, considered success
        return removed

    return await asyncio.to_thread(_unlink_sync)


async def delete_worker_clips(
    session: AsyncSession,
    recording_id: uuid.UUID,
    workspace_root: Path,
) -> int:
    """Physically delete audio clips extracted by analyzers.

    1. Query the detections table for associated clips.
    2. Unlink the physical files from the respective analyzer workspaces via a thread.
    3. Nullify the clip_path column in the database only for successfully deleted paths.

    Args:
        session: Active async DB session.
        recording_id: Primary key of the deleted recording.
        workspace_root: Base Workspace path (e.g., ``/data``) to resolve
            ``{analyzer}/{clip_path}``.

    Returns:
        Number of physical clip files successfully unlinked.
    """
    result = await session.execute(
        text("""
            SELECT analyzer, clip_path 
            FROM detections 
            WHERE recording_id = :id AND clip_path IS NOT NULL
        """),
        {"id": recording_id},
    )
    rows = result.fetchall()
    if not rows:
        return 0

    def _unlink_clips_sync() -> tuple[list[str], Exception | None]:
        successful_clip_paths = []
        err: Exception | None = None
        for analyzer, clip_path in rows:
            # Expected path format: /data/birdnet/clips/file.wav
            full_path = workspace_root / analyzer / clip_path
            try:
                if not full_path.resolve().is_relative_to(workspace_root.resolve()):
                    continue
                full_path.unlink()
                successful_clip_paths.append(clip_path)
            except FileNotFoundError:
                # File already missing, safe to nullify in DB
                successful_clip_paths.append(clip_path)
            except OSError as e:
                log.exception(
                    "janitor.delete_worker_clip_error",
                    recording_id=str(recording_id),
                    clip_path=str(full_path),
                )
                err = e
                # Halt further unlinks for this recording
                break
        return successful_clip_paths, err

    successful_clip_paths, err = await asyncio.to_thread(_unlink_clips_sync)

    if successful_clip_paths:
        await session.execute(
            text("""
                UPDATE detections 
                SET clip_path = NULL 
                WHERE recording_id = :id AND clip_path = ANY(:clip_paths)
            """),
            {"id": recording_id, "clip_paths": successful_clip_paths},
        )

    if err:
        # Raise error to halt further soft_delete for this recording
        raise err

    return len(successful_clip_paths)


async def soft_delete(
    session: AsyncSession,
    recording_id: uuid.UUID,
) -> None:
    """Mark a recording as locally deleted in the database.

    The row is preserved for historical inventory — only ``deleted_at``
    and ``deletion_reason = 'retention'`` are set (Soft Delete pattern).
    """
    await session.execute(
        text("UPDATE recordings SET deleted_at = now(), deletion_reason = :reason WHERE id = :id"),
        {"id": recording_id, "reason": DELETION_REASON_RETENTION},
    )


async def panic_filesystem_fallback(
    recordings_dir: Path,
    batch_size: int,
) -> int:
    """Blind cleanup by mtime when the database is unreachable.

    Deletes the oldest WAV files across all microphone directories, sorted
    by modification time.  This is the last-resort fallback for Panic
    Mode when the DB is offline.

    Args:
        recordings_dir: Root of the Recorder workspace.
        batch_size: Maximum files to delete.

    Returns:
        Number of files deleted.
    """

    def _panic_sync() -> int:
        import heapq
        from collections.abc import Iterator

        def _generate_candidates() -> Iterator[tuple[float, list[Path]]]:
            candidates: dict[str, list[Path]] = {}
            for wav_path in recordings_dir.glob("*/data/*/*.wav"):
                try:
                    workspace_name = wav_path.parts[-4]
                    key = f"{workspace_name}/{wav_path.stem}"
                    if key not in candidates:
                        candidates[key] = []
                    candidates[key].append(wav_path)
                except IndexError:
                    continue

            for paths in candidates.values():
                try:
                    mtime = min(os.path.getmtime(p) for p in paths)
                    yield (mtime, paths)
                except OSError:
                    continue

        oldest_candidates = heapq.nsmallest(batch_size, _generate_candidates(), key=lambda x: x[0])

        deleted = 0
        for _, paths in oldest_candidates:
            candidate_deleted = False
            for wav_path in paths:
                try:
                    wav_path.unlink()
                    candidate_deleted = True
                    log.warning(
                        "janitor.panic_fallback_deleted",
                        file=str(wav_path.name),
                        reason="panic_filesystem_fallback",
                    )
                except FileNotFoundError:
                    pass
                except OSError:
                    log.exception("janitor.panic_fallback_error", file=str(wav_path.name))
            if candidate_deleted:
                deleted += 1

        return deleted

    return await asyncio.to_thread(_panic_sync)


async def run_cleanup(
    session: AsyncSession,
    recordings_dir: Path,
    settings: StorageSettings,
    mode: RetentionMode | None = None,
    disk_pct: float | None = None,
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
        settings: Active StorageSettings with thresholds and batch size
        mode: Optional pre-evaluated retention mode
        disk_pct: Optional pre-evaluated disk usage percentage
        stats: Two-Phase Logging stats object.

    Returns:
        JanitorResult with mode, deletions, and error counts.
    """
    if disk_pct is None:
        disk_pct = await get_disk_usage(recordings_dir)
    if mode is None:
        mode = evaluate_mode(disk_pct, settings)

    result = JanitorResult(mode=mode, disk_usage_percent=disk_pct)

    if mode == RetentionMode.IDLE:
        return result

    log.info(
        "janitor.cycle_start",
        mode=mode.value,
        disk_usage_percent=round(disk_pct, 1),
        batch_size=settings.cleanup_batch_files,
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
                "Cloud sync not enabled — skipping 'uploaded_at' condition. "
                "Files will be deleted based on analysis state only "
                "(Housekeeping) or age only (Defensive)."
            ),
        )

    # Find deletable recordings
    rows = await find_deletable(session, mode, settings.cleanup_batch_files, cloud_sync_active)

    # Delete files + soft-delete in DB
    workspace_root = recordings_dir.parent
    for rec_id, raw_path, processed_path in rows:
        try:
            await delete_files(recordings_dir, raw_path, processed_path)
            await soft_delete(session, rec_id)
            result.recordings_deleted += 1
            if stats:
                stats.record_deleted(
                    recording_id=rec_id,
                    processed_path=processed_path,
                    mode=mode.value,
                    cloud_sync_fallback=result.cloud_sync_fallback,
                )
            else:
                log.info(
                    "janitor.deleted",
                    recording_id=str(rec_id),
                    processed_path=processed_path,
                    mode=mode.value,
                    cloud_sync_fallback=result.cloud_sync_fallback,
                )

            # Post-cleanup for analyzer clips. Failure here must not abort soft_delete!
            try:
                await delete_worker_clips(session, rec_id, workspace_root)
            except Exception:
                result.errors += 1
                result.error_details.append(processed_path or raw_path)
                if stats:
                    stats.record_error(rec_id, processed_path)
                else:
                    log.exception("janitor.worker_clip_delete_error", recording_id=str(rec_id))
        except SQLAlchemyError as e:
            log.exception(
                "janitor.db_error",
                recording_id=str(rec_id),
                detail="Database error during cleanup, aborting cycle to prevent split-brain.",
            )
            result.errors += 1
            result.error_details.append(processed_path or raw_path)
            if stats:
                stats.record_error(rec_id, processed_path)
            await session.rollback()
            raise e
        except Exception:
            result.errors += 1
            result.error_details.append(processed_path or raw_path)
            if stats:
                stats.record_error(rec_id, processed_path)
            else:
                log.exception(
                    "janitor.delete_error",
                    recording_id=str(rec_id),
                    processed_path=processed_path,
                )

    # Always commit to ensure any partial NULLs applied by delete_worker_clips are saved,
    # even if recordings_deleted is 0 due to an exception aborting a soft_delete.
    await session.commit()

    log.info(
        "janitor.cycle_complete",
        mode=mode.value,
        recordings_deleted=result.recordings_deleted,
        errors=result.errors,
        disk_usage_percent=round(disk_pct, 1),
        cloud_sync_fallback=result.cloud_sync_fallback,
    )

    return result


async def run_cleanup_safe(
    recordings_dir: Path,
    settings: StorageSettings,
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

    disk_pct = await get_disk_usage(recordings_dir)
    mode = evaluate_mode(disk_pct, settings)

    if mode == RetentionMode.IDLE:
        return JanitorResult(mode=mode, disk_usage_percent=disk_pct)

    try:
        async with get_session() as session:
            return await run_cleanup(
                session, recordings_dir, settings, mode=mode, disk_pct=disk_pct, stats=stats
            )
    except Exception:
        if mode == RetentionMode.PANIC:
            log.critical(
                "janitor.db_unavailable_panic_fallback",
                disk_usage_percent=round(disk_pct, 1),
                detail="Database unreachable during PANIC — falling back to mtime cleanup.",
            )
            deleted = await panic_filesystem_fallback(recordings_dir, settings.cleanup_batch_files)
            return JanitorResult(
                mode=RetentionMode.PANIC,
                disk_usage_percent=disk_pct,
                recordings_deleted=deleted,
            )
        # Non-panic: skip this cycle safely
        log.warning(
            "janitor.db_unavailable_skipped",
            mode=mode.value,
            disk_usage_percent=round(disk_pct, 1),
            detail=f"Database unreachable during {mode.value} — skipping cycle (no data loss).",
        )
        return JanitorResult(mode=mode, disk_usage_percent=disk_pct)
