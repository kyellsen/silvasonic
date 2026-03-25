"""Smoke tests — health probes and heartbeat verification for all Silvasonic services.

Each test uses testcontainer fixtures (from conftest.py) to spin up
isolated, ephemeral containers with random ports. No conflicts with
the dev stack, no host-filesystem writes, automatic cleanup.
"""

import json
import socket
import time
from typing import Any

import httpx
import pytest
from redis import Redis
from testcontainers.core.container import DockerContainer


@pytest.mark.smoke
class TestServiceHealth:
    """Verify all services respond to health probes via testcontainers."""

    def test_database_healthy(self, database_container: DockerContainer) -> None:
        """Database accepts TCP connections on its exposed port."""
        host = database_container.get_container_host_ip()
        port = int(database_container.get_exposed_port(5432))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            result = sock.connect_ex((host, port))
            assert result == 0, f"Database not reachable on {host}:{port}"
        finally:
            sock.close()

    def test_controller_healthy(self, controller_container: DockerContainer) -> None:
        """Controller /healthy returns 200 with status ok."""
        host = controller_container.get_container_host_ip()
        port = int(controller_container.get_exposed_port(9100))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_recorder_healthy(self, recorder_container: DockerContainer) -> None:
        """Recorder /healthy returns 200 with status ok."""
        host = recorder_container.get_container_host_ip()
        port = int(recorder_container.get_exposed_port(9500))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_web_mock_healthy(self, web_mock_container: DockerContainer) -> None:
        """Web-Mock /healthy returns 200 with status ok."""
        host = web_mock_container.get_container_host_ip()
        port = int(web_mock_container.get_exposed_port(8001))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def _poll_redis_key(redis_client: Redis, key: str, timeout: float = 30.0) -> dict[str, Any]:
    """Poll Redis for a key until it exists or timeout. Returns parsed JSON."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = redis_client.get(key)
        if raw is not None:
            return json.loads(str(raw))  # type: ignore[no-any-return]
        time.sleep(2)
    msg = f"Redis key '{key}' not found within {timeout}s"
    raise TimeoutError(msg)


@pytest.mark.smoke
class TestServiceHeartbeats:
    """Verify services publish heartbeats to Redis (container-to-container)."""

    def test_controller_heartbeat_in_redis(
        self,
        controller_container: DockerContainer,
        redis_container_smoke: DockerContainer,
    ) -> None:
        """Controller writes a heartbeat to Redis with host_resources."""
        # Connect to Redis from the test host (via exposed port)
        host = redis_container_smoke.get_container_host_ip()
        port = int(redis_container_smoke.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        payload = _poll_redis_key(redis_client, "silvasonic:status:controller")

        assert payload["service"] == "controller"
        assert payload["instance_id"] == "controller"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]
        assert "host_resources" in payload["meta"], (
            "Controller heartbeat should include host_resources"
        )

        redis_client.close()

    def test_recorder_heartbeat_in_redis(
        self,
        recorder_container: DockerContainer,
        redis_container_smoke: DockerContainer,
    ) -> None:
        """Recorder writes a heartbeat to Redis."""
        host = redis_container_smoke.get_container_host_ip()
        port = int(redis_container_smoke.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        payload = _poll_redis_key(redis_client, "silvasonic:status:recorder")

        assert payload["service"] == "recorder"
        assert payload["instance_id"] == "recorder"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]
        # Phase 4: dual-stream flags must be present in heartbeat
        assert "recording" in payload["meta"]
        assert "raw_enabled" in payload["meta"]["recording"]
        assert "processed_enabled" in payload["meta"]["recording"]

        redis_client.close()
