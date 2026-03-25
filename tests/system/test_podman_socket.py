"""System tests: SilvasonicPodmanClient ↔ real Podman socket.

These tests verify real connectivity to the host Podman engine.
They are skipped if the Podman socket is not available.

The socket path is discovered from the ``SILVASONIC_PODMAN_SOCKET``
environment variable or falls back to the standard rootless location.

Moved from ``services/controller/tests/integration/`` because these
tests require a real Podman socket (Stage 10), not testcontainers
(Stage 6).
"""

from __future__ import annotations

import pytest

from .conftest import (
    PODMAN_SOCKET,
    SOCKET_AVAILABLE,
)

pytestmark = [
    pytest.mark.system,
    pytest.mark.skipif(
        not SOCKET_AVAILABLE,
        reason=f"Podman socket not found at {PODMAN_SOCKET}",
    ),
]


class TestPodmanSocketConnection:
    """Verify real Podman socket connectivity."""

    def test_connect_and_ping(self) -> None:
        """Connects to the host Podman socket and pings the engine."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient(socket_path=PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()
        try:
            assert client.is_connected
            assert client.ping() is True
        finally:
            client.close()

    def test_list_containers(self) -> None:
        """Lists containers (may be empty, but must not raise)."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient(socket_path=PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()
        try:
            containers = client.list_containers()
            assert isinstance(containers, list)
        finally:
            client.close()

    def test_list_managed_containers(self) -> None:
        """Lists managed containers (filters by silvasonic label)."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient(socket_path=PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()
        try:
            managed = client.list_managed_containers()
            assert isinstance(managed, list)
            # All returned containers should have the correct label
            for c in managed:
                labels = c["labels"]
                assert isinstance(labels, dict)
                assert labels.get("io.silvasonic.owner") == "controller"
        finally:
            client.close()

    def test_close_and_reconnect(self) -> None:
        """Closes connection and reconnects successfully."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient(socket_path=PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()
        assert client.is_connected

        client.close()
        assert not client.is_connected

        # Reconnect
        client.connect()
        assert client.is_connected
        assert client.ping() is True
        client.close()
