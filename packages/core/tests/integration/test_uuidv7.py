"""Integration tests for UUIDv7 identifiers (ADR-0033) on SQLite (ADR-0037).

The ORM generates ids in Python; the schema's column default builds an
equivalent one for raw SQL. Runs through the shared ``station_db`` fixture.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.recordings import Recording, Upload
from silvasonic.core.database.models.species import Species
from silvasonic.core.database.models.system import Microphone, User
from silvasonic.core.database.session import create_station_engine
from silvasonic.core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _unix_ms(value: uuid.UUID) -> int:
    """The 48-bit Unix millisecond timestamp in the first six bytes."""
    return int.from_bytes(value.bytes[:6], "big")


def _assert_v7(value: uuid.UUID) -> None:
    """Version nibble 7 and RFC 9562 variant bits ``10``."""
    assert value.version == 7, value
    assert value.bytes[6] >> 4 == 7
    assert value.bytes[8] >> 6 == 0b10
    assert value.variant == uuid.RFC_4122


@pytest.fixture
async def session_factory(
    station_db: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory bound to the shared test database."""
    engine = create_station_engine(station_db)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _raw_microphone_id(session: AsyncSession) -> uuid.UUID:
    """Insert a microphone with raw SQL and no id; return the id the default chose."""
    suffix = uuid.uuid4().hex
    row = (
        await session.execute(
            text(
                "INSERT INTO microphones (hardware_id, name, serial_number, model, hardware) "
                "VALUES (:hw, 'Raw', :sn, 'Raw', '{}') RETURNING id"
            ),
            {"hw": f"hw-raw-{suffix}", "sn": f"sn-raw-{suffix}"},
        )
    ).one()
    return uuid.UUID(row[0])


@pytest.mark.integration
class TestUuidv7Generation:
    """IDs are RFC 9562 UUIDv7 whether the ORM or the SQL default makes them."""

    def test_application_generator(self) -> None:
        """``uuid7()`` returns v7 values stamped with the current time, in order."""
        before = datetime.now(UTC)
        ids = [uuid7() for _ in range(1000)]
        for value in ids:
            _assert_v7(value)
        assert len(set(ids)) == 1000
        assert ids == sorted(ids), "generated in one process, they sort by creation"
        stamped = datetime.fromtimestamp(_unix_ms(ids[0]) / 1000, tz=UTC)
        assert abs(stamped - before) < timedelta(seconds=5)

    async def test_sql_default_version_variant_and_timestamp(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Raw SQL that leaves ``id`` out gets a v7 stamped with the current time."""
        before = datetime.now(UTC)
        async with session_factory() as session:
            value = await _raw_microphone_id(session)
            await session.commit()
        _assert_v7(value)
        stamped = datetime.fromtimestamp(_unix_ms(value) / 1000, tz=UTC)
        assert abs(stamped - before) < timedelta(seconds=5)

    async def test_sql_default_sorts_by_time_and_is_unique(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Defaults a few milliseconds apart sort in order; many never collide."""
        spaced: list[uuid.UUID] = []
        async with session_factory() as session:
            for _ in range(5):
                spaced.append(await _raw_microphone_id(session))
                await asyncio.sleep(0.005)
            burst = [await _raw_microphone_id(session) for _ in range(300)]
            await session.commit()
        assert [_unix_ms(i) for i in spaced] == sorted(_unix_ms(i) for i in spaced)
        assert len(set(burst)) == len(burst)


@pytest.mark.integration
class TestUuidv7Defaults:
    """Runtime rows get a UUIDv7 ``id`` by default (ADR-0033)."""

    async def test_rows_get_uuidv7_ids(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Microphones, users, recordings, detections and uploads."""
        suffix = uuid.uuid4().hex[:8]
        now = datetime.now(UTC)
        async with session_factory() as session:
            mic = Microphone(
                hardware_id=f"hw-uuid-{suffix}",
                name="Test Mic",
                serial_number=f"sn-uuid-{suffix}",
                model="Test Mic",
                hardware={},
            )
            user = User(username=f"user-{suffix}", password_hash="x")
            session.add_all([mic, user])
            await session.flush()

            recording = Recording(
                started_at=now,
                microphone_id=mic.id,
                raw_path=f"raw/{suffix}.wav",
                duration_s=10.0,
                sample_rate_hz=384000,
                raw_size_bytes=1,
            )
            session.add(recording)
            await session.flush()

            species = Species(
                id=f"testus-{suffix}",
                analyzer="birdnet",
                label=f"Testus {suffix}_Test bird",
                scientific_name=f"Testus {suffix}",
                common_names={"en": "Test bird"},
                descriptions={},
            )
            session.add(species)
            await session.flush()

            detection = Detection(
                started_at=now,
                ended_at=now + timedelta(seconds=3),
                recording_id=recording.id,
                analyzer="birdnet",
                confidence=0.9,
                label=species.label,
                species_id=species.id,
                details={},
            )
            upload = Upload(
                recording_id=recording.id,
                filename=f"{suffix}.flac",
                size_bytes=1,
                success=True,
            )
            session.add_all([detection, upload])
            await session.flush()
            await session.refresh(detection)
            await session.refresh(recording)

            for value in (mic.id, user.id, recording.id, detection.id, upload.id):
                assert isinstance(value, uuid.UUID)
                _assert_v7(value)

            # Server defaults of the new columns
            assert recording.clock_synced is True
            assert recording.channels == 1
            assert recording.deleted_at is None
            assert recording.analysis_state == {}
            assert detection.review_state == "unreviewed"

            # A detection is addressable by id alone
            found = await session.execute(
                text("SELECT label FROM detections WHERE id = :id"), {"id": detection.id}
            )
            assert found.scalar_one() == species.label
            await session.rollback()
