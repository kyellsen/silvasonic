"""Root conftest.py — re-exports shared test-utils fixtures for all test paths.

pytest automatically discovers this file at the project root, making the
session-scoped fixtures available to every test in ``testpaths``
(packages/*, services/*, tests/*) without explicit imports.
"""

from collections.abc import AsyncIterator

import pytest
from silvasonic.test_utils.containers import (  # noqa: F401
    redis_container,
    shared_network,
    station_db,
)


@pytest.fixture(autouse=True)
async def _close_default_database_engine(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Close the cached default engine after each integration test.

    Code under test opens it from ``SILVASONIC_DB_PATH``; its aiosqlite
    connections must close before the test's event loop does.
    """
    yield
    if request.node.get_closest_marker("integration") is not None:
        from silvasonic.core.database.session import dispose_default_engine

        await dispose_default_engine()
