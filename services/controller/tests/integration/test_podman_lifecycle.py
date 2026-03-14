"""Integration tests: Full recorder-spawn flow via Reconciliation.

Verifies the end-to-end path: insert a device into the DB → run the
DeviceStateEvaluator → reconcile with ContainerManager → verify a Podman
container is (or would be) started.

These tests are **skipped** when the Podman socket is unavailable.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
from pathlib import Path

import pytest
from silvasonic.controller.container_manager import ContainerManager

# Discover the Podman socket path
_DEFAULT_ROOTLESS_SOCKET = f"/run/user/{os.getuid()}/podman/podman.sock"
_PODMAN_SOCKET = os.environ.get("SILVASONIC_PODMAN_SOCKET", _DEFAULT_ROOTLESS_SOCKET)
_SOCKET_AVAILABLE = pathlib.Path(_PODMAN_SOCKET).exists()

pytestmark = [
    pytest.mark.integration,
]


@pytest.mark.skipif(
    not _SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {_PODMAN_SOCKET}",
)
class TestPodmanLifecycle:
    """Verify ContainerManager can reconcile specs against real Podman.

    These tests require a running Podman socket on the host.
    The lifecycle test additionally requires the recorder image to be built
    locally (``just build``).
    """

    def test_reconcile_with_empty_desired_and_actual(self) -> None:
        """reconcile() with empty inputs succeeds (no-op)."""
        from silvasonic.controller.podman_client import (
            SilvasonicPodmanClient,
        )

        client = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()
        try:
            mgr = ContainerManager(client)
            # No desired specs, no actual containers → no action
            mgr.sync_state(desired=[], actual=[])
            # Should not raise
        finally:
            client.close()

    def test_start_and_stop_recorder_container(self, tmp_path: Path) -> None:
        """Start a real Recorder container, verify it's listed, stop and remove it.

        This is the end-to-end lifecycle test for Phase 4:
        Tier2ServiceSpec → ContainerManager.start → list_managed → stop → remove.
        """
        import subprocess

        from silvasonic.controller.container_spec import (
            MountSpec,
            RestartPolicy,
            Tier2ServiceSpec,
        )
        from silvasonic.controller.podman_client import (
            SilvasonicPodmanClient,
        )

        # Check if recorder image is available
        result = subprocess.run(
            ["podman", "image", "exists", "localhost/silvasonic_recorder:latest"],
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip("Recorder image not built (run 'just build' first)")

        container_name = "silvasonic-recorder-integration-test"
        workspace = tmp_path / "recorder" / "integration-test"
        workspace.mkdir(parents=True, exist_ok=True)

        spec = Tier2ServiceSpec(
            image="localhost/silvasonic_recorder:latest",
            name=container_name,
            network="silvasonic-net",
            environment={
                "SILVASONIC_RECORDER_DEVICE": "hw:99,0",
                "SILVASONIC_RECORDER_PROFILE_SLUG": "test_profile",
                "SILVASONIC_REDIS_URL": "redis://silvasonic-redis:6379/0",
            },
            labels={
                "io.silvasonic.tier": "2",
                "io.silvasonic.owner": "controller",
                "io.silvasonic.service": "recorder",
                "io.silvasonic.device_id": "integration-test",
                "io.silvasonic.profile": "test_profile",
            },
            mounts=[
                MountSpec(
                    source=str(workspace),
                    target="/app/workspace",
                    read_only=False,
                ),
            ],
            devices=[],  # No /dev/snd in test environment
            group_add=[],
            privileged=False,  # No privileged needed for lifecycle test
            restart_policy=RestartPolicy(name="no", max_retry_count=0),
            memory_limit="128m",
            cpu_limit=0.5,
            oom_score_adj=-999,
        )

        client = SilvasonicPodmanClient(
            socket_path=_PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client)

            # 1) Start the container
            info = mgr.start(spec)
            assert info is not None, "start() should return container info"
            assert info.get("name") == container_name

            # 2) Verify it appears in list_managed
            managed = mgr.list_managed()
            managed_names = [str(c.get("name", "")) for c in managed]
            assert container_name in managed_names, (
                f"Container '{container_name}' not in managed list: {managed_names}"
            )

            # 3) Stop the container
            stopped = mgr.stop(container_name)
            assert stopped is True, "stop() should return True"

            # 4) Remove the container
            removed = mgr.remove(container_name)
            assert removed is True, "remove() should return True"

            # 5) Verify it's gone
            assert mgr.get(container_name) is None, "Container should be removed"
        finally:
            # Cleanup: ensure container is removed even if test fails
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            client.close()
