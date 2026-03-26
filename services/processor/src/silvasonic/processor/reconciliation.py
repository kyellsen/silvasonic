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
    ``file_processed`` path exists on disk.  If the file is missing,
    set ``local_deleted = true``.

    Args:
        session: Active async DB session.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        Number of rows reconciled (marked as deleted).
    """
    result = await session.execute(
        text("""
            SELECT id, file_processed
            FROM recordings
            WHERE local_deleted = false
        """)
    )
    rows = result.fetchall()

    reconciled = 0
    for row_id, file_processed in rows:
        full_path = recordings_dir / file_processed
        if not full_path.exists():
            await session.execute(
                text("UPDATE recordings SET local_deleted = true WHERE id = :id"),
                {"id": row_id},
            )
            reconciled += 1
            log.warning(
                "reconciliation.file_missing",
                recording_id=row_id,
                file=file_processed,
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
