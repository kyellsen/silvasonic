"""Reconciliation Audit — Split-Brain healing on Processor startup.

Runs once before the Indexer polling loop begins. Queries all ``recordings``
rows where ``local_deleted = false`` and verifies the referenced
``file_processed`` exists on disk.  Missing files are marked
``local_deleted = true`` to heal Split-Brain state caused by Panic-Mode
blind deletion (Phase 4) during DB outages.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


async def run_audit(
    session: AsyncSession,
    recordings_dir: Path,
) -> int:
    """Reconcile database state with filesystem.

    For each recording where ``local_deleted = false``, verify that the
    primary audio file exists on disk.  For dual-stream devices this is
    ``file_processed``; for raw-only devices it is ``file_raw``.
    If the file is missing, set ``local_deleted = true``.

    Args:
        session: Active async DB session.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        Number of rows reconciled (marked as deleted).
    """
    result = await session.execute(
        text("""
            SELECT id, file_processed, file_raw
            FROM recordings
            WHERE local_deleted = false
        """)
    )
    rows = result.fetchall()

    reconciled = 0
    for row_id, file_processed, file_raw in rows:
        if file_processed is None and file_raw is None:
            continue

        missing_file = None
        if file_processed is not None and not (recordings_dir / file_processed).exists():
            missing_file = file_processed
        elif file_raw is not None and not (recordings_dir / file_raw).exists():
            missing_file = file_raw

        if missing_file is not None:
            await session.execute(
                text("UPDATE recordings SET local_deleted = true WHERE id = :id"),
                {"id": row_id},
            )
            reconciled += 1
            log.warning(
                "reconciliation.file_missing",
                recording_id=row_id,
                file=missing_file,
                reason="reconciliation",
            )

    if reconciled > 0:
        await session.commit()

    log.info(
        "reconciliation.completed",
        total_checked=len(rows),
        reconciled=reconciled,
    )

    return reconciled
