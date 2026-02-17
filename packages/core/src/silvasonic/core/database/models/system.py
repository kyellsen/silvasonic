from datetime import UTC, datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Device(Base):  # type: ignore[misc]
    """Inventory of hardware devices (microphones)."""

    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    serial_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="offline", nullable=False)
    enrollment_status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)

    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Link to the Microphone Profile
    profile_slug: Mapped[str | None] = mapped_column(
        Text, ForeignKey("microphone_profiles.slug"), nullable=True
    )

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)


class SystemService(Base):  # type: ignore[misc]
    """Registry of dynamic services managed by the Controller."""

    __tablename__ = "system_services"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="stopped", nullable=False)


class SystemConfig(Base):  # type: ignore[misc]
    """Global Key-Value store for application settings."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Upload(Base):  # type: ignore[misc]
    """Immutable audit log of all upload attempts."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    recording_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recordings.id"), nullable=False, index=True
    )

    remote_slug: Mapped[str] = mapped_column(
        Text, ForeignKey("storage_remotes.slug"), nullable=False, index=True
    )

    attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
