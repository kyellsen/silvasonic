# packages/core/tests/conftest.py
import os
import subprocess
import time
import uuid
from collections.abc import Generator

import pytest


@pytest.fixture(scope="session")
def postgres_container() -> Generator[str, None, None]:
    """Spins up a Postgres container using Podman for integration tests.

    Yields the database URL.
    """
    container_name = f"silvasonic-test-db-{uuid.uuid4()}"

    db_name = "silvasonic_test"
    db_user = "testuser"
    db_pass = "testpass"

    print(f"Starting Podman container: {container_name}")
    try:
        # Run the container
        # Use TimescaleDB image to support hypertables
        # Mount init.sql to enable extension
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        init_sql_path = os.path.join(project_root, "scripts", "db", "init.sql")

        # Ensure init.sql exists
        if not os.path.exists(init_sql_path):
            raise FileNotFoundError(f"init.sql not found at {init_sql_path}")

        subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                "-d",
                "-P",  # Assign a random host port
                "-e",
                f"POSTGRES_PASSWORD={db_pass}",
                "-e",
                f"POSTGRES_DB={db_name}",
                "-e",
                f"POSTGRES_USER={db_user}",
                "-v",
                f"{init_sql_path}:/docker-entrypoint-initdb.d/init.sql:z",  # :z for SELinux if needed
                "--name",
                container_name,
                "timescale/timescaledb-ha:pg17",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Get the assigned port
        # output format example: 0.0.0.0:49153
        port_output = (
            subprocess.check_output(["podman", "port", container_name, "5432"])
            .decode("utf-8")
            .strip()
        )

        # Extract just the port number
        assigned_host_port = port_output.split(":")[-1]

        # Wait for Postgres to be ready
        print(f"Waiting for database to be ready on port {assigned_host_port}...")
        retries = 30
        while retries > 0:
            try:
                subprocess.check_call(
                    [
                        "podman",
                        "exec",
                        container_name,
                        "pg_isready",
                        "-U",
                        db_user,
                        "-d",
                        db_name,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                print("Database is ready!")
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
                retries -= 1

        if retries == 0:
            raise RuntimeError("Database failed to start within timeout")

        # Construct Database URL
        # Note: When running tests from the host, we connect to localhost:host_port
        database_url = (
            f"postgresql+asyncpg://{db_user}:{db_pass}@localhost:{assigned_host_port}/{db_name}"
        )

        yield database_url

    finally:
        print(f"Stopping Podman container: {container_name}")
        subprocess.call(
            ["podman", "kill", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # --rm was used, so it should be removed automatically, but kill is safer
