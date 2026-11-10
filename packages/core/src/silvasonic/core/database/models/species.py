from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import JSON, Boolean, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column


class Species(Base):
    """Metadata registry for all detection classes (Bio- & Anthropophony).

    ``id`` is a slug of the scientific name (ADR-0033); ``(analyzer, label)``
    is how an analyzer reports the class.
    """

    __tablename__ = "species"
    __table_args__ = (UniqueConstraint("analyzer", "label"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)

    analyzer: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)

    scientific_name: Mapped[str] = mapped_column(Text, nullable=False)

    # Localized maps: {"de": "Amsel", "en": "Blackbird"}
    common_names: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Plain text by language, never HTML from outside
    descriptions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Per language: {"url": ..., "license": ..., "license_url": ...} of that text
    description_sources: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'"), nullable=False
    )

    # bird, bat, mammal, amphibian, insect, human, environment, other
    category: Mapped[str] = mapped_column(
        Text, default="other", server_default=text("'other'"), nullable=False
    )
    watched: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )

    # Picture, relative to the analyzer's workspace, and its attribution:
    # source page, author and licence as the licence asks them to be shown
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_license: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_license_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # IUCN Red List status (LC, EN, etc.)
    conservation_status: Mapped[str | None] = mapped_column(Text, nullable=True)
