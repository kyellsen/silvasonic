# packages/core/tests/conftest.py
import os
from collections.abc import Generator

import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> Generator[str, None, None]:
    """Spins up a Postgres container using Testcontainers for integration tests.

    Yields the database URL.
    """
    # Locating init.sql
    # tests/integration -> tests -> core -> packages -> silvasonic
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    init_sql_path = os.path.join(project_root, "scripts", "db", "init.sql")

    if not os.path.exists(init_sql_path):
        raise FileNotFoundError(f"init.sql not found at {init_sql_path}")

    # Configure the container
    postgres = PostgresContainer(
        "timescale/timescaledb-ha:pg17",
        username="testuser",
        password="testpass",
        dbname="silvasonic_test",
    )

    # Mount init.sql to enable extension
    # We mount it to /docker-entrypoint-initdb.d/ which Postgres image executes on startup
    postgres.with_volume_mapping(init_sql_path, "/docker-entrypoint-initdb.d/init.sql", mode="z")

    print(f"Starting Testcontainers Postgres ({postgres.image})...")
    postgres.start()

    try:
        # Construct Async URL
        # PostgresContainer.get_connection_url() usually returns sync driver (psycopg2).
        # We need asyncpg.
        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
        database_url = f"postgresql+asyncpg://testuser:testpass@{host}:{port}/silvasonic_test"

        yield database_url

    finally:
        print("Stopping Testcontainers Postgres...")
        postgres.stop()
