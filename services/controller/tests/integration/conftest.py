import os

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# Or just import the fixtures if they are in root/tests/integration/conftest.py
# Pytest discovery might not see root/tests/integration/conftest.py from services/controller/tests/integration/
# Actually, the best way is to move the fixtures to a common conftest in root `tests/conftest.py`
# OR just copy/symlink them or import them.
# Given the structure:
# tests/integration/conftest.py (Has postgres_url)
# services/controller/tests/integration/mic_profiles_refresh.py (Needs postgres_url)
# We can create a conftest.py here that plugins the root one or re-defines the fixtures.
# Let's try to define them here for now by importing from reference implementation or just copy-paste for speed/isolation.
# But wait, `postgres_url` fixture spins up a container. using the same one as other tests saves time.
# Pytest should find `tests/conftest.py` if it is in root.
# But `tests/integration/conftest.py` is nested.
# Plan:
# 1. Check if `tests/conftest.py` exists (Global).
# 2. If not, create `services/controller/tests/integration/conftest.py` and implement `postgres_url` there.

# Disable Ryuk (Reaper) for Podman compatibility
os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"


@pytest.fixture(scope="session")
def postgres_url():
    """Spins up a Postgres container for integration tests."""
    # We need to find the init.sql relative to project root
    # This file is in services/controller/tests/integration/
    # Root is ../../../../

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
    init_sql_path = os.path.join(project_root, "scripts", "db", "init.sql")

    postgres = PostgresContainer(
        "timescale/timescaledb-ha:pg17",
        username="testuser",
        password="testpass",
        dbname="silvasonic_test",
    )
    postgres.with_volume_mapping(init_sql_path, "/docker-entrypoint-initdb.d/init.sql", mode="z")
    postgres.start()

    try:
        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
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
