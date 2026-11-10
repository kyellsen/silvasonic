from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class MicrophoneProfile(Base):
    """Configuration profile for a specific microphone type."""

    __tablename__ = "microphone_profiles"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full Pydantic config dumped as JSON
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Shipped with the software: bootstrapped from the YAML profiles
    built_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
