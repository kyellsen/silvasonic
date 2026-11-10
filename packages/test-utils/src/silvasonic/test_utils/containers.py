"""Shared Docker/Podman container fixtures for Silvasonic integration tests.

All fixtures are ``session``-scoped: each is created exactly **once** per
``pytest`` process and shared across every integration test that declares it.

Usage (in a test file — no import needed if consumed via root conftest.py):

    @pytest.mark.integration
    async def test_something(station_db: Path) -> None:
        engine = create_station_engine(station_db)
        ...

"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.core.network import Network
from testcontainers.redis import RedisContainer


def _get_repo_root() -> Path:
    """Return the repository root directory.

    Walks up until a ``.git`` directory is found (repo root anchor).
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parents[5]  # Fallback


@pytest.fixture(scope="session")
def shared_network() -> Iterator[Network]:
    """Provide a shared Docker/Podman network for inter-container communication.

    Session-scoped: the network is created once per ``pytest`` run and removed
    after all tests complete. All containers that need to communicate must be
    attached to this network.

    Yields:
        A running ``testcontainers`` ``Network`` instance.
    """
    with Network() as network:
        yield network


@pytest.fixture(scope="session")
def station_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Provide a session-scoped station database file (SQLite, ADR-0037).

    One file per ``pytest`` process, so every xdist worker has its own.  The
    schema is created by the first connection, exactly as on a station.
    Point services at it with ``SILVASONIC_DB_PATH`` or create an engine
    with ``silvasonic.core.database.create_station_engine(station_db)``.

    Yields:
        Path of the database file (it may not exist until first connect).
    """
    yield tmp_path_factory.mktemp("database") / "silvasonic.db"


@pytest.fixture(scope="session")
def redis_container(shared_network: Network) -> Iterator[RedisContainer]:
    """Provide a session-scoped Redis container on the shared network.

    Network aliases ``silvasonic-redis`` and ``redis`` allow other containers
    or test code to resolve Redis by name inside the shared network.

    Yields:
        A running ``RedisContainer`` instance.
    """
    redis = RedisContainer("docker.io/library/redis:7.4-alpine")
    redis.with_network(shared_network)
    redis.with_network_aliases("silvasonic-redis", "redis")

    with redis:
        yield redis
