import uuid
from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import DateTime, Float, ForeignKey, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Detection(Base):
    """Stores analysis results from various analyzers (BirdNET, BatDetect, etc.).

    Designed to be a TimescaleDB hypertable partitioned by `started_at`.
    """

    __tablename__ = "detections"

    # TimescaleDB requires the partition key to be part of the Primary Key,
    # so the PK is (started_at, id); a plain index on id addresses a detection alone.
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("uuidv7()"), index=True
    )

    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Foreign Key to Recordings (Standard Table)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recordings.id"), nullable=False, index=True
    )

    analyzer: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # The label as the analyzer reported it; species_id is what it means
    label: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    species_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("species.id"), nullable=True, index=True
    )
    clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Review of the detection: unreviewed, confirmed, rejected
    review_state: Mapped[str] = mapped_column(
        Text, default="unreviewed", server_default=text("'unreviewed'"), nullable=False
    )
    corrected_species_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("species.id"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
