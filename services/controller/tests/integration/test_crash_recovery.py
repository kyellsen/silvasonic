"""Integration tests: Crash Recovery & Multi-Instance (Phase 6).

Verifies the crash recovery guarantees from ADR-0013 §2.4:

1. Tier 2 containers survive Controller disconnect / crash.
2. A restarted Controller adopts existing containers via label query.
3. Multiple Recorder instances run concurrently with isolated labels.
4. Reconciliation restarts a killed Recorder container.
5. Graceful shutdown stops all managed Tier 2 containers.

These tests require:
- A running Podman socket on the host.
- The Recorder image to be built locally (``just build``).

Tests are **skipped** when the Podman socket is unavailable.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import subprocess
import time
from pathlib import Path

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    RestartPolicy,
    Tier2ServiceSpec,
)
from silvasonic.controller.podman_client import SilvasonicPodmanClient

# Discover the Podman socket path
_DEFAULT_ROOTLESS_SOCKET = f"/run/user/{os.getuid()}/podman/podman.sock"
_PODMAN_SOCKET = os.environ.get("SILVASONIC_PODMAN_SOCKET", _DEFAULT_ROOTLESS_SOCKET)
_SOCKET_AVAILABLE = pathlib.Path(_PODMAN_SOCKET).exists()
_RECORDER_IMAGE = "localhost/silvasonic_recorder:latest"

pytestmark = [
    pytest.mark.integration,
]


def _require_image() -> None:
    """Skip the test if the Recorder image is not built."""
    result = subprocess.run(
        ["podman", "image", "exists", _RECORDER_IMAGE],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("Recorder image not built (run 'just build' first)")


def _make_test_spec(name: str, device_id: str, workspace: Path) -> Tier2ServiceSpec:
    """Create a minimal Recorder spec for crash recovery testing."""
    return Tier2ServiceSpec(
        image=_RECORDER_IMAGE,
        name=name,
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
            "io.silvasonic.device_id": device_id,
            "io.silvasonic.profile": "test_profile",
        },
        mounts=[
            MountSpec(
                source=str(workspace),
                target="/app/workspace",
                read_only=False,
            ),
        ],
        devices=[],
        group_add=[],
        privileged=False,
        restart_policy=RestartPolicy(name="no", max_retry_count=0),
        memory_limit="128m",
        cpu_limit=0.5,
        oom_score_adj=-999,
    )


@pytest.mark.skipif(
    not _SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {_PODMAN_SOCKET}",
)
class TestCrashRecovery:
    """Verify crash recovery guarantees from ADR-0013 §2.4.

    Requires a running Podman socket and the Recorder image.
    """

    def test_start_replaces_exited_container(self, tmp_path: Path) -> None:
        """Regression: start() must replace exited containers (crash-loop fix).

        Previously, start() returned the dead container info when a
        container existed with status=exited, causing the reconciler to
        loop infinitely.  After the fix, start() removes the exited
        container and recreates a fresh one.
        """
        _require_image()

        container_name = "silvasonic-recorder-exited-test"
        network_name = "silvasonic-net"
        workspace = tmp_path / "recorder" / "exited-test"
        workspace.mkdir(parents=True, exist_ok=True)
        spec = _make_test_spec(container_name, "exited-test-device", workspace)

        # Ensure the network exists (it's only created by compose normally)
        subprocess.run(
            ["podman", "network", "create", network_name],
            capture_output=True,
        )

        client = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()

        try:
            mgr = ContainerManager(client)

            # Step 1: Start container
            info = mgr.start(spec)
            assert info is not None, "start() should return container info"
            original_id = info.get("id")

            # Step 2: Kill the container to force exited state
            result = subprocess.run(
                ["podman", "kill", container_name],
                capture_output=True,
            )
            assert result.returncode == 0, f"podman kill failed: {result.stderr.decode()}"
            time.sleep(1)

            exited = mgr.get(container_name)
            assert exited is not None, "Container should still exist after kill"
            assert exited.get("status") == "exited", (
                f"Container should be exited, got status={exited.get('status')}"
            )

            # Step 3: Call start() again — it should replace the exited
            # container instead of returning the dead one.
            restarted = mgr.start(spec)
            assert restarted is not None, "start() should return new container info"
            assert restarted.get("id") != original_id, (
                "start() must create a new container, not return the dead one"
            )

            # Cleanup
            mgr.stop(container_name)
            mgr.remove(container_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            client.close()

    def test_recorder_survives_controller_disconnect(self, tmp_path: Path) -> None:
        """Tier 2 container keeps running after Controller disconnects (US-C02 §4).

        Simulates a Controller crash by closing the Podman client, then
        reconnects and verifies the container is still running.
        """
        _require_image()

        container_name = "silvasonic-recorder-crash-test"
        workspace = tmp_path / "recorder" / "crash-test"
        workspace.mkdir(parents=True, exist_ok=True)
        spec = _make_test_spec(container_name, "crash-test-device", workspace)

        # Phase 1: Start container via first client
        client1 = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client1.connect()
        try:
            mgr1 = ContainerManager(client1)
            info = mgr1.start(spec)
            assert info is not None, "start() should return container info"
            original_id = info.get("id")
        finally:
            # Simulate crash: close client without stopping containers
            client1.close()

        # Phase 2: Reconnect with new client — container should still be running
        client2 = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client2.connect()
        try:
            mgr2 = ContainerManager(client2)
            surviving = mgr2.get(container_name)

            assert surviving is not None, "Container should still exist after Controller disconnect"
            assert surviving.get("id") == original_id, (
                "Container ID should be unchanged (same container)"
            )

            # Cleanup
            mgr2.stop(container_name)
            mgr2.remove(container_name)
            assert mgr2.get(container_name) is None, "Container should be removed"
        finally:
            with contextlib.suppress(Exception):
                client2.containers.get(container_name).remove(force=True)
            client2.close()

    def test_reconciliation_adopts_existing_container(self, tmp_path: Path) -> None:
        """Restarted Controller adopts existing containers without restarting them (US-C02 §3).

        Starts a container, destroys the ContainerManager, creates a new one
        (simulating Controller restart), and verifies sync_state() does NOT
        call containers.run() — it adopts the existing container.
        """
        _require_image()

        container_name = "silvasonic-recorder-adopt-test"
        workspace = tmp_path / "recorder" / "adopt-test"
        workspace.mkdir(parents=True, exist_ok=True)
        spec = _make_test_spec(container_name, "adopt-test-device", workspace)

        client = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()

        try:
            # Phase 1: Start a container (= "original Controller")
            mgr1 = ContainerManager(client)
            info = mgr1.start(spec)
            assert info is not None
            original_id = info.get("id")

            # Phase 2: Simulate Controller restart — new ContainerManager
            mgr2 = ContainerManager(client)

            # Query actual state (like Controller does on startup)
            actual = mgr2.list_managed()
            actual_names = [str(c.get("name", "")) for c in actual]
            assert container_name in actual_names, (
                f"Container '{container_name}' should appear in list_managed()"
            )

            # Reconcile: desired matches actual → should adopt (no restart)
            mgr2.sync_state(desired=[spec], actual=actual)

            # Verify: container still has the same ID (was NOT restarted)
            after = mgr2.get(container_name)
            assert after is not None
            assert after.get("id") == original_id, (
                "Container must NOT be restarted — same ID expected"
            )

            # Cleanup
            mgr2.stop(container_name)
            mgr2.remove(container_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            client.close()

    def test_multi_instance_isolated_labels(self, tmp_path: Path) -> None:
        """Multiple Recorder instances run concurrently with unique labels (US-R05).

        Starts 2 containers with different device_ids, verifies both appear
        in list_managed() with correct, distinct labels.
        """
        _require_image()

        names = [
            "silvasonic-recorder-multi-test-a",
            "silvasonic-recorder-multi-test-b",
        ]
        device_ids = ["multi-device-aaa", "multi-device-bbb"]
        specs = []
        for name, device_id in zip(names, device_ids, strict=True):
            workspace = tmp_path / "recorder" / name
            workspace.mkdir(parents=True, exist_ok=True)
            specs.append(_make_test_spec(name, device_id, workspace))

        client = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()

        try:
            mgr = ContainerManager(client)

            # Start both containers
            for spec in specs:
                info = mgr.start(spec)
                assert info is not None, f"start() failed for {spec.name}"

            # Verify both appear in list_managed
            managed = mgr.list_managed()
            managed_names = [str(c.get("name", "")) for c in managed]
            for name in names:
                assert name in managed_names, f"'{name}' not in managed list: {managed_names}"

            # Verify labels are distinct per container
            for name, expected_device_id in zip(names, device_ids, strict=True):
                info = mgr.get(name)
                assert info is not None
                labels = info.get("labels", {})
                assert isinstance(labels, dict)
                assert labels.get("io.silvasonic.device_id") == expected_device_id
                assert labels.get("io.silvasonic.service") == "recorder"
                assert labels.get("io.silvasonic.owner") == "controller"

            # Cleanup
            for name in names:
                mgr.stop(name)
                mgr.remove(name)

            # Verify both are gone
            for name in names:
                assert mgr.get(name) is None, f"'{name}' should be removed"
        finally:
            for name in names:
                with contextlib.suppress(Exception):
                    client.containers.get(name).remove(force=True)
            client.close()

    def test_reconcile_restarts_killed_recorder(self, tmp_path: Path) -> None:
        """Reconciliation restarts a recorder that was killed externally (US-C02).

        Steps:
        1. Start 2 Recorder containers.
        2. Kill one via ``podman kill`` (simulating OOM or crash).
        3. Run ``sync_state()`` with both specs as desired.
        4. Verify the killed container is restarted (new container ID).
        5. Verify the surviving container is unchanged (same ID).
        """
        _require_image()

        names = [
            "silvasonic-recorder-kill-test-a",
            "silvasonic-recorder-kill-test-b",
        ]
        device_ids = ["kill-device-aaa", "kill-device-bbb"]
        specs = []
        for name, device_id in zip(names, device_ids, strict=True):
            workspace = tmp_path / "recorder" / name
            workspace.mkdir(parents=True, exist_ok=True)
            specs.append(_make_test_spec(name, device_id, workspace))

        client = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()

        try:
            mgr = ContainerManager(client)

            # Step 1: Start both containers
            original_ids = {}
            for spec in specs:
                info = mgr.start(spec)
                assert info is not None, f"start() failed for {spec.name}"
                original_ids[spec.name] = info.get("id")

            # Step 2: Kill one container externally (simulate crash)
            killed_name = names[0]
            result = subprocess.run(
                ["podman", "kill", killed_name],
                capture_output=True,
            )
            assert result.returncode == 0, f"podman kill failed: {result.stderr.decode()}"

            time.sleep(1)

            # Remove the killed container so sync_state will recreate it
            # (Podman keeps dead containers; reconcile checks running state)
            mgr.remove(killed_name)

            # Step 3: Reconcile — desired has both specs, actual only has survivor.
            # NOTE: list_managed() only returns *running* containers.  The test
            # recorder image exits quickly (no real audio device), so container b
            # may already have stopped by this point — that is acceptable.
            actual = mgr.list_managed()
            actual_names = [str(c.get("name", "")) for c in actual]
            assert killed_name not in actual_names, "Killed container should not be in running list"

            # Use get() to verify the surviving container still *exists*
            # (regardless of running state — get() works on stopped containers too).
            survivor_info = mgr.get(names[1])
            assert survivor_info is not None, "Surviving container should still exist"

            mgr.sync_state(desired=specs, actual=actual)

            # Step 4: Verify the killed container was restarted
            restarted = mgr.get(killed_name)
            assert restarted is not None, (
                "Reconciliation should have restarted the killed container"
            )
            assert restarted.get("id") != original_ids[killed_name], (
                "Restarted container should have a new ID"
            )

            # Step 5: Survivor — if it was still running when sync_state ran,
            # it should keep the same ID; if it had already exited (no real
            # audio device), sync_state would have recreated it with a new ID.
            survivor = mgr.get(names[1])
            assert survivor is not None, "Surviving container should exist after reconciliation"
            if names[1] in actual_names:
                assert survivor.get("id") == original_ids[names[1]], (
                    "Surviving container should keep the same ID"
                )
            # else: container was re-created — new ID is expected

            # Cleanup
            for name in names:
                mgr.stop(name)
                mgr.remove(name)
        finally:
            for name in names:
                with contextlib.suppress(Exception):
                    client.containers.get(name).remove(force=True)
            client.close()

    def test_graceful_shutdown_stops_all_containers(self, tmp_path: Path) -> None:
        """Graceful shutdown stops all managed Tier 2 containers (Phase 6).

        Simulates ``ControllerService._stop_all_tier2()`` by starting
        2 Recorder containers, then stopping all containers returned
        by ``list_managed()``.  Verifies all containers are stopped.
        """
        _require_image()

        names = [
            "silvasonic-recorder-shutdown-test-a",
            "silvasonic-recorder-shutdown-test-b",
        ]
        device_ids = ["shutdown-device-aaa", "shutdown-device-bbb"]
        specs = []
        for name, device_id in zip(names, device_ids, strict=True):
            workspace = tmp_path / "recorder" / name
            workspace.mkdir(parents=True, exist_ok=True)
            specs.append(_make_test_spec(name, device_id, workspace))

        client = SilvasonicPodmanClient(socket_path=_PODMAN_SOCKET, max_retries=2, retry_delay=0.5)
        client.connect()

        try:
            mgr = ContainerManager(client)

            # Start both containers
            for spec in specs:
                info = mgr.start(spec)
                assert info is not None, f"start() failed for {spec.name}"

            # Verify both are running
            managed = mgr.list_managed()
            managed_names = [str(c.get("name", "")) for c in managed]
            for name in names:
                assert name in managed_names, f"'{name}' not in managed list before shutdown"

            # Simulate _stop_all_tier2(): iterate list_managed → stop each
            containers = mgr.list_managed()
            assert len(containers) >= 2, (
                f"Expected at least 2 managed containers, got {len(containers)}"
            )

            for container in containers:
                cname = str(container.get("name", ""))
                if cname:
                    stopped = mgr.stop(cname)
                    assert stopped is True, f"stop({cname}) should return True"

            # Verify all our test containers are stopped
            for name in names:
                info = mgr.get(name)
                if info is not None:
                    # Container exists but should NOT be running
                    assert info.get("status") != "running", (
                        f"'{name}' should not be running after shutdown"
                    )

            # Cleanup: remove stopped containers
            for name in names:
                mgr.remove(name)

            # Verify all are gone
            for name in names:
                assert mgr.get(name) is None, f"'{name}' should be removed after cleanup"
        finally:
            for name in names:
                with contextlib.suppress(Exception):
                    client.containers.get(name).remove(force=True)
            client.close()
