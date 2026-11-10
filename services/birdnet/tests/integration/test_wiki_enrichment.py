"""Wikipedia enrichment of a species row against a real station database."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.birdnet import wiki_enricher
from silvasonic.birdnet.species import ensure_species
from silvasonic.birdnet.wiki_enricher import TEXT_LICENSE, ImageAttribution, enrich_if_needed
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.species import Species
from silvasonic.core.database.session import get_session

BLACKBIRD = "Turdus merula_Eurasian Blackbird"
IMAGE_URL = "https://upload.wikimedia.org/wikipedia/commons/a/a9/Blackbird.jpg"
ATTRIBUTION = ImageAttribution(
    author="Andreas Trepte",
    license="CC BY-SA 2.5",
    license_url="https://creativecommons.org/licenses/by-sa/2.5",
    page_url="https://commons.wikimedia.org/wiki/File:Blackbird.jpg",
)


async def _fake_fetch(_name: str, lang: str) -> dict[str, Any]:
    return {
        "extract": f"Blackbird ({lang}).",
        "thumbnail_url": None,
        "original_image_url": IMAGE_URL,
        "wiki_page_url": f"https://{lang}.wikipedia.org/wiki/Blackbird",
        "short_description": "",
    }


async def _fake_download(_url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\xff\xd8fake-jpeg")
    return True


@pytest.mark.integration
async def test_enrichment_is_stored_and_then_served_from_the_row(
    station_db: Path, tmp_path: Path
) -> None:
    """The first lookup fills the registered species row; the second needs no network."""
    await check_database_connection()
    wiki_enricher._next_attempt.clear()

    async with get_session() as session:
        await ensure_species(session, [BLACKBIRD])
        await session.commit()

    fetch = AsyncMock(side_effect=_fake_fetch)
    with (
        patch("silvasonic.birdnet.wiki_enricher.fetch_wiki_summary", new=fetch),
        patch(
            "silvasonic.birdnet.wiki_enricher.fetch_commons_attribution",
            new=AsyncMock(return_value=ATTRIBUTION),
        ),
        patch("silvasonic.birdnet.wiki_enricher._download_image", new=_fake_download),
        patch("silvasonic.birdnet.wiki_enricher.asyncio.sleep", new=AsyncMock()),
    ):
        first = await enrich_if_needed(BLACKBIRD, tmp_path)
        second = await enrich_if_needed(BLACKBIRD, tmp_path)

    assert fetch.await_count == 2  # EN + DE, once
    assert first.image_path == second.image_path == "wiki/img/turdus-merula.jpg"
    assert (tmp_path / "wiki" / "img" / "turdus-merula.jpg").exists()

    async with get_session() as session:
        row = await session.get(Species, "turdus-merula")

    assert row is not None
    assert row.descriptions == {"en": "Blackbird (en).", "de": "Blackbird (de)."}
    assert row.description_sources["en"]["url"] == "https://en.wikipedia.org/wiki/Blackbird"
    assert row.description_sources["en"]["license"] == TEXT_LICENSE
    assert row.image_path == "wiki/img/turdus-merula.jpg"
    assert row.image_source == ATTRIBUTION.page_url
    assert row.image_author == "Andreas Trepte"
    assert row.image_license == "CC BY-SA 2.5"
    assert row.image_license_url == "https://creativecommons.org/licenses/by-sa/2.5"
    # What BirdNET registered is untouched
    assert row.common_names == {"en": "Eurasian Blackbird"}
    assert row.category == "bird"


@pytest.mark.integration
async def test_label_without_a_species_row_is_left_alone(station_db: Path, tmp_path: Path) -> None:
    """Enrichment never creates a species row and asks nothing without one."""
    await check_database_connection()
    wiki_enricher._next_attempt.clear()

    fetch = AsyncMock(side_effect=_fake_fetch)
    with patch("silvasonic.birdnet.wiki_enricher.fetch_wiki_summary", new=fetch):
        await enrich_if_needed(BLACKBIRD, tmp_path)

    fetch.assert_not_awaited()
    async with get_session() as session:
        assert await session.get(Species, "turdus-merula") is None
