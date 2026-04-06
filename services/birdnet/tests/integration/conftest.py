"""Shared fixtures for BirdNET integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from silvasonic.test_utils.containers import postgres_container as postgres_container
from silvasonic.test_utils.helpers import clean_database
from testcontainers.postgres import PostgresContainer


@pytest.fixture(autouse=True)
async def _clean_db_tables(postgres_container: PostgresContainer) -> AsyncIterator[None]:
    """Reset application tables after each test for parallel safety.

    Runs **after** every integration test in this directory. Truncates
    all user application tables dynamically so that tests running on the
    same xdist worker with a shared session-scoped database cannot
    interfere with each other.
    """
    import os

    from silvasonic.core.database.session import override_engine, reset_engine
    from silvasonic.test_utils.helpers import build_postgres_url
    from sqlalchemy.ext.asyncio import create_async_engine

    # Set env vars for database settings
    os.environ["SILVASONIC_DB_HOST"] = postgres_container.get_container_host_ip()
    os.environ["SILVASONIC_DB_PORT"] = str(postgres_container.get_exposed_port(5432))
    os.environ["POSTGRES_USER"] = postgres_container.username
    os.environ["POSTGRES_PASSWORD"] = postgres_container.password
    os.environ["POSTGRES_DB"] = postgres_container.dbname

    # Override engine globally for all code running in this test worker
    engine = create_async_engine(build_postgres_url(postgres_container))
    override_engine(engine)

    try:
        await clean_database(postgres_container)
        yield
    finally:
        reset_engine()
        await engine.dispose()
        await clean_database(postgres_container)
