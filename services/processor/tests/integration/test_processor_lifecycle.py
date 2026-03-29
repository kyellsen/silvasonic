"""Integration tests for Processor service lifecycle.

Tests the Processor service against real PostgreSQL (Testcontainer)
and real Redis to verify:
- Service starts and reports healthy via HTTP /healthy endpoint
- Heartbeat is published to Redis within expected timeframe
"""

import json
import subprocess
import time
from collections.abc import Generator

import httpx
import pytest
from silvasonic.test_utils.helpers import wait_for_http, wait_for_log
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network


def _require_image(image: str) -> None:
    """Skip the test if image is not available locally."""
    result = subprocess.run(
        ["podman", "image", "exists", image],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Image '{image}' not found — run 'just build' first")


@pytest.fixture(scope="module")
def integration_network() -> Generator[Network]:
    """Shared network for processor integration tests."""
    with Network() as network:
        yield network


@pytest.fixture(scope="module")
def db_container(integration_network: Network) -> Generator[DockerContainer]:
    """Start a disposable database container with Silvasonic schema."""
    _require_image("silvasonic_database")
    container = (
        DockerContainer("silvasonic_database")
        .with_exposed_ports(5432)
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_network(integration_network)
        .with_network_aliases("test-database")
        .with_kwargs(tmpfs={"/var/lib/postgresql/data": "rw"})
    )
    container.start()
    wait_for_log(container, "database system is ready to accept connections")
    yield container
    container.stop()


@pytest.fixture(scope="module")
def redis_container(integration_network: Network) -> Generator[DockerContainer]:
    """Start a disposable Redis container."""
    container = (
        DockerContainer("docker.io/library/redis:7-alpine")
        .with_exposed_ports(6379)
        .with_command("redis-server --save ''")
        .with_network(integration_network)
        .with_network_aliases("test-redis")
    )
    container.start()
    wait_for_log(container, "Ready to accept connections")
    yield container
    container.stop()


@pytest.fixture(scope="module")
def processor_container(
    integration_network: Network,
    db_container: DockerContainer,
    redis_container: DockerContainer,
) -> Generator[DockerContainer]:
    """Start a Processor container connected to test DB and Redis."""
    _require_image("silvasonic_processor")
    # Ensure fixtures are used (dependency ordering)
    _ = db_container
    _ = redis_container

    container = (
        DockerContainer("silvasonic_processor")
        .with_exposed_ports(9200)
        .with_env("POSTGRES_HOST", "test-database")
        .with_env("POSTGRES_USER", "silvasonic")
        .with_env("POSTGRES_PASSWORD", "silvasonic")
        .with_env("POSTGRES_DB", "silvasonic")
        .with_env("POSTGRES_PORT", "5432")
        .with_env("SILVASONIC_REDIS_URL", "redis://test-redis:6379/0")
        .with_network(integration_network)
        .with_kwargs(tmpfs={"/data/recorder": "rw", "/data/processor": "rw"})
    )
    container.start()
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(9200))
    wait_for_http(host, port)
    yield container
    container.stop()


@pytest.mark.integration
class TestProcessorLifecycle:
    """Verify Processor service lifecycle with real DB and Redis."""

    def test_processor_starts_with_db(
        self,
        processor_container: DockerContainer,
    ) -> None:
        """Processor /healthy returns 200 with status ok."""
        host = processor_container.get_container_host_ip()
        port = int(processor_container.get_exposed_port(9200))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_processor_heartbeat_published(
        self,
        processor_container: DockerContainer,
        redis_container: DockerContainer,
    ) -> None:
        """Processor publishes heartbeat to Redis within 30s."""
        from redis import Redis

        host = redis_container.get_container_host_ip()
        port = int(redis_container.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        deadline = time.monotonic() + 30
        payload = None
        while time.monotonic() < deadline:
            raw = redis_client.get("silvasonic:status:processor")
            if raw is not None:
                payload = json.loads(str(raw))
                break
            time.sleep(2)

        redis_client.close()

        assert payload is not None, "Processor heartbeat not found in Redis within 30s"
        assert payload["service"] == "processor"
        assert payload["instance_id"] == "processor"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]
