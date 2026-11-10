"""Integration tests for the station database (SQLite, ADR-0037).

Uses the shared ``station_db`` fixture from ``silvasonic-test-utils``: a
database file per test process, created by its first connection.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from silvasonic.core.database.schema import SCHEMA_VERSION, SchemaVersionError
from silvasonic.core.database.session import create_station_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.mark.integration
class TestStationDatabase:
    """Every connection gets the schema and the same pragmas."""

    async def test_first_connection_creates_schema(self, tmp_path: Path) -> None:
        """A new file holds every table and the current schema version."""
        engine = create_station_engine(tmp_path / "new.db")
        async with engine.connect() as conn:
            version = (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one()
            tables = {
                row[0]
                for row in await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        await engine.dispose()

        assert version == SCHEMA_VERSION
        assert {"recordings", "detections", "microphones", "settings", "uploads"} <= tables

    async def test_concurrent_first_connections_create_schema_once(self, tmp_path: Path) -> None:
        """Services starting at the same time do not race on CREATE TABLE."""
        path = tmp_path / "race.db"
        engines = [create_station_engine(path) for _ in range(4)]

        async def touch(engine: AsyncEngine) -> int:
            async with engine.connect() as conn:
                return int((await conn.exec_driver_sql("PRAGMA user_version")).scalar_one())

        versions = await asyncio.gather(*(touch(e) for e in engines))
        for engine in engines:
            await engine.dispose()

        assert versions == [SCHEMA_VERSION] * 4

    async def test_pragmas_on_every_connection(self, station_db: Path) -> None:
        """WAL, foreign keys and the busy timeout are set per connection."""
        engine = create_station_engine(station_db)
        async with engine.connect() as conn:
            journal = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            foreign_keys = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
            busy_timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        await engine.dispose()

        assert journal == "wal"
        assert foreign_keys == 1
        assert busy_timeout > 0

    async def test_foreign_keys_enforced(self, station_db: Path) -> None:
        """A recording must reference an existing microphone."""
        engine = create_station_engine(station_db)
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.exec_driver_sql(
                    "INSERT INTO recordings (started_at, microphone_id, raw_path, duration_s, "
                    "sample_rate_hz, raw_size_bytes) "
                    "VALUES (0, 'no-such-microphone', 'a.wav', 1, 1, 1)"
                )
        await engine.dispose()

    async def test_strict_tables_reject_wrong_types(self, station_db: Path) -> None:
        """A STRICT table refuses a value that cannot become its column type."""
        engine = create_station_engine(station_db)
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.exec_driver_sql(
                    "INSERT INTO modules (id, enabled, updated_at) VALUES ('x', 1, 'yesterday')"
                )
        await engine.dispose()

    async def test_unknown_schema_version_is_refused(self, tmp_path: Path) -> None:
        """A file from another schema version stops the service instead of being used."""
        path = tmp_path / "future.db"
        engine = create_station_engine(path)
        async with engine.begin() as conn:  # user_version is transactional
            await conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        await engine.dispose()

        engine = create_station_engine(path)
        with pytest.raises((SchemaVersionError, OperationalError)):
            async with engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
        await engine.dispose()


@pytest.mark.integration
class TestCheckDatabaseConnection:
    """Verify ``check_database_connection()`` against a real station database.

    This is the cross-package integration test that was previously missing:
    Controller calls ``check_database_connection()`` (from ``core.database.check``)
    which internally uses ``get_session()`` → ``AsyncSessionLocal`` → real DB.

    We patch the session module's engine + session factory to point at the
    test database instead of the default (env-based) file.
    """

    async def test_check_returns_true_on_live_db(self, station_db: Path) -> None:
        """check_database_connection() returns True against a reachable database."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        with patch(
            "silvasonic.core.database.session._get_session_factory",
            return_value=session_factory,
        ):
            from silvasonic.core.database.check import check_database_connection

            result = await check_database_connection()

        await engine.dispose()
        assert result is True

    async def test_check_returns_false_on_dead_db(self) -> None:
        """check_database_connection() returns False when the DB is unreachable."""
        # A directory that does not exist: SQLite cannot create the file
        bad_engine = create_async_engine("sqlite+aiosqlite:////nonexistent/dir/gone.db")
        bad_session = async_sessionmaker(bad_engine, class_=AsyncSession, expire_on_commit=False)

        with patch(
            "silvasonic.core.database.session._get_session_factory",
            return_value=bad_session,
        ):
            from silvasonic.core.database.check import check_database_connection

            result = await check_database_connection()

        await bad_engine.dispose()
        assert result is False
