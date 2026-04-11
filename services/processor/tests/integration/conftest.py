"""Shared fixtures for Processor integration tests.

Provides an autouse cleanup fixture that resets DB state after each
test, ensuring parallel-safe execution with ``pytest-xdist``.

With ``-n 4`` each xdist worker gets its **own** session-scoped
``postgres_container``.  Tests on the same worker share that DB and
run sequentially.  The autouse fixture guarantees a clean slate
between tests so that leftover rows never cause false positives.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
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
