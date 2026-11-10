"""Shared helpers for system tests.

Container management, DB/Redis readiness checks, state-based polling
waiters, and device seeding used across all ``tests/system/`` modules.
"""

from __future__ import annotations

import contextlib
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from pathlib import Path

import pytest
from redis import Redis
from silvasonic.core.ids import uuid7

PROCESSOR_IMAGE = "localhost/silvasonic_processor:latest"
REDIS_IMAGE = "docker.io/library/redis:7-alpine"
BIRDNET_IMAGE = "localhost/silvasonic_birdnet:latest"


# ---------------------------------------------------------------------------
# State-based polling
# ---------------------------------------------------------------------------


def wait_until[T](
    description: str,
    predicate: Callable[[], T],
    *,
    timeout: float = 30,
    poll_interval: float = 1.0,
) -> T:
    """Poll *predicate* until it returns a truthy value or *timeout* expires.

    Returns the truthy value on success.  Predicate exceptions are
    swallowed (treated as "not yet ready").  On timeout the test is
    failed via ``pytest.fail()`` with *description* for immediate
    root-cause identification.
    """
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:
            last_exc = exc
        time.sleep(poll_interval)
    detail = f" (last error: {last_exc})" if last_exc else ""
    pytest.fail(f"Timeout: {description}{detail}")


def wait_for_log_pattern(
    container: str,
    pattern: str,
    *,
    timeout: float = 25,
    poll_interval: float = 1.0,
) -> str:
    """Poll container logs for *pattern*. Returns full logs on match.

    **Diagnostic/fallback helper only.**  Must NOT be used for primary
    business-logic assertions — use only where no observable external
    state exists (e.g. verifying an internal skip/fallback code path).
    """

    def _check() -> str:
        logs = podman_logs(container)
        return logs if pattern in logs else ""

    return wait_until(
        f"log pattern '{pattern}' in {container}",
        _check,
        timeout=timeout,
        poll_interval=poll_interval,
    )


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


def require_birdnet_image() -> None:
    """Skip if the BirdNET image is not built."""
    if not image_exists(BIRDNET_IMAGE):
        pytest.skip("BirdNET image not built (run 'just build' first)")


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

    A container whose ``env`` names ``SILVASONIC_DB_PATH`` gets the database
    directory of the running test (see ``system_db``) mounted read-write at
    ``/data/database``, as compose does on a station (ADR-0037).

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
        if "SILVASONIC_DB_PATH" in env:
            if _ACTIVE_DB_DIR is None:
                msg = f"{name} needs the database, but no system_db fixture is active"
                raise RuntimeError(msg)
            cmd.extend(["-v", f"{_ACTIVE_DB_DIR}:{DB_DIR_IN_CONTAINER}:z"])
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


DB_DIR_IN_CONTAINER = "/data/database"
DB_PATH_IN_CONTAINER = f"{DB_DIR_IN_CONTAINER}/silvasonic.db"

# Database directory of the running test; set by the ``system_db`` fixture.
# Tests run one at a time per pytest-xdist worker process.
_ACTIVE_DB_DIR: Path | None = None


def db_query(
    db_dir: str | Path,
    query: str,
    *,
    retries: int = 0,
    retry_delay: float = 1.0,
) -> str:
    """Execute one SQL statement against the test database file, from the host.

    Returns the rows as text in the shape ``psql -t -A`` printed: one line
    per row, columns joined by ``|``, NULL as an empty string.  SQLite
    returns booleans as ``1``/``0`` and times as epoch microseconds.

    The database lives in a directory shared with the containers, so the
    host reads the same file the services write (WAL mode lets it read
    while they write).

    Args:
        db_dir: Database directory yielded by ``system_db``.
        query: SQL statement to execute.
        retries: Retry attempts while a service holds the write lock longer
            than the busy timeout, or before the first service created the file.
        retry_delay: Seconds to wait between retries.
    """
    path = Path(db_dir) / "silvasonic.db"
    last_err: Exception | None = None
    for attempt in range(1 + retries):
        try:
            con = sqlite3.connect(path, timeout=10, isolation_level=None)
            try:
                con.execute("PRAGMA busy_timeout = 10000")
                rows = con.execute(query).fetchall()
            finally:
                con.close()
            return "\n".join(
                "|".join("" if v is None else str(v) for v in row) for row in rows
            ).strip()
        except sqlite3.Error as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(retry_delay)
    assert last_err is not None  # range(1 + retries) runs at least once
    raise RuntimeError(f"SQLite query failed: {last_err}") from last_err


@contextlib.contextmanager
def active_database(db_dir: Path) -> Generator[None]:
    """Mount ``db_dir`` into every DB client ``podman_run`` starts meanwhile."""
    global _ACTIVE_DB_DIR
    _ACTIVE_DB_DIR = db_dir
    try:
        yield
    finally:
        _ACTIVE_DB_DIR = None


def create_test_database(db_dir: Path) -> None:
    """Create the station database with its schema, as a service's first connection would.

    The directory is opened to everyone: under rootless Podman the container's
    root is the host user, but the SQLite WAL and lock files must be
    writable by whichever process opens them first.
    """
    db_dir.mkdir(parents=True, exist_ok=True)
    db_dir.chmod(0o777)
    import asyncio

    from silvasonic.core.database.session import create_station_engine

    async def _create() -> None:
        engine = create_station_engine(db_dir / "silvasonic.db")
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        await engine.dispose()

    asyncio.run(_create())


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


def seed_test_microphones(db_container: str | Path, hardware_ids: list[str]) -> None:
    """Seed microphone_profiles and microphones rows for system tests.

    The Indexer resolves a workspace directory to ``microphones.id`` via
    ``workspace_name``; its INSERT into ``recordings`` needs that row. In
    production, the Controller seeds these; in system tests, we do it
    manually. Each test microphone uses its hardware ID as name and
    workspace name.

    Uses retries in case a service holds the write lock at that moment.
    """
    db_query(
        db_container,
        """INSERT INTO microphone_profiles (slug, name, config)
           VALUES ('test_profile', 'Test Profile', '{}')
           ON CONFLICT (slug) DO NOTHING""",
        retries=10,
    )
    for hw_id in hardware_ids:
        db_query(
            db_container,
            f"""
                INSERT INTO microphones (
                    id, hardware_id, name, serial_number, model, hardware,
                    profile_slug, workspace_name
                )
                VALUES (
                    '{uuid7().hex}', '{hw_id}', '{hw_id}', '{hw_id}-serial', 'test-model',
                    '{{}}', 'test_profile', '{hw_id}'
                )
                ON CONFLICT (hardware_id) DO NOTHING
            """,
            retries=10,
        )


def seed_storage_settings(
    db_container: str | Path,
    *,
    warning_percent: float = 70.0,
    critical_percent: float = 80.0,
    emergency_percent: float = 90.0,
    cleanup_interval_s: int = 60,
    cleanup_batch_files: int = 50,
    index_interval_s: float = 2.0,
) -> None:
    """Seed StorageSettings into the ``storage`` section of the settings table.

    Allows tests to override Janitor thresholds and intervals.
    """
    import json

    config = {
        "warning_percent": warning_percent,
        "critical_percent": critical_percent,
        "emergency_percent": emergency_percent,
        "cleanup_interval_s": cleanup_interval_s,
        "cleanup_batch_files": cleanup_batch_files,
        "index_interval_s": index_interval_s,
    }
    config_json = json.dumps(config).replace("'", "''")
    db_query(
        db_container,
        f"""INSERT INTO settings (section, value)
           VALUES ('storage', '{config_json}')
           ON CONFLICT (section) DO UPDATE SET value = EXCLUDED.value""",
        retries=10,
    )


def count_wav_files(workspace: Path) -> int:
    """Count WAV files recursively in a workspace directory."""
    return len(list(workspace.rglob("*.wav")))


def wait_for_wavs(
    directory: Path,
    *,
    min_count: int = 1,
    timeout: float = 20,
    poll_interval: float = 1.0,
) -> list[Path]:
    """Poll for WAV files with early return."""

    def _check() -> list[Path]:
        files = sorted(directory.rglob("*.wav"))
        return files if len(files) >= min_count else []

    return wait_until(
        f"{min_count} WAVs in {directory}",
        _check,
        timeout=timeout,
        poll_interval=poll_interval,
    )


def wait_for_db_rows(
    db_container: str | Path,
    query: str,
    *,
    min_count: int = 1,
    timeout: float = 20,
    poll_interval: float = 1.0,
) -> int:
    """Poll database for a minimum row count."""

    def _check() -> int:
        output = db_query(db_container, query, retries=0).strip()
        count = int(output) if output.isdigit() else 0
        return count if count >= min_count else 0

    return wait_until(
        f">= {min_count} rows from: {query}",
        _check,
        timeout=timeout,
        poll_interval=poll_interval,
    )


def wait_for_detection(
    db_container: str | Path,
    prefix_taxon: str,
    *,
    timeout: float = 40,
    poll_interval: float = 2.0,
) -> dict[str, str]:
    """Poll for a BirdNET detection by taxon prefix and return its id, label, clip_path."""
    query = (
        "SELECT id, label, clip_path FROM detections "
        f"WHERE label LIKE '{prefix_taxon}%' AND analyzer = 'birdnet' LIMIT 1"
    )

    def _check() -> dict[str, str]:
        output = db_query(db_container, query, retries=0).strip()
        if output and "|" in output:
            id_str, label, clip_path = output.split("|")
            return {"id": id_str, "label": label, "clip_path": clip_path}
        return {}

    return wait_until(
        f"BirdNET detection with prefix '{prefix_taxon}'",
        _check,
        timeout=timeout,
        poll_interval=poll_interval,
    )


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
    interfere via shared DNS aliases (``redis``).
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
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, str]]:
    """Create a station database (SQLite, ADR-0037) in a directory of its own.

    Yields ``(db_dir, run_id)``.  ``db_dir`` is mounted into every container
    started with ``SILVASONIC_DB_PATH`` in its env (see ``podman_run``) and
    is queried from the host with ``db_query``.  Seeds test devices for FK
    satisfaction.
    """
    global _ACTIVE_DB_DIR
    db_dir = tmp_path_factory.mktemp(f"database-{run_id}")
    db_dir.chmod(0o777)  # container root is the host user under rootless Podman
    create_test_database(db_dir)
    seed_test_microphones(db_dir, ["test-device", "mic-aaa", "mic-bbb"])
    _ACTIVE_DB_DIR = db_dir
    try:
        yield (str(db_dir), run_id)
    finally:
        _ACTIVE_DB_DIR = None


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

    Redis resolves by its fixed DNS name within the test's isolated Podman
    network; the database is the file ``podman_run`` mounts.
    """
    return {
        "SILVASONIC_DB_PATH": DB_PATH_IN_CONTAINER,
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
