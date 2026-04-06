"""Shared fixtures for BirdNET integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import asyncpg  # type: ignore[import-untyped]
import pytest
from silvasonic.test_utils.containers import postgres_container as postgres_container
from testcontainers.postgres import PostgresContainer

# Tables deleted in FK-safe order.
_CLEANUP_TABLES = (
    "detections",
    "recordings",
    "devices",
    "microphone_profiles",
    "system_config",
    "managed_services",
)


async def _delete_all(container: PostgresContainer) -> None:
    """Connect via asyncpg and DELETE all application rows."""
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(5432))
    conn = await asyncpg.connect(
        host=host, port=port, user="silvasonic", password="silvasonic", database="silvasonic_test"
    )
    try:
        for table in _CLEANUP_TABLES:
            await conn.execute(f"DELETE FROM {table}")
    finally:
        await conn.close()


@pytest.fixture(autouse=True, scope="session")
def setup_test_engine(postgres_container: PostgresContainer) -> Iterator[None]:
    """Inject testcontainer database into the engine singleton for all tests."""
    import os

    # Still patch environ in case any code reads directly from DatabaseSettings
    os.environ["SILVASONIC_DB_HOST"] = str(postgres_container.get_container_host_ip())
    os.environ["SILVASONIC_DB_PORT"] = str(postgres_container.get_exposed_port(5432))
    os.environ["SILVASONIC_DB_USER"] = str(postgres_container.username)
    os.environ["SILVASONIC_DB_PASS"] = str(postgres_container.password)
    os.environ["SILVASONIC_DB_NAME"] = str(postgres_container.dbname)

    from silvasonic.core.database.session import override_engine, reset_engine
    from silvasonic.test_utils.helpers import build_postgres_url
    from sqlalchemy.ext.asyncio import create_async_engine

    url = build_postgres_url(postgres_container)
    engine = create_async_engine(url, future=True)
    override_engine(engine)

    yield

    reset_engine()
    # Note: no need to dispose engine here as pytest will tear down anyway.


@pytest.fixture(autouse=True)
def _clean_db_tables(
    postgres_container: PostgresContainer, setup_test_engine: None
) -> Iterator[None]:
    """Reset application tables after each test."""
    yield
    asyncio.get_event_loop().run_until_complete(_delete_all(postgres_container))
