"""Shared fixtures for Controller integration tests.

Provides an autouse cleanup fixture that resets DB state after each
test, ensuring parallel-safe execution with ``pytest-xdist``.

With ``-n 4`` each xdist worker gets its **own** session-scoped
``postgres_container``.  Tests on the same worker share that DB and
run sequentially.  The autouse fixture guarantees a clean slate
between tests so that leftover rows never cause false positives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from silvasonic.test_utils.helpers import clean_database
from testcontainers.postgres import PostgresContainer


@pytest.fixture(autouse=True)
async def _clean_db_tables(postgres_container: PostgresContainer) -> AsyncIterator[None]:
    """Reset application tables after each test for parallel safety.

    Runs **after** every integration test in this directory.  Truncates
    all user application tables dynamically so that tests running on the
    same xdist worker with a shared session-scoped database cannot
    interfere with each other.
    """
    import os

    from silvasonic.core.database.session import override_engine, reset_engine
    from silvasonic.test_utils.helpers import build_postgres_url
    from sqlalchemy.ext.asyncio import create_async_engine

    # Set env vars for legacy code
    os.environ["SILVASONIC_DB_HOST"] = postgres_container.get_container_host_ip()
    os.environ["SILVASONIC_DB_PORT"] = str(postgres_container.get_exposed_port(5432))
    os.environ["SILVASONIC_DB_USER"] = "silvasonic"
    os.environ["SILVASONIC_DB_PASS"] = "silvasonic"
    os.environ["SILVASONIC_DB_NAME"] = "silvasonic_test"

    # Override engine globally for all code running in this test worker
    engine = create_async_engine(build_postgres_url(postgres_container))
    override_engine(engine)

    try:
        yield
    finally:
        reset_engine()
        await engine.dispose()
        await clean_database(postgres_container)
