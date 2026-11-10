"""Shared fixtures for BirdNET integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from silvasonic.core.database.session import create_station_engine
from silvasonic.test_utils.containers import station_db as station_db
from silvasonic.test_utils.helpers import clean_database


@pytest.fixture(autouse=True)
async def _clean_db_tables(station_db: Path) -> AsyncIterator[None]:
    """Reset application tables after each test for parallel safety.

    Runs **after** every integration test in this directory. Truncates
    all user application tables dynamically so that tests running on the
    same xdist worker with a shared session-scoped database cannot
    interfere with each other.
    """
    import os

    from silvasonic.core.database.session import override_engine, reset_engine

    # Set env vars for database settings
    os.environ["SILVASONIC_DB_PATH"] = str(station_db)

    # Override engine globally for all code running in this test worker
    engine = create_station_engine(station_db)
    override_engine(engine)

    try:
        await clean_database(station_db)
        yield
    finally:
        reset_engine()
        await engine.dispose()
        await clean_database(station_db)
