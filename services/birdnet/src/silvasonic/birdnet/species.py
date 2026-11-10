"""Register BirdNET labels as species (ADR-0033).

BirdNET reports a class as ``"<scientific name>_<common name>"``. Nothing else
fills the ``species`` table yet, so the first time a label is detected a
minimal row is inserted; existing rows (curated names, descriptions, the
``watched`` flag) are never touched.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from silvasonic.core.database.models.species import Species
from silvasonic.core.database.session import get_session
from silvasonic.core.schemas.species import SpeciesCategory, species_id
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

ANALYZER = "birdnet"


def split_label(label: str) -> tuple[str, str]:
    """Split a BirdNET label into scientific and common name (``""`` if absent)."""
    parts = label.split("_")
    return parts[0], parts[1] if len(parts) > 1 else ""


def label_category(label: str) -> SpeciesCategory:
    """``bird``, or ``other`` for a non-species sound class such as ``Dog_Dog``.

    BirdNET names such classes with two identical halves; a label without a
    common name is treated the same way.
    """
    scientific, common = split_label(label)
    return "bird" if common and common != scientific else "other"


def label_species_id(label: str) -> str:
    """The ``species.id`` a BirdNET label stands for."""
    return species_id(split_label(label)[0])


def species_row(label: str) -> dict[str, Any]:
    """Build the minimal ``species`` row for a BirdNET label."""
    scientific, common = split_label(label)
    return {
        "id": label_species_id(label),
        "analyzer": ANALYZER,
        "label": label,
        "scientific_name": scientific,
        "common_names": {"en": common} if common else {},
        "descriptions": {},
        "category": label_category(label),
    }


async def ensure_species(session: AsyncSession, labels: Iterable[str]) -> None:
    """Insert a ``species`` row for each label not yet known (ON CONFLICT DO NOTHING)."""
    rows = [species_row(label) for label in sorted(set(labels))]
    if rows:
        await session.execute(insert(Species).values(rows).on_conflict_do_nothing())


async def register_species(labels: Iterable[str]) -> None:
    """Run :func:`ensure_species` in a short transaction of its own.

    Kept apart from the detection insert: the species rows are committed
    before the detections that reference them, and each transaction stays
    short (ADR-0037).
    """
    async with get_session() as session:
        await ensure_species(session, labels)
        await session.commit()
