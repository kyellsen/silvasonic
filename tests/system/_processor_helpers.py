"""Shared helpers for Processor system tests.

Container management, DB/Redis readiness checks, and device seeding
used by both ``test_processor_lifecycle.py`` and
``test_processor_resilience.py``.
"""

from __future__ import annotations

import contextlib
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from redis import Redis

PROCESSOR_IMAGE = "localhost/silvasonic_processor:latest"
DATABASE_IMAGE = "localhost/silvasonic_database:latest"
REDIS_IMAGE = "docker.io/library/redis:7-alpine"


# ---------------------------------------------------------------------------
# Image checks
# ---------------------------------------------------------------------------


def image_exists(image: str) -> bool:
    """Check if a container image is built locally."""
    result = subprocess.run(
        ["podman", "image", "exists", image],
        capture_output=True,
    )
    return result.returncode == 0


def require_processor_image() -> None:
    """Skip if the Processor image is not built."""
    if not image_exists(PROCESSOR_IMAGE):
        pytest.skip("Processor image not built (run 'just build' first)")


def require_database_image() -> None:
    """Skip if the Database image is not built."""
    if not image_exists(DATABASE_IMAGE):
        pytest.skip("Database image not built (run 'just build' first)")


# ---------------------------------------------------------------------------
# Container management
# ---------------------------------------------------------------------------


def podman_run(
    name: str,
    image: str,
    *,
    env: dict[str, str] | None = None,
    publish: list[str] | None = None,
    volumes: list[str] | None = None,
    network: str,
    network_aliases: list[str] | None = None,
) -> str:
    """Start a container via podman run. Returns container ID.

    Args:
        name: Container name.
        image: Container image.
        env: Environment variable dict.
        publish: Port mappings as ``-p`` arguments. Use ``[":6379"]`` for
            random host-port or ``["5432:5432"]`` for fixed mapping.
        volumes: Volume mount specifications.
        network: Podman network to join.
        network_aliases: DNS aliases for the container on the network.
    """
    cmd = [
        "podman",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
    ]
    if network_aliases:
        for alias in network_aliases:
            cmd.extend(["--network-alias", alias])
    if env:
        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])
    if publish:
        for port_spec in publish:
            cmd.extend(["-p", port_spec])
    if volumes:
        for vol in volumes:
            cmd.extend(["-v", vol])
    cmd.append(image)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        pytest.fail(
            f"podman run failed for {name}: exit {result.returncode}\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
    return result.stdout.strip()


def podman_stop_rm(name: str) -> None:
    """Force-stop and remove a container."""
    with contextlib.suppress(Exception):
        subprocess.run(
            ["podman", "rm", "-f", name],
            capture_output=True,
            timeout=15,
        )


def podman_stop(name: str) -> None:
    """Stop a container (keep it for restart)."""
    with contextlib.suppress(Exception):
        subprocess.run(
            ["podman", "stop", name],
            capture_output=True,
            timeout=15,
        )


def podman_start(name: str) -> None:
    """Re-start a previously stopped container."""
    result = subprocess.run(
        ["podman", "start", name],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        pytest.fail(
            f"podman start failed for {name}: exit {result.returncode}\nstderr: {result.stderr}"
        )


def podman_is_running(name: str) -> bool:
    """Check whether a container is currently running."""
    result = subprocess.run(
        ["podman", "inspect", "--format", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def podman_logs(name: str) -> str:
    """Get container logs."""
    try:
        result = subprocess.run(
            ["podman", "logs", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    except Exception as e:
        return f"Could not fetch logs: {e}"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def psql_query(
    db_container: str,
    query: str,
    *,
    retries: int = 0,
    retry_delay: float = 1.0,
) -> str:
    """Execute a SQL query via psql inside the DB container.

    Returns the raw stdout output. Uses ``-t`` (tuples-only) and ``-A``
    (unaligned) for machine-readable output.

    Args:
        db_container: Name of the running database container.
        query: SQL statement to execute.
        retries: Number of retry attempts on transient failure (e.g. DB
            container restarting its init scripts under parallel load).
        retry_delay: Seconds to wait between retries.
    """
    last_err: RuntimeError | None = None
    for attempt in range(1 + retries):
        result = subprocess.run(
            [
                "podman",
                "exec",
                db_container,
                "psql",
                "-U",
                "silvasonic",
                "-d",
                "silvasonic",
                "-t",
                "-A",
                "-c",
                query,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        last_err = RuntimeError(f"psql query failed: {result.stderr}")
        if attempt < retries:
            time.sleep(retry_delay)
    raise last_err  # type: ignore[misc]


def wait_for_db(db_container: str, timeout: float = 30) -> None:
    """Wait for PostgreSQL inside the container to accept connections.

    Uses an actual SQL query (not just pg_isready) to ensure the init
    scripts have completed and tables exist.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "podman",
                    "exec",
                    db_container,
                    "psql",
                    "-U",
                    "silvasonic",
                    "-d",
                    "silvasonic",
                    "-t",
                    "-A",
                    "-c",
                    "SELECT COUNT(*) FROM microphone_profiles",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip().isdigit():
                return
        except Exception:
            pass
        time.sleep(1)
    msg = f"Database container '{db_container}' not ready after {timeout}s"
    raise TimeoutError(msg)


def wait_for_redis(host: str, port: int, timeout: float = 15) -> None:
    """Wait for Redis to respond to PING."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = Redis(host=host, port=port)
            if r.ping():
                r.close()
                return
        except Exception:
            time.sleep(0.5)
    msg = f"Redis not ready at {host}:{port} after {timeout}s"
    raise TimeoutError(msg)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def seed_test_devices(db_container: str, device_names: list[str]) -> None:
    """Seed microphone_profiles and devices rows for system tests.

    The Indexer's INSERT into ``recordings`` requires a matching FK in
    ``devices(name)``. In production, the Controller seeds these; in system
    tests, we do it manually.

    Uses retries because under parallel load the PostgreSQL init scripts
    may briefly restart the server after ``wait_for_db`` succeeds.
    """
    psql_query(
        db_container,
        """INSERT INTO microphone_profiles (slug, name, config)
           VALUES ('test_profile', 'Test Profile', '{}')
           ON CONFLICT (slug) DO NOTHING""",
        retries=10,
    )
    for dev in device_names:
        psql_query(
            db_container,
            f"""
                INSERT INTO devices (
                    name, serial_number, model, config, profile_slug, workspace_name
                )
                VALUES (
                    '{dev}', '{dev}-serial', 'test-model',
                    '{{}}'::jsonb, 'test_profile', '{dev}'
                )
                ON CONFLICT (name) DO NOTHING
            """,
            retries=10,
        )


def seed_processor_config(
    db_container: str,
    *,
    janitor_threshold_warning: float = 70.0,
    janitor_threshold_critical: float = 80.0,
    janitor_threshold_emergency: float = 90.0,
    janitor_interval_seconds: int = 60,
    janitor_batch_size: int = 50,
    indexer_poll_interval: float = 2.0,
) -> None:
    """Seed ProcessorSettings into system_config table.

    Allows tests to override Janitor thresholds and intervals.
    """
    import json

    config = {
        "janitor_threshold_warning": janitor_threshold_warning,
        "janitor_threshold_critical": janitor_threshold_critical,
        "janitor_threshold_emergency": janitor_threshold_emergency,
        "janitor_interval_seconds": janitor_interval_seconds,
        "janitor_batch_size": janitor_batch_size,
        "indexer_poll_interval": indexer_poll_interval,
    }
    config_json = json.dumps(config).replace("'", "''")
    psql_query(
        db_container,
        f"""INSERT INTO system_config (key, value)
           VALUES ('processor', '{config_json}'::jsonb)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        retries=10,
    )


def count_wav_files(workspace: Path) -> int:
    """Count WAV files recursively in a workspace directory."""
    return len(list(workspace.rglob("*.wav")))


# ---------------------------------------------------------------------------
# Shared Fixtures — Network, DB, Redis (P0/P1/P2)
# ---------------------------------------------------------------------------


@pytest.fixture()
def run_id() -> str:
    """Unique ID per test to avoid container name collisions."""
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def system_network(run_id: str) -> Iterator[str]:
    """Create an isolated Podman network per test. Yields network name.

    Each test gets its own network so that parallel tests cannot
    interfere via shared DNS aliases (``database``, ``redis``).
    Cleaned up in teardown.
    """
    network_name = f"silvasonic-test-{run_id}"
    subprocess.run(
        ["podman", "network", "create", network_name],
        capture_output=True,
        check=True,
        timeout=10,
    )
    try:
        yield network_name
    finally:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["podman", "network", "rm", "-f", network_name],
                capture_output=True,
                timeout=10,
            )


@pytest.fixture()
def system_db(
    run_id: str,
    system_network: str,
) -> Iterator[tuple[str, str]]:
    """Start a PostgreSQL container on an isolated network.

    Yields ``(db_container_name, run_id)``.
    Seeds test devices for FK satisfaction.
    """
    require_database_image()

    name = f"silvasonic-db-{run_id}"
    podman_stop_rm(name)

    podman_run(
        name,
        DATABASE_IMAGE,
        env={
            "POSTGRES_USER": "silvasonic",
            "POSTGRES_PASSWORD": "silvasonic",
            "POSTGRES_DB": "silvasonic",
        },
        network=system_network,
        network_aliases=["database", "silvasonic-database"],
    )

    try:
        wait_for_db(name, timeout=30)
        seed_test_devices(name, ["test-device", "mic-aaa", "mic-bbb"])
        yield (name, run_id)
    finally:
        podman_stop_rm(name)


@pytest.fixture()
def system_redis(
    run_id: str,
    system_network: str,
) -> Iterator[tuple[str, int, str]]:
    """Start a Redis container on an isolated network.

    Uses dynamic host-port allocation (``-p 0:6379``) to avoid
    port collisions when tests run in parallel.

    Yields ``(host, mapped_port, container_name)``.
    """
    name = f"silvasonic-redis-{run_id}"
    podman_stop_rm(name)

    podman_run(
        name,
        REDIS_IMAGE,
        publish=[":6379"],
        network=system_network,
        network_aliases=["redis", "silvasonic-redis"],
    )

    result = subprocess.run(
        ["podman", "port", name, "6379"],
        capture_output=True,
        text=True,
        check=True,
    )
    mapped_port = int(result.stdout.strip().split(":")[-1])

    try:
        wait_for_redis("127.0.0.1", mapped_port, timeout=15)
        yield ("127.0.0.1", mapped_port, name)
    finally:
        podman_stop_rm(name)


def make_processor_env() -> dict[str, str]:
    """Build the standard Processor environment dict.

    Uses fixed DNS names (``database``, ``redis``) that resolve
    within the test's isolated Podman network.
    """
    return {
        "SILVASONIC_DB_HOST": "database",
        "SILVASONIC_DB_PORT": "5432",
        "POSTGRES_USER": "silvasonic",
        "POSTGRES_PASSWORD": "silvasonic",
        "POSTGRES_DB": "silvasonic",
        "SILVASONIC_REDIS_URL": "redis://redis:6379/0",
        "SILVASONIC_RECORDINGS_DIR": "/data/recorder",
        "SILVASONIC_ENCRYPTION_KEY": "zVwzBZb-B2UaAqyP3jDihh01e_-80u2rD5pYtQYkUaQ=",
    }


def make_recorder_env() -> dict[str, str]:
    """Build the standard Recorder (mock source) environment dict."""
    return {
        "SILVASONIC_RECORDER_DEVICE": "hw:99,0",
        "SILVASONIC_RECORDER_MOCK_SOURCE": "true",
        "SILVASONIC_REDIS_URL": "redis://redis:6379/0",
        "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
        "SILVASONIC_RECORDER_PROFILE_SLUG": "test_profile",
    }
