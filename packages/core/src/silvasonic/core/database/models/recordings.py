from datetime import UTC, datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from silvasonic.core.database.types import UTCDateTime
from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column


class Recording(Base):
    """Registry of all audio files recorded by the system.

    Referenced by ``detections`` and ``uploads`` (ADR-0025).
    """

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)

    # Microphone Identifier. References devices.name
    # (lazy string ref to avoid circular imports if needed)
    # Using String for simplicity in foreign key, assuming devices.name is the PK
    sensor_id: Mapped[str] = mapped_column(
        Text, ForeignKey("devices.name"), nullable=False, index=True
    )

    file_raw: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_processed: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    duration: Mapped[float] = mapped_column(Float, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)

    filesize_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filesize_processed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    # Soft Delete: Marked True if file is removed from local disk by Janitor
    local_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Analysis status map — Worker Pull (ADR-0018)
    analysis_state: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )

    # Named while the system clock was unsynchronised: ``time`` may be off (Issue 002)
    clock_unsynced: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )


class Upload(Base):
    """Immutable audit log of all upload attempts."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    recording_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recordings.id"), nullable=False, index=True
    )

    attempt_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    remote_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
