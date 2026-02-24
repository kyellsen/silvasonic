"""Testcontainer fixtures for smoke tests.

Provides isolated, ephemeral containers for each Silvasonic service.
All containers use random ephemeral ports to avoid conflicts with
the dev stack or any other running containers.

No host-filesystem writes: workspace volumes use tmpfs.
"""

import time
from collections.abc import Generator

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

# ── Helper ────────────────────────────────────────────────────────────────────


def _wait_for_http(host: str, port: int, path: str = "/healthy", timeout: float = 60) -> None:
    """Poll an HTTP endpoint until it returns 200 or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"http://{host}:{port}{path}", timeout=3.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    msg = f"Service on {host}:{port}{path} did not become healthy within {timeout}s"
    raise TimeoutError(msg)


def _wait_for_log(container: DockerContainer, message: str, timeout: float = 60) -> None:
    """Wait for a log message to appear in the container logs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stdout, stderr = container.get_logs()
        logs = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
        if message in logs:
            return
        time.sleep(2)
    msg = f"Log message '{message}' not found within {timeout}s"
    raise TimeoutError(msg)


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
    _wait_for_log(container, "database system is ready to accept connections")
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
    _wait_for_log(container, "Ready to accept connections")
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
    # Ensure fixtures are used (dependency ordering)
    _ = database_container
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_controller")
        .with_exposed_ports(9100)
        .with_env("POSTGRES_HOST", "test-database")
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_env("POSTGRES_PORT", "5432")
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_network(smoke_network)
        .with_kwargs(tmpfs={"/app/workspace": "rw", "/app/recorder-workspace": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9100))
    _wait_for_http(host, port)
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
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_recorder")
        .with_exposed_ports(9500)
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_network(smoke_network)
        .with_kwargs(tmpfs={"/app/workspace": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9500))
    _wait_for_http(host, port)
    yield container
    container.stop()


# ── Web-Mock ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def web_mock_container() -> Generator[DockerContainer]:
    """Start an isolated Web-Mock container.

    Function-scoped: fresh container per test (immutable Tier 2 pattern).
    No database connection needed — web-mock serves hardcoded mock data.
    No shared network needed.
    """
    container = DockerContainer("silvasonic_web-mock").with_exposed_ports(8001)
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(8001))
    _wait_for_http(host, port)
    yield container
    container.stop()
