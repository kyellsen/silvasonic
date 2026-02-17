from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Detection(Base):
    """Stores analysis results from various workers (BirdNET, BatDetect, etc.).

    Designed to be a TimescaleDB hypertable partitioned by `time`.
    """

    __tablename__ = "detections"

    # TimescaleDB requires the partition key to be part of the Primary Key
    # So we use a composite PK: (time, id)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Foreign Key to Recordings (Standard Table)
    recording_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recordings.id"), nullable=False, index=True
    )

    worker: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    common_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)
