"""Audit logger for Cloud Sync uploads.

Records upload attempts to the immutable `uploads` table and signals the Janitor
by marking `recordings.uploaded = True` upon success.
"""

from __future__ import annotations

import json
from typing import Any

from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Upload
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


async def log_upload_attempt(
    session: AsyncSession,
    recording_id: int,
    filename: str,
    remote_path: str,
    size: int,
    success: bool,
    error_message: str | None,
    duration_s: float,
) -> None:
    """Log an upload attempt to the DB and update recording status on success.

    Args:
        session: Active DB session (will be flushed but NOT committed here).
        recording_id: Origin recording PK.
        filename: Base filename of the uploaded file.
        remote_path: Target path on remote storage.
        size: Bytes transferred or size of the file.
        success: Whether the upload succeeded.
        error_message: Error text if failed.
        duration_s: Time taken for the upload attempt.
    """
    # Create the immutable audit log entry
    # We stuff duration into a structured error_message/metadata field since
    # we don't have a dedicated duration_s column to keep the schema simple (KISS).
    meta: dict[str, Any] = {"duration_s": round(duration_s, 2)}
    if error_message:
        meta["error"] = error_message

    upload_record = Upload(
        recording_id=recording_id,
        filename=filename,
        remote_path=remote_path,
        size=size,
        success=success,
        error_message=json.dumps(meta),
    )
    session.add(upload_record)

    # If successful, mark the recording as uploaded so Janitor can delete it later
    if success:
        from datetime import UTC, datetime

        stmt = (
            update(Recording)
            .where(Recording.id == recording_id)
            .values(uploaded=True, uploaded_at=datetime.now(UTC))
        )
        await session.execute(stmt)
