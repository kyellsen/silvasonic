"""System tests for Controller Health Reconciliation (Issue 006).

Validates that the Controller's ReconciliationLoop actively monitors
container heartbeat freshness via Redis and intervenes when a container
deadlocks (remains 'running' but stops publishing heartbeats).
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import RestartPolicy, Tier2ServiceSpec
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.reconciler import ReconciliationLoop

from .conftest import (
    PODMAN_SOCKET,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
    TEST_RUN_ID,
    require_recorder_image,
)

pytestmark = [
    pytest.mark.system,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not SOCKET_AVAILABLE,
        reason=f"Podman socket not found at {PODMAN_SOCKET}",
    ),
]


class TestControllerHealthReconciliation:
    """Verify Controller gracefully neutralizes zombie/deadlocked containers."""

    @patch("silvasonic.controller.reconciler.get_session")
    async def test_heartbeat_timeout_triggers_adoption(
        self,
        mock_get_session: Mock,
        tmp_path: Path,
        system_network: str,
        system_redis: tuple[str, int, str],
        system_db: str,
    ) -> None:
        """Controller explicitly stops containers with stale/missing heartbeats.

        1. Start a real container.
        2. Wait for it to exist.
        3. Clear its heartbeat in Redis, simulating a deadlock.
        4. Trigger reconciliation loop.
        5. Verify the Reconciler neutralizes the zombie and replaces it.
        """
        require_recorder_image()

        container_name = f"silvasonic-recorder-zombie-{TEST_RUN_ID}"
        workspace = tmp_path / "zombie-workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=Mock())
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        redis_host_url = f"redis://{system_redis[0]}:{system_redis[1]}/0"
        redis_container_url = f"redis://{system_redis[2]}:6379/0"

        spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=container_name,
            network=system_network,
            environment={
                "SILVASONIC_RECORDER_DEVICE": "hw:0,0",
                "SILVASONIC_RECORDER_MOCK_SOURCE": "true",
                "SILVASONIC_REDIS_URL": redis_container_url,
                "SILVASONIC_INSTANCE_ID": "zombie-device",
                "SILVASONIC_HEARTBEAT_INTERVAL_S": "1.0",
            },
            labels={
                "io.silvasonic.tier": "2",
                "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
                "io.silvasonic.service": "recorder",
                "io.silvasonic.device_id": "zombie-device",
            },
            mounts=[],
            devices=[],
            privileged=False,
            restart_policy=RestartPolicy(name="no", max_retry_count=0),
            memory_limit="128m",
            cpu_limit=1.0,
            oom_score_adj=-999,
        )

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")

            # Use extremely tight timeouts for fast test execution
            reconciler = ReconciliationLoop(
                mgr,
                interval=1.0,
                redis_url=redis_host_url,
                stale_timeout_s=3.0,
            )

            # Mock the hardware/sys evaluators to always desire this single container
            mock_hw_evaluator = Mock()
            mock_hw_evaluator.evaluate = AsyncMock(return_value=[spec])
            reconciler._evaluator = mock_hw_evaluator

            mock_sys_evaluator = Mock()
            mock_sys_evaluator.evaluate = AsyncMock(return_value=[])
            reconciler._sys_evaluator = mock_sys_evaluator

            # Initial sync: starts the container
            await reconciler._reconcile_once()
            running = mgr.get(container_name)
            assert running is not None, "Reconciler failed to start the container"
            original_cid = running["id"]

            # Wait 2 seconds for container to start up and publish heartbeat
            await asyncio.sleep(2.0)

            # Manually simulate deadlock by deleting the heartbeat in redis
            from silvasonic.core.redis import get_redis_connection

            redis = await get_redis_connection(redis_host_url)
            assert redis is not None

            # Prove the container was publishing
            key = "silvasonic:status:zombie-device"
            val = await redis.get(key)
            assert val is not None, "Container never published a heartbeat"

            # Delete the key so the reconciler sees it as missing/stale
            await redis.delete(key)
            await redis.aclose()

            # Second sync: should detect missing heartbeat, kill the old one, and start a new one!
            await reconciler._reconcile_once()

            new_running = mgr.get(container_name)
            assert new_running is not None, "Reconciler did not recreate the container"
            new_cid = new_running["id"]

            assert new_cid != original_cid, (
                "Reconciler did not restart the container! "
                "The container ID is identical, meaning it was not killed."
            )

            # Cleanup
            mgr.stop(container_name)
            mgr.remove(container_name)

        finally:
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            client.close()
