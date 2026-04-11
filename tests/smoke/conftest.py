"""Testcontainer fixtures for smoke tests.

Provides isolated, ephemeral containers for each Silvasonic service.
All containers use random ephemeral ports to avoid conflicts with
the dev stack or any other running containers.

No host-filesystem writes: workspace volumes use tmpfs.
"""

import subprocess
import time
from collections.abc import Generator

import pytest
from silvasonic.test_utils.helpers import wait_for_http, wait_for_log
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

# ── Helper ────────────────────────────────────────────────────────────────────


def _require_image(image: str) -> None:
    """Skip the test if a container image is not available locally.

    Uses ``podman image exists`` to check. Produces a clear skip reason
    instead of a cryptic container-start failure.
    """
    result = subprocess.run(
        ["podman", "image", "exists", image],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Image '{image}' not found — run 'just build' first")


# ── Shared Network ────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def smoke_network() -> Generator[Network]:
    """Create a shared network for inter-container communication.

    Ensures services can resolve each other by alias name.
    """
    with Network() as network:
        yield network


# ── Database ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def database_container(smoke_network: Network) -> Generator[DockerContainer]:
    """Start an isolated TimescaleDB container.

    Session-scoped: shared across all smoke tests for performance.
    Uses tmpfs for the data directory to avoid host-filesystem writes.
    """
    _require_image("silvasonic_database")
    container = (
        DockerContainer("silvasonic_database")
        .with_exposed_ports(5432)
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_network(smoke_network)
        .with_network_aliases("test-database")
        .with_kwargs(tmpfs={"/var/lib/postgresql/data": "rw"})
    )
    container.start()
    wait_for_log(container, "database system is ready to accept connections")
    # Small grace period for pg_isready
    time.sleep(2)
    yield container
    container.stop()


# ── Redis ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def redis_container_smoke(smoke_network: Network) -> Generator[DockerContainer]:
    """Start an isolated Redis container for smoke tests.

    Session-scoped: shared across all smoke tests for performance.
    Connected to the shared smoke_network so services can reach it
    via the 'test-redis' alias.
    """
    container = (
        DockerContainer("docker.io/library/redis:7-alpine")
        .with_exposed_ports(6379)
        .with_command("redis-server --save ''")
        .with_network(smoke_network)
        .with_network_aliases("test-redis")
    )
    container.start()
    wait_for_log(container, "Ready to accept connections")
    yield container
    container.stop()


# ── Controller ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def controller_container(
    smoke_network: Network,
    database_container: DockerContainer,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated Controller container connected to test database and Redis.

    Session-scoped: shared across all smoke tests for performance.
    Connects to the database via 'test-database' alias and to Redis via
    'test-redis' alias on the shared smoke_network.
    Uses tmpfs for workspace directories.
    """
    _require_image("silvasonic_controller")
    # Ensure fixtures are used (dependency ordering)
    _ = database_container
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_controller")
        .with_exposed_ports(9100)
        .with_env("SILVASONIC_DB_HOST", "test-database")
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_env("SILVASONIC_DB_PORT", "5432")
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_network(smoke_network)
        .with_kwargs(tmpfs={"/app/workspace": "rw", "/app/recorder-workspace": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9100))
    wait_for_http(host, port)
    yield container
    container.stop()


# ── Processor ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def processor_container(
    smoke_network: Network,
    database_container: DockerContainer,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated Processor container connected to test database and Redis.

    Session-scoped: shared across all smoke tests for performance.
    Connects to the database via 'test-database' alias and to Redis via
    'test-redis' alias on the shared smoke_network.
    Uses tmpfs for workspace directories (no host writes).
    """
    _require_image("silvasonic_processor")
    # Ensure fixtures are used (dependency ordering)
    _ = database_container
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_processor")
        .with_exposed_ports(9200)
        .with_env("SILVASONIC_DB_HOST", "test-database")
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_env("SILVASONIC_DB_PORT", "5432")
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_env("SILVASONIC_ENCRYPTION_KEY", "zVwzBZb-B2UaAqyP3jDihh01e_-80u2rD5pYtQYkUaQ=")
        .with_network(smoke_network)
        .with_kwargs(tmpfs={"/data/recorder": "rw", "/data/processor": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9200))
    wait_for_http(host, port)
    yield container
    container.stop()


# ── Recorder ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def recorder_container(
    smoke_network: Network,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated Recorder container with Redis.

    Function-scoped: fresh container per test (immutable Tier 2 pattern).
    No database connection needed. Connected to Redis via 'test-redis'
    alias on the shared smoke_network.
    Uses tmpfs for workspace directory.
    """
    _require_image("silvasonic_recorder")
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_recorder")
        .with_exposed_ports(9500)
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_env("SILVASONIC_SKIP_DEVICE_CHECK", "true")
        .with_network(smoke_network)
        .with_kwargs(tmpfs={"/app/workspace": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9500))
    wait_for_http(host, port)
    yield container
    container.stop()


# ── Web-Mock ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def birdnet_container(
    smoke_network: Network,
    database_container: DockerContainer,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated BirdNET container connected to test database and Redis."""
    _require_image("silvasonic_birdnet")
    _ = database_container
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_birdnet")
        .with_exposed_ports(9500)
        .with_env("SILVASONIC_DB_HOST", "test-database")
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_env("SILVASONIC_DB_PORT", "5432")
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_network(smoke_network)
        .with_kwargs(tmpfs={"/app/workspace": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9500))
    wait_for_http(host, port)
    yield container
    container.stop()


@pytest.fixture()
def web_mock_container() -> Generator[DockerContainer]:
    """Start an isolated Web-Mock container.

    Function-scoped: fresh container per test (immutable Tier 2 pattern).
    No database connection needed — web-mock serves hardcoded mock data.
    No shared network needed.
    """
    _require_image("silvasonic_web-mock")
    container = DockerContainer("silvasonic_web-mock").with_exposed_ports(8001)
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(8001))
    wait_for_http(host, port)
    yield container
    container.stop()


# ── DB-Viewer ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_viewer_container(
    smoke_network: Network,
    database_container: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated DB-Viewer container.

    Function-scoped: fresh container per test.
    Connects to the test database.
    """
    _require_image("silvasonic_db-viewer")
    _ = database_container

    container = (
        DockerContainer("silvasonic_db-viewer")
        .with_exposed_ports(8002)
        .with_env("SILVASONIC_DB_HOST", "test-database")
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_env("SILVASONIC_DB_PORT", "5432")
        .with_network(smoke_network)
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(8002))
    wait_for_http(host, port)
    yield container
    container.stop()
