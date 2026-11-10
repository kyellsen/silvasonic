"""Work poller for discovering pending uploads."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from silvasonic.core.database.models.recordings import Recording, Upload
from silvasonic.core.database.models.system import Microphone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PendingUpload:
    """A recording that needs to be uploaded."""

    recording_id: uuid.UUID
    raw_path: Path
    hardware_id: str
    station_name: str
    started_at: datetime
    profile_slug: str


async def find_pending_uploads(
    session: AsyncSession,
    recordings_dir: Path,
    batch_size: int = 50,
    max_retries: int = 3,
) -> list[PendingUpload]:
    """Find recordings that haven't been uploaded and haven't been deleted.

    Recordings that have already failed ``max_retries`` times are excluded
    from the result to prevent an ever-growing retry storm.

    Args:
        session: Active database session.
        recordings_dir: Root of the Recorder workspace.  Prepended to the
            relative ``raw_path`` column to produce absolute paths.
        batch_size: Max number of recordings to return.
        max_retries: Maximum number of failed upload attempts before a
            recording is excluded from polling.

    Returns:
        A list of PendingUpload objects representing recordings to upload.
    """
    # Subquery: count failed upload attempts per recording
    failed_attempts = (
        select(
            Upload.recording_id,
            func.count().label("attempt_count"),
        )
        .where(Upload.success.is_(False))
        .group_by(Upload.recording_id)
        .subquery()
    )

    stmt = (
        select(Recording, Microphone.hardware_id, Microphone.profile_slug)
        .join(Microphone, Recording.microphone_id == Microphone.id)
        .outerjoin(failed_attempts, Recording.id == failed_attempts.c.recording_id)
        .where(Recording.uploaded_at.is_(None))
        .where(Recording.deleted_at.is_(None))
        .where(
            # Include recordings that have never been tried (NULL)
            # or have fewer than max_retries failed attempts
            (failed_attempts.c.attempt_count.is_(None))
            | (failed_attempts.c.attempt_count < max_retries)
        )
        .order_by(Recording.started_at.asc())
        .limit(batch_size)
    )

    result = await session.execute(stmt)
    rows = result.all()

    pending = []
    for recording, hardware_id, profile_slug in rows:
        pending.append(
            PendingUpload(
                recording_id=recording.id,
                raw_path=recordings_dir / recording.raw_path,
                hardware_id=hardware_id,
                station_name="",  # Caller fills this in
                started_at=recording.started_at,
                profile_slug=profile_slug,
            )
        )

    return pending
