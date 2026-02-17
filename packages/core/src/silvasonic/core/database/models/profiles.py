from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class MicrophoneProfile(Base):  # type: ignore[misc]
    """Configuration profile for a specific microphone type."""

    __tablename__ = "microphone_profiles"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full Pydantic config dumped as JSON
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)

    # Flag to indicate if this profile was bootstrapped from system YAMLs
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
