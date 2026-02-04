import os

import pytest
import structlog
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# Configure structlog for tests
structlog.configure(
    processors=[structlog.processors.JSONRenderer()],
    logger_factory=structlog.PrintLoggerFactory(),
)

# Auto-configure DOCKER_HOST for Podman (Rootless)
if "DOCKER_HOST" not in os.environ:
    uid = os.getuid()
    rootless_socket = f"/run/user/{uid}/podman/podman.sock"
    if os.path.exists(rootless_socket):
        os.environ["DOCKER_HOST"] = f"unix://{rootless_socket}"
        print(f"DEBUG: Set DOCKER_HOST to {os.environ['DOCKER_HOST']}")

# Disable Ryuk (Reaper) for Podman compatibility if needed
os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"


@pytest.fixture(scope="session")
def postgres_url():
    """Spins up a Postgres container for integration tests."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    init_sql_path = os.path.join(project_root, "scripts", "db", "init.sql")

    if not os.path.exists(init_sql_path):
        raise FileNotFoundError(f"init.sql not found at {init_sql_path}")

    # Use Timescale image as per production
    postgres = PostgresContainer(
        "timescale/timescaledb-ha:pg17",
        username="testuser",
        password="testpass",
        dbname="silvasonic_test",
    )

    # Mount init.sql
    postgres.with_volume_mapping(init_sql_path, "/docker-entrypoint-initdb.d/init.sql", mode="z")

    postgres.start()

    try:
        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
        # return async url
        yield f"postgresql+asyncpg://testuser:testpass@{host}:{port}/silvasonic_test"
    finally:
        postgres.stop()


@pytest.fixture(scope="session")
def redis_url():
    """Spins up a Redis container."""
    redis = RedisContainer("redis:7-alpine")
    redis.start()

    try:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}"
    finally:
        redis.stop()
