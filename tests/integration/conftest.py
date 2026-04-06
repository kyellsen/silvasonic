"""Shared fixtures for cross-cutting integration tests.

Re-exports session-scoped container fixtures from ``silvasonic-test-utils``
and provides an autouse DB cleanup fixture for parallel-safe execution
with ``pytest-xdist``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from silvasonic.test_utils.containers import postgres_container as postgres_container
from silvasonic.test_utils.containers import redis_container as redis_container
from silvasonic.test_utils.containers import shared_network as shared_network
from silvasonic.test_utils.helpers import clean_database
from testcontainers.postgres import PostgresContainer


@pytest.fixture(autouse=True)
def _clean_db_tables(postgres_container: PostgresContainer) -> Iterator[None]:
    """Reset application tables after each test for parallel safety.

    Runs **after** every integration test in this directory.  Truncates
    all user application tables dynamically so that tests running on the
    same xdist worker with a shared session-scoped database cannot
    interfere with each other.
    """
    yield
    asyncio.get_event_loop().run_until_complete(clean_database(postgres_container))
