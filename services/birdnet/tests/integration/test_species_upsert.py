"""BirdNET registers detected labels as species against a real database (ADR-0033)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from silvasonic.birdnet.species import ensure_species
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.species import Species
from silvasonic.core.database.models.system import Microphone
from silvasonic.core.database.session import get_session
from sqlalchemy import select

BLACKBIRD = "Turdus merula_Eurasian Blackbird"


@pytest.mark.integration
class TestEnsureSpecies:
    """First sighting inserts a minimal row; existing rows are never changed."""

    async def test_inserts_minimal_rows(self, station_db: Path) -> None:
        await check_database_connection()
        async with get_session() as session:
            await ensure_species(session, [BLACKBIRD, "Dog_Dog", BLACKBIRD])
            await session.commit()

        async with get_session() as session:
            rows = {s.id: s for s in (await session.execute(select(Species))).scalars()}

        assert set(rows) == {"turdus-merula", "dog"}
        bird = rows["turdus-merula"]
        assert bird.analyzer == "birdnet"
        assert bird.label == BLACKBIRD
        assert bird.scientific_name == "Turdus merula"
        assert bird.common_names == {"en": "Eurasian Blackbird"}
        assert bird.descriptions == {}
        assert bird.category == "bird"
        assert bird.watched is False
        assert rows["dog"].category == "other"

    async def test_keeps_curated_row(self, station_db: Path) -> None:
        await check_database_connection()
        async with get_session() as session:
            session.add(
                Species(
                    id="turdus-merula",
                    analyzer="birdnet",
                    label=BLACKBIRD,
                    scientific_name="Turdus merula",
                    common_names={"en": "Blackbird", "de": "Amsel"},
                    descriptions={"de": "Häufiger Singvogel"},
                    category="bird",
                    watched=True,
                )
            )
            await session.commit()

        async with get_session() as session:
            await ensure_species(session, [BLACKBIRD])
            await session.commit()

        async with get_session() as session:
            row = await session.get(Species, "turdus-merula")

        assert row is not None
        assert row.common_names == {"en": "Blackbird", "de": "Amsel"}
        assert row.descriptions == {"de": "Häufiger Singvogel"}
        assert row.watched is True

    async def test_detection_references_species(self, station_db: Path) -> None:
        await check_database_connection()
        start = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        async with get_session() as session:
            session.add(MicrophoneProfile(slug="prof", name="prof", config={}))
            mic = Microphone(
                hardware_id="mic-s", name="m", serial_number="s", model="m", profile_slug="prof"
            )
            session.add(mic)
            await session.flush()
            rec = Recording(
                started_at=start,
                microphone_id=mic.id,
                raw_path="mic-s/raw.wav",
                duration_s=10.0,
                sample_rate_hz=48000,
                raw_size_bytes=100,
            )
            session.add(rec)
            await session.flush()

            await ensure_species(session, [BLACKBIRD])
            session.add(
                Detection(
                    started_at=start,
                    ended_at=start + timedelta(seconds=3),
                    recording_id=rec.id,
                    analyzer="birdnet",
                    confidence=0.9,
                    label=BLACKBIRD,
                    species_id="turdus-merula",
                    details={},
                )
            )
            await session.commit()

        async with get_session() as session:
            det = (await session.execute(select(Detection))).scalar_one()
            species = await session.get(Species, det.species_id)

        assert species is not None
        assert species.label == det.label
        assert det.review_state == "unreviewed"
