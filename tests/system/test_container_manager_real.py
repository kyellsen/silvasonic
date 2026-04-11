"""System regression tests: ContainerManager boundary against a real Podman socket.

This supplements the unit tests which mock Podman. By issuing commands to
a genuine Podman engine, we guarantee that the Podman REST API syntax
(like `read_only=True` mapping to correct mount kwargs) is actually accepted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import MountSpec, RestartPolicy, Tier2ServiceSpec
from silvasonic.controller.podman_client import SilvasonicPodmanClient

from .conftest import PODMAN_SOCKET, SOCKET_AVAILABLE

pytestmark = [
    pytest.mark.system,
    pytest.mark.skipif(
        not SOCKET_AVAILABLE,
        reason=f"Podman socket not found at {PODMAN_SOCKET}",
    ),
]


def test_real_container_manager_mount_options(tmp_path: Path) -> None:
    """Regression test against Podman REST API 500 error for mount options.

    Verifies that ContainerManager can successfully map both read-only
    and read-write MountSpecs to a genuine Podman socket without the
    engine rejecting the request syntax (e.g. invalid 'ro,z' concatenation).
    """
    client = SilvasonicPodmanClient(socket_path=PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
    client.connect()
    assert client.is_connected

    # Create dummy host directories
    ro_dir = tmp_path / "ro_data"
    rw_dir = tmp_path / "rw_data"
    ro_dir.mkdir()
    rw_dir.mkdir()

    # Define minimal spec with both mount types
    spec = Tier2ServiceSpec(
        image="localhost/silvasonic_recorder:latest",
        name="silvasonic-system-test-mounts",
        network="podman",  # Standard rootless podman network
        memory_limit="64m",
        cpu_limit=0.5,
        oom_score_adj=500,
        restart_policy=RestartPolicy(name="no", max_retry_count=0),
        labels={"io.silvasonic.owner": "test"},
        mounts=[
            MountSpec(source=str(ro_dir), target="/mnt/ro", read_only=True),
            MountSpec(source=str(rw_dir), target="/mnt/rw", read_only=False),
        ],
    )

    manager = ContainerManager(client, owner_profile="test")

    try:
        # Start container. This triggers the POST to the Docker/Podman compatible API.
        # If the mount options are syntaktisch invalide, this will throw an APIError.
        container_info = manager.start(spec)
        assert container_info is not None, "Container failed to start"
        assert container_info["name"] == spec.name

    finally:
        # Cleanup
        manager.stop_and_remove(spec.name, timeout=1)
        client.close()
