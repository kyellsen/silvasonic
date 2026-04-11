"""System lifecycle tests for Singleton Tier-2 Workers (BirdNET).

Tests the Controller's ability to start and stop background worker containers
like BirdNET based on the `enabled` state in the `managed_services` database table,
using a real Podman socket and testcontainers PostgreSQL.

Skip conditions:
- Podman socket not available → all tests skipped
- BirdNET image not built → container tests skipped
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.reconciler import ReconciliationLoop
from silvasonic.controller.seeder import ConfigSeeder
from silvasonic.controller.worker_evaluator import SystemWorkerEvaluator
from silvasonic.core.database.models.system import ManagedService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    PODMAN_SOCKET,
    SOCKET_AVAILABLE,
    seed_test_defaults,
)

pytestmark = [
    pytest.mark.system,
]


def require_birdnet_image() -> None:
    """Skip the test if the BirdNET image is not built."""
    result = subprocess.run(
        ["podman", "image", "exists", "localhost/silvasonic_birdnet:latest"],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("BirdNET image not built (run 'just build' first)")


class MockDeviceStateEvaluator:
    """Mock Hardware evaluator to isolate testing to the SystemWorkerEvaluator."""

    async def evaluate(self, session: AsyncSession) -> list[Any]:
        return []


@pytest.mark.skipif(
    not SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {PODMAN_SOCKET}",
)
class TestSingletonWorkerLifecycle:
    """Verify Controller can start/stop BirdNET containers via DB state."""

    async def test_reconcile_starts_and_stops_birdnet(
        self,
        tmp_path: Path,
        system_network: str,
        session_factory: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Integration from DB to Podman for Tier 2 Background Worker."""
        require_birdnet_image()

        # Phase 1: Setup test environment
        monkeypatch.setenv("SILVASONIC_NETWORK", system_network)

        # Seed defaults to prepare required configs
        defaults_path = seed_test_defaults(tmp_path)
        async with session_factory() as session:
            await ConfigSeeder(defaults_path=defaults_path).seed(session)
            await session.commit()

        # Connect Podman Client
        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile="controller")

            # Instantiate ReconciliationLoop with real SystemWorkerEvaluator, mock HW evaluator
            sys_evaluator = SystemWorkerEvaluator()
            hw_evaluator = MockDeviceStateEvaluator()

            loop = ReconciliationLoop(
                mgr,
                hardware_evaluator=hw_evaluator,  # type: ignore
                sys_evaluator=sys_evaluator,
                interval=1.0,
            )

            # Phase 2: Start BirdNET via DB state
            # Insert ManagedService for BirdNET with enabled=True
            async with session_factory() as session:
                session.add(ManagedService(name="birdnet", enabled=True))
                await session.commit()

            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def mock_get_session():
                async with session_factory() as s:
                    yield s

            with patch(
                "silvasonic.controller.reconciler.get_session", side_effect=mock_get_session
            ):
                # Run loop
                await loop._reconcile_once()

            # Assert: BirdNET container should now be running
            worker_name = "silvasonic-birdnet"
            running_info = mgr.get(worker_name)

            assert running_info is not None, (
                f"Container '{worker_name}' should be started by sync_state"
            )
            assert running_info.get("status") == "running", (
                f"Container '{worker_name}' must be running"
            )

            # Check that it has the correct network and labels
            labels = running_info.get("labels", {})
            assert isinstance(labels, dict)
            assert labels.get("io.silvasonic.tier") == "2"
            assert labels.get("io.silvasonic.service") == "birdnet"

            # Phase 3: Stop BirdNET via DB state
            # Update ManagedService to enabled=False
            async with session_factory() as session:
                birdnet_svc = await session.get(ManagedService, "birdnet")
                assert birdnet_svc is not None
                birdnet_svc.enabled = False
                await session.commit()

            # Execute another reconciliation cycle
            with patch(
                "silvasonic.controller.reconciler.get_session", side_effect=mock_get_session
            ):
                await loop._reconcile_once()

            # Assert: BirdNET container should be stopped and removed
            stopped_info = mgr.get(worker_name)
            assert stopped_info is None, (
                f"Container '{worker_name}' should have been removed by sync_state"
            )

        finally:
            # Cleanup safeguard if test fails midway
            with contextlib.suppress(Exception):
                client.containers.get("silvasonic-birdnet").remove(force=True)
            client.close()
