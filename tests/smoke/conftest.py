"""Testcontainer fixtures for smoke tests.

Provides isolated, ephemeral containers for each Silvasonic service.
All containers use random ephemeral ports to avoid conflicts with
the dev stack or any other running containers.

Workspace volumes use tmpfs. The one host directory is the shared station
database (SQLite, ADR-0037) in a pytest temp dir: SQLite needs every
client to see the same files, which a per-container tmpfs cannot give.
"""

import subprocess
from collections.abc import Generator
from pathlib import Path

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
def database_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Directory of the station database, shared by every DB client container.

    The first container that connects creates ``silvasonic.db`` and its
    schema, as on a station.
    """
    path = tmp_path_factory.mktemp("database")
    path.chmod(0o777)  # container root is the host user under rootless Podman
    return path


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
    database_dir: Path,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated Controller container with the shared database and Redis.

    Session-scoped: shared across all smoke tests for performance.
    Opens the shared station database through ``database_dir`` and reaches
    Redis via the 'test-redis' alias on the shared smoke_network.
    Uses tmpfs for workspace directories.
    """
    _require_image("silvasonic_controller")
    # Ensure fixtures are used (dependency ordering)
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_controller")
        .with_exposed_ports(9100)
        .with_volume_mapping(str(database_dir), "/data/database", "z")
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
    database_dir: Path,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated Processor container with the shared database and Redis.

    Session-scoped: shared across all smoke tests for performance.
    Opens the shared station database through ``database_dir`` and reaches
    Redis via the 'test-redis' alias on the shared smoke_network.
    Uses tmpfs for workspace directories (no host writes).
    """
    _require_image("silvasonic_processor")
    # Ensure fixtures are used (dependency ordering)
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_processor")
        .with_exposed_ports(9200)
        .with_volume_mapping(str(database_dir), "/data/database", "z")
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
    database_dir: Path,
    redis_container_smoke: DockerContainer,
) -> Generator[DockerContainer]:
    """Start an isolated BirdNET container with the shared database and Redis."""
    _require_image("silvasonic_birdnet")
    _ = redis_container_smoke

    container = (
        DockerContainer("silvasonic_birdnet")
        .with_exposed_ports(9500)
        .with_volume_mapping(str(database_dir), "/data/database", "z")
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
    database_dir: Path,
) -> Generator[DockerContainer]:
    """Start an isolated DB-Viewer container.

    Function-scoped: fresh container per test.
    Opens the shared station database through ``database_dir``.
    """
    _require_image("silvasonic_db-viewer")

    container = (
        DockerContainer("silvasonic_db-viewer")
        .with_exposed_ports(8002)
        .with_volume_mapping(str(database_dir), "/data/database", "z")
        .with_network(smoke_network)
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(8002))
    wait_for_http(host, port)
    yield container
    container.stop()


# ── Gateway (Caddy) ──────────────────────────────────────────────────────────


# Test-only login for the gateway. The Caddyfile reads SILVASONIC_GATEWAY_USER and
# SILVASONIC_GATEWAY_PASSWORD_HASH (per-installation credentials, see
# scripts/setup.py). The hash is bcrypt of the plaintext below, generated with
# `caddy hash-password --plaintext smoke-test-password`.
_GATEWAY_TEST_USER = "smoke"
_GATEWAY_TEST_PASSWORD = "smoke-test-password"
_GATEWAY_TEST_PASSWORD_HASH = "$2a$14$T0vFTVr0QOSNT4/fbg.h0.GFYp9mdKI8iyDF7IdBndoovRnhW.mVa"


@pytest.fixture()
def gateway_credentials() -> tuple[str, str]:
    """Return the (user, plaintext password) the smoke gateway accepts."""
    return (_GATEWAY_TEST_USER, _GATEWAY_TEST_PASSWORD)


@pytest.fixture()
def gateway_container(
    smoke_network: Network,
) -> Generator[DockerContainer]:
    """Start an isolated Caddy gateway container with a networked web-mock backend.

    Function-scoped: fresh container per test.
    Spins up its own web-mock instance on the smoke_network with the alias
    'web-mock' so that Caddy's reverse_proxy directive can resolve it.
    Mounts the real Caddyfile to validate production routing config.
    """
    _require_image("caddy:2-alpine")
    _require_image("silvasonic_web-mock")

    # Start a web-mock backend that Caddy can proxy to
    backend = (
        DockerContainer("silvasonic_web-mock")
        .with_exposed_ports(8001)
        .with_network(smoke_network)
        .with_network_aliases("web-mock")
    )
    caddyfile = str(Path(__file__).resolve().parents[2] / "services" / "gateway" / "Caddyfile")
    container = (
        DockerContainer("docker.io/library/caddy:2-alpine")
        .with_exposed_ports(80)
        .with_env("SILVASONIC_DOMAIN_NAME", "localhost")
        .with_env("SILVASONIC_GATEWAY_USER", _GATEWAY_TEST_USER)
        .with_env("SILVASONIC_GATEWAY_PASSWORD_HASH", _GATEWAY_TEST_PASSWORD_HASH)
        .with_network(smoke_network)
        .with_network_aliases("test-gateway")
        .with_volume_mapping(caddyfile, "/etc/caddy/Caddyfile", "ro")
    )

    # Stop both containers whatever fails: a Caddy that never comes up used
    # to leave its web-mock backend running after the test.
    backend.start()
    try:
        wait_for_http(backend.get_container_host_ip(), int(backend.get_exposed_port(8001)))
        container.start()
        try:
            wait_for_log(container, "serving initial configuration")
            yield container
        finally:
            container.stop()
    finally:
        backend.stop()
