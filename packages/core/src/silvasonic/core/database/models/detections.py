import uuid
from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from silvasonic.core.database.types import UTCDateTime
from silvasonic.core.ids import uuid7
from sqlalchemy import JSON, Float, ForeignKey, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class Detection(Base):
    """Stores analysis results from various analyzers (BirdNET, BatDetect, etc.)."""

    __tablename__ = "detections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

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

    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Review of the detection: unreviewed, confirmed, rejected
    review_state: Mapped[str] = mapped_column(
        Text, default="unreviewed", server_default=text("'unreviewed'"), nullable=False
    )
    corrected_species_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("species.id"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
