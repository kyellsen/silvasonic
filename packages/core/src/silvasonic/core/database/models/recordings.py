from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


class Recording(Base):  # type: ignore[misc]
    """Registry of all audio files recorded by the system.

    Designed to be a TimescaleDB hypertable partitioned by `time`.
    """

    __tablename__ = "recordings"

    # Standard PostgreSQL Table (Not a Hypertable)
    # This allows it to be referenced by Foreign Keys from other tables (like detections, uploads)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Time is still indexed but not part of PK
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Microphone Identifier. References devices.name (lazy string ref to avoid circular imports if needed)
    # Using String for simplicity in foreign key, assuming devices.name is the PK
    sensor_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.name"), nullable=False, index=True
    )

    file_raw: Mapped[str] = mapped_column(String, nullable=False)
    file_processed: Mapped[str] = mapped_column(String, nullable=False)

    duration: Mapped[float] = mapped_column(Float, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)

    filesize_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filesize_processed: Mapped[int] = mapped_column(BigInteger, nullable=False)

    uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Analysis status map
    analysis_state: Mapped[dict[str, Any]] = mapped_column(JSON, default={}, nullable=False)
