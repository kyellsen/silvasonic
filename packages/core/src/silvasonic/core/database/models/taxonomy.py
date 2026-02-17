from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Taxonomy(Base):
    """Metadata registry for all detection classes (Bio- & Anthropophony).

    Maps raw labels to human-readable info.
    """

    __tablename__ = "taxonomy"

    # Composite Primary Key
    worker: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, primary_key=True)

    scientific_name: Mapped[str] = mapped_column(Text, nullable=False)

    # Localized maps: {"de": "Amsel", "en": "Blackbird"}
    common_names: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Static asset paths
    image_path: Mapped[str] = mapped_column(Text, nullable=True)
    image_source: Mapped[str] = mapped_column(Text, nullable=True)

    # IUCN Red List status (LC, EN, etc.)
    conservation_status: Mapped[str] = mapped_column(Text, nullable=True)
