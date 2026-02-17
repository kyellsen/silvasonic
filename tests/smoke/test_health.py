"""Smoke tests — health probes for all Silvasonic services.

Each test uses testcontainer fixtures (from conftest.py) to spin up
isolated, ephemeral containers with random ports. No conflicts with
the dev stack, no host-filesystem writes, automatic cleanup.
"""

import socket

import httpx
import pytest
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
