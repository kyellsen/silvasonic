"""Shared Docker/Podman container fixtures for Silvasonic integration tests.

All fixtures are ``session``-scoped, meaning each container is started exactly
**once** per ``pytest`` invocation and shared across every integration test that
declares it as a parameter. This is critical for performance: a TimescaleDB
container takes ~10 s to start, so starting it once vs. once-per-test-class
makes a significant difference.

Usage (in a test file — no import needed if consumed via root conftest.py):

    @pytest.mark.integration
    async def test_something(postgres_container: PostgresContainer) -> None:
        url = build_postgres_url(postgres_container)
        ...

"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer
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
def postgres_container(shared_network: Network) -> Iterator[PostgresContainer]:
    """Provide a session-scoped TimescaleDB container with the Silvasonic schema.

    Mounts the real init SQL scripts from ``services/database/init/`` so the
    schema matches production exactly. This ensures integration tests run
    against the same table structure, hypertables, and indexes as the live DB.

    Network aliases ``silvasonic-postgres`` and ``db`` allow other containers
    (e.g. Controller) to resolve the database by name inside the shared network.

    Yields:
        A running ``PostgresContainer`` instance. Use ``build_postgres_url()``
        from :mod:`silvasonic.test_utils.helpers` to get a connection URL.
    """
    repo_root = _get_repo_root()
    init_dir = repo_root / "services" / "database" / "init"

    postgres = PostgresContainer(
        image="docker.io/timescale/timescaledb:2.19.3-pg17",
        username="silvasonic",
        password="silvasonic",
        dbname="silvasonic_test",
    )
    postgres.with_network(shared_network)
    postgres.with_network_aliases("silvasonic-postgres", "db")

    # Mount real init scripts so the schema is identical to production.
    init_extensions = init_dir / "00-init-extensions.sql"
    init_schema = init_dir / "01-init-schema.sql"

    if init_extensions.exists():
        postgres.with_volume_mapping(
            str(init_extensions),
            "/docker-entrypoint-initdb.d/00-init-extensions.sql",
            mode="z",
        )
    if init_schema.exists():
        postgres.with_volume_mapping(
            str(init_schema),
            "/docker-entrypoint-initdb.d/01-init-schema.sql",
            mode="z",
        )

    with postgres:
        yield postgres


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
