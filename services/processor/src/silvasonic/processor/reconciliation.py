"""Reconciliation Audit — Split-Brain healing on Processor startup.

Runs once before the Indexer polling loop begins. Queries all ``recordings``
rows where ``deleted_at IS NULL`` and verifies the referenced
``processed_path`` exists on disk.  Rows whose file is gone get
``deleted_at`` (now) and ``deletion_reason = 'missing'`` to heal
Split-Brain state caused by Panic-Mode blind deletion (Phase 4) during
DB outages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

#: ``recordings.deletion_reason`` for a file found missing on disk.
DELETION_REASON_MISSING = "missing"


async def run_audit(
    session: AsyncSession,
    recordings_dir: Path,
) -> int:
    """Reconcile database state with filesystem.

    For each recording where ``deleted_at IS NULL``, verify that the
    primary audio file exists on disk.  For dual-stream microphones this is
    ``processed_path``; for raw-only microphones it is ``raw_path``.
    If the file is missing, set ``deleted_at`` and ``deletion_reason = 'missing'``.

    Args:
        session: Active async DB session.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        Number of rows reconciled (marked as deleted).
    """
    result = await session.execute(
        text("""
            SELECT id, processed_path, raw_path
            FROM recordings
            WHERE deleted_at IS NULL
        """)
    )
    rows = result.fetchall()
    # Release the read transaction: checking every file on disk must not hold the database write
    # lock (ADR-0037).  Nothing was written.
    await session.rollback()

    missing: list[object] = []
    for row_id, processed_path, raw_path in rows:
        if processed_path is None and raw_path is None:
            continue

        missing_file = None
        if processed_path is not None and not (recordings_dir / processed_path).exists():
            missing_file = processed_path
        elif raw_path is not None and not (recordings_dir / raw_path).exists():
            missing_file = raw_path

        if missing_file is not None:
            missing.append(row_id)
            log.warning(
                "reconciliation.file_missing",
                recording_id=str(row_id),
                file=missing_file,
                reason="reconciliation",
            )

    reconciled = len(missing)
    if missing:
        now = datetime.now(UTC)
        for row_id in missing:
            await session.execute(
                text(
                    "UPDATE recordings SET deleted_at = :now, deletion_reason = :reason "
                    "WHERE id = :id"
                ),
                {"id": row_id, "now": now, "reason": DELETION_REASON_MISSING},
            )
        await session.commit()

    log.info(
        "reconciliation.completed",
        total_checked=len(rows),
        reconciled=reconciled,
    )

    return reconciled
