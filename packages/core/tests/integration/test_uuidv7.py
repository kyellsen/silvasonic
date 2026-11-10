"""Integration tests for the ``uuidv7()`` polyfill and UUIDv7 defaults (ADR-0033).

Runs against the real init schema (``services/database/init/``) through the
shared ``postgres_container`` fixture.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.recordings import Recording, Upload
from silvasonic.core.database.models.species import Species
from silvasonic.core.database.models.system import Microphone, User
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


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
    postgres_container: PostgresContainer,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory bound to the shared test database."""
    engine = create_async_engine(build_postgres_url(postgres_container))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.integration
class TestUuidv7Function:
    """``SELECT uuidv7()`` returns RFC 9562 UUIDv7 values."""

    async def test_version_variant_and_timestamp(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """The value is v7 and its timestamp is the database's current time."""
        async with session_factory() as session:
            row = (await session.execute(text("SELECT uuidv7(), now()"))).one()
        value, now = row[0], row[1]
        assert isinstance(value, uuid.UUID)
        _assert_v7(value)
        stamped = datetime.fromtimestamp(_unix_ms(value) / 1000, tz=UTC)
        assert abs(stamped - now) < timedelta(seconds=5)

    async def test_ids_sort_by_creation_time(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """IDs generated a few milliseconds apart sort in generation order."""
        ids: list[uuid.UUID] = []
        async with session_factory() as session:
            for _ in range(5):
                ids.append((await session.execute(text("SELECT uuidv7()"))).scalar_one())
                await session.execute(text("SELECT pg_sleep(0.005)"))
        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)
        assert [_unix_ms(i) for i in ids] == sorted(_unix_ms(i) for i in ids)
        for value in ids:
            _assert_v7(value)

    async def test_values_are_unique(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Many IDs in the same millisecond do not collide (74 random bits)."""
        async with session_factory() as session:
            result = await session.execute(text("SELECT uuidv7() FROM generate_series(1, 1000)"))
            ids = list(result.scalars())
        assert len(set(ids)) == 1000


@pytest.mark.integration
class TestUuidv7Defaults:
    """Runtime rows get a UUIDv7 ``id`` from the database by default."""

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
