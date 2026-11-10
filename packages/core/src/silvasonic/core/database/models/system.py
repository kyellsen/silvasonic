import uuid
from datetime import UTC, datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Microphone(Base):
    """Inventory of the microphones the station has seen (ADR-0033)."""

    __tablename__ = "microphones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    # Stable Device ID: USB vendor, product and serial, or the USB port without a serial
    hardware_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Label chosen by the user; the model until then
    name: Mapped[str] = mapped_column(Text, nullable=False)
    serial_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    # connected | disconnected
    connection_state: Mapped[str] = mapped_column(Text, default="disconnected", nullable=False)
    # pending | enrolled | ignored
    enrollment_state: Mapped[str] = mapped_column(Text, default="pending", nullable=False)

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Link to the Microphone Profile
    profile_slug: Mapped[str | None] = mapped_column(
        Text, ForeignKey("microphone_profiles.slug"), nullable=True
    )

    # Facts read from the device (USB IDs, ALSA card), not configuration
    hardware: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Human-readable workspace directory name (e.g. "ultramic-384-evo-034f").
    # Set by the Controller when a profile is assigned (enrollment).
    # Used by the Processor Indexer to resolve microphone_id from filesystem paths.
    workspace_name: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)


class SettingsSection(Base):
    """One section of the station's settings (ADR-0023), e.g. ``storage``.

    ``revision`` starts at 1; a database trigger increments it on every update.
    """

    __tablename__ = "settings"

    section: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class Module(Base):
    """Switch for an optional feature, whichever process implements it (ADR-0029).

    Stores the desired state only. Domain/business settings
    (thresholds, intervals) remain in ``settings`` (ADR-0023).
    """

    __tablename__ = "modules"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class User(Base):
    """Authentication credentials (ADR-0023)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
