"""Integration tests for silvasonic-core database connectivity.

Uses the shared ``postgres_container`` fixture from ``silvasonic-test-utils``
(via root ``conftest.py``) to spin up a real TimescaleDB instance with the
Silvasonic schema already applied.

Requires Podman to be available on the host. The container is started once
per session and shared with all other integration tests that declare the
``postgres_container`` fixture.
"""

from unittest.mock import patch

import pytest
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.mark.integration
class TestDatabaseConnectivity:
    """Verify that core can connect to a real TimescaleDB instance."""

    async def test_database_connection(self, postgres_container: PostgresContainer) -> None:
        """Connect to the shared Testcontainers Postgres instance and execute a query."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        async_session = async_sessionmaker(engine, class_=AsyncSession)

        async with async_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()

        await engine.dispose()

        assert "PostgreSQL" in str(version)

    async def test_timescaledb_extension_active(
        self, postgres_container: PostgresContainer
    ) -> None:
        """Verify that the TimescaleDB extension is loaded (confirms init SQL ran)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        async_session = async_sessionmaker(engine, class_=AsyncSession)

        async with async_session() as session:
            result = await session.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
            )
            ext = result.scalar_one_or_none()

        await engine.dispose()

        assert ext == "timescaledb", "TimescaleDB extension was not initialised by init SQL"


@pytest.mark.integration
class TestCheckDatabaseConnection:
    """Verify ``check_database_connection()`` against a real TimescaleDB instance.

    This is the cross-package integration test that was previously missing:
    Controller calls ``check_database_connection()`` (from ``core.database.check``)
    which internally uses ``get_session()`` → ``AsyncSessionLocal`` → real DB.

    We patch the session module's engine + session factory to point at the
    Testcontainer instead of the default (env-based) connection URL.
    """

    async def test_check_returns_true_on_live_db(
        self, postgres_container: PostgresContainer
    ) -> None:
        """check_database_connection() returns True against a running Postgres."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
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
        bad_engine = create_async_engine("postgresql+asyncpg://bad:bad@localhost:1/gone")
        bad_session = async_sessionmaker(bad_engine, class_=AsyncSession, expire_on_commit=False)

        with patch(
            "silvasonic.core.database.session._get_session_factory",
            return_value=bad_session,
        ):
            from silvasonic.core.database.check import check_database_connection

            result = await check_database_connection()

        await bad_engine.dispose()
        assert result is False
