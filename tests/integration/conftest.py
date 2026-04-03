"""Shared fixtures for cross-cutting integration tests.

Re-exports session-scoped container fixtures from ``silvasonic-test-utils``
and provides an autouse DB cleanup fixture for parallel-safe execution
with ``pytest-xdist``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import asyncpg  # type: ignore[import-untyped]
import pytest
from silvasonic.test_utils.containers import postgres_container as postgres_container
from silvasonic.test_utils.containers import redis_container as redis_container
from silvasonic.test_utils.containers import shared_network as shared_network
from testcontainers.postgres import PostgresContainer

# Tables deleted in FK-safe order (children before parents).
_CLEANUP_TABLES = (
    "recordings",
    "devices",
    "microphone_profiles",
    "users",
    "system_config",
)


async def _delete_all(container: PostgresContainer) -> None:
    """Connect via asyncpg and DELETE all application rows."""
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(5432))
    conn = await asyncpg.connect(
        host=host,
        port=port,
        user="silvasonic",
        password="silvasonic",
        database="silvasonic_test",
    )
    try:
        for table in _CLEANUP_TABLES:
            await conn.execute(f"DELETE FROM {table}")
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def _clean_db_tables(postgres_container: PostgresContainer) -> Iterator[None]:
    """Reset application tables after each test for parallel safety.

    Runs **after** every integration test in this directory.  Deletes
    rows from all known application tables in FK-safe order so that
    tests running on the same xdist worker with a shared session-scoped
    database cannot interfere with each other.
    """
    yield
    asyncio.get_event_loop().run_until_complete(_delete_all(postgres_container))
