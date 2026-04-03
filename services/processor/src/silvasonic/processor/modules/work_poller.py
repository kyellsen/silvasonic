"""Work poller for discovering pending uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device, Upload
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PendingUpload:
    """A recording that needs to be uploaded."""

    recording_id: int
    file_raw: Path
    sensor_id: str
    station_name: str
    time: datetime
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
            relative ``file_raw`` column to produce absolute paths.
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
        select(Recording, Device.name, Device.profile_slug)
        .join(Device, Recording.sensor_id == Device.name)
        .outerjoin(failed_attempts, Recording.id == failed_attempts.c.recording_id)
        .where(Recording.uploaded.is_(False))
        .where(Recording.local_deleted.is_(False))
        .where(
            # Include recordings that have never been tried (NULL)
            # or have fewer than max_retries failed attempts
            (failed_attempts.c.attempt_count.is_(None))
            | (failed_attempts.c.attempt_count < max_retries)
        )
        .order_by(Recording.time.asc())
        .limit(batch_size)
    )

    result = await session.execute(stmt)
    rows = result.all()

    pending = []
    for recording, device_name, profile_slug in rows:
        pending.append(
            PendingUpload(
                recording_id=recording.id,
                file_raw=recordings_dir / recording.file_raw,
                sensor_id=device_name,
                station_name="",  # Caller fills this in
                time=recording.time,
                profile_slug=profile_slug,
            )
        )

    return pending
