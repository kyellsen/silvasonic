from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from silvasonic.core.database.types import UTCDateTime
from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column


class Detection(Base):
    """Stores analysis results from various workers (BirdNET, BatDetect, etc.)."""

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    recording_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recordings.id"), nullable=False, index=True
    )

    worker: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    common_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
