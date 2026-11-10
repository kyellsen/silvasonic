"""Shared fixtures for Controller integration tests.

Provides an autouse cleanup fixture that resets DB state after each
test, ensuring parallel-safe execution with ``pytest-xdist``.

With ``-n 4`` each xdist worker gets its **own** session-scoped
``station_db``.  Tests on the same worker share that DB and
run sequentially.  The autouse fixture guarantees a clean slate
between tests so that leftover rows never cause false positives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from silvasonic.core.database.session import create_station_engine
from silvasonic.test_utils.helpers import clean_database


@pytest.fixture(autouse=True)
async def _clean_db_tables(station_db: Path) -> AsyncIterator[None]:
    """Reset application tables after each test for parallel safety.

    Runs **after** every integration test in this directory.  Truncates
    all user application tables dynamically so that tests running on the
    same xdist worker with a shared session-scoped database cannot
    interfere with each other.
    """
    import os

    from silvasonic.core.database.session import override_engine, reset_engine

    # Point code that builds its own engine at the test database
    os.environ["SILVASONIC_DB_PATH"] = str(station_db)

    # Override engine globally for all code running in this test worker
    engine = create_station_engine(station_db)
    override_engine(engine)

    try:
        yield
    finally:
        reset_engine()
        await engine.dispose()
        await clean_database(station_db)
