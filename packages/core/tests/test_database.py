"""Integration tests for silvasonic-core database connectivity.

Uses Testcontainers to spin up a real TimescaleDB instance.
Requires Docker/Podman to be available on the host.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.mark.integration
class TestDatabaseConnectivity:
    """Verify that core can connect to a real TimescaleDB instance."""

    def test_database_connection(self) -> None:
        """Connect to a Testcontainers Postgres instance and execute a query."""
        with PostgresContainer(
            image="timescale/timescaledb:2.19.3-pg17",
            username="silvasonic",
            password="silvasonic",
            dbname="silvasonic",
        ) as pg:
            # Build async connection URL
            host = pg.get_container_host_ip()
            port = pg.get_exposed_port(5432)
            url = f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic"

            import asyncio

            async def _check() -> str:
                engine = create_async_engine(url)
                async_session = async_sessionmaker(engine, class_=AsyncSession)
                async with async_session() as session:
                    result = await session.execute(text("SELECT version()"))
                    version = result.scalar_one()
                await engine.dispose()
                return str(version)

            version = asyncio.run(_check())
            assert "PostgreSQL" in version
