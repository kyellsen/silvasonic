"""Work poller for discovering pending uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PendingUpload:
    """A recording that needs to be uploaded."""

    recording_id: int
    file_raw: Path
    sensor_id: str
    station_name: str
    time: datetime


async def find_pending_uploads(
    session: AsyncSession,
    recordings_dir: Path,
    batch_size: int = 50,
) -> list[PendingUpload]:
    """Find recordings that haven't been uploaded and haven't been deleted.

    Args:
        session: Active database session.
        recordings_dir: Root of the Recorder workspace.  Prepended to the
            relative ``file_raw`` column to produce absolute paths.
        batch_size: Max number of recordings to return.

    Returns:
        A list of PendingUpload objects representing recordings to upload.
    """
    stmt = (
        select(Recording, Device.name)
        .join(Device, Recording.sensor_id == Device.name)
        .where(Recording.uploaded.is_(False))
        .where(Recording.local_deleted.is_(False))
        .order_by(Recording.time.asc())
        .limit(batch_size)
    )

    result = await session.execute(stmt)
    rows = result.all()

    pending = []
    for recording, device_name in rows:
        pending.append(
            PendingUpload(
                recording_id=recording.id,
                file_raw=recordings_dir / recording.file_raw,
                sensor_id=device_name,
                station_name="",  # Caller fills this in
                time=recording.time,
            )
        )

    return pending
