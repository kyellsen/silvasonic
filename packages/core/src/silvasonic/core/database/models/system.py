from datetime import UTC, datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Device(Base):
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

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Human-readable workspace directory name (e.g. "ultramic-384-evo-034f").
    # Set by the Controller when a profile is assigned (enrollment).
    # Used by the Processor Indexer to resolve sensor_id from filesystem paths.
    workspace_name: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)


class SystemConfig(Base):
    """Global Key-Value store for application settings (ADR-0023)."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class ManagedService(Base):
    """Registry for Tier-2 containers managed by the Controller (ADR-0029).

    Stores lifecycle orchestration toggles only. Domain/business settings
    (thresholds, intervals) remain in ``system_config`` (ADR-0023).
    """

    __tablename__ = "managed_services"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class User(Base):
    """Authentication credentials (ADR-0023)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
