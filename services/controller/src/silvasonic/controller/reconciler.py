"""State reconciliation for Tier 2 containers (ADR-0017).

Implements the Kubernetes-inspired reconciliation pattern:

1. **DeviceStateEvaluator** — determines which devices should have Recorders.
2. **ReconciliationLoop** — periodic async task that compares desired vs. actual.

The Controller reads desired state from the database (``devices`` + ``microphone_profiles``)
and reconciles against actual state from Podman (running containers queried by label).
"""

from __future__ import annotations

import asyncio
from typing import NoReturn

import structlog
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import Tier2ServiceSpec, build_recorder_spec
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import get_session
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


class DeviceStateEvaluator:
    """Evaluate which devices should have running Recorders.

    A device is eligible for recording when ALL conditions are met
    (Controller README §Device State Evaluation):

    - ``status == "online"``
    - ``enabled == True``
    - ``enrollment_status == "enrolled"``
    - ``profile_slug IS NOT NULL``
    """

    async def evaluate(self, session: AsyncSession) -> list[Tier2ServiceSpec]:
        """Query eligible devices and build Tier2ServiceSpecs.

        Returns:
            List of specs for Recorder containers that should be running.
        """
        stmt = select(Device).where(
            and_(
                Device.status == "online",
                Device.enabled.is_(True),
                Device.enrollment_status == "enrolled",
                Device.profile_slug.isnot(None),
            )
        )
        result = await session.execute(stmt)
        devices = result.scalars().all()

        specs: list[Tier2ServiceSpec] = []

        for device in devices:
            # Fetch the linked profile
            profile = await session.get(MicProfileDB, device.profile_slug)
            if profile is None:
                log.warning(
                    "reconciler.missing_profile",
                    device=device.name,
                    slug=device.profile_slug,
                )
                continue

            try:
                spec = build_recorder_spec(device, profile)
                specs.append(spec)
            except Exception:
                log.exception(
                    "reconciler.spec_build_failed",
                    device=device.name,
                )

        log.debug("reconciler.evaluated", eligible_count=len(specs))
        return specs


class ReconciliationLoop:
    """Periodic reconciliation loop (~30s) comparing desired vs. actual state.

    Follows the State Reconciliation Pattern (ADR-0017, messaging_patterns.md §6).
    Can be triggered immediately via the ``trigger()`` method (from NudgeSubscriber).
    """

    def __init__(
        self,
        container_manager: ContainerManager,
        interval: float = 30.0,
    ) -> None:
        """Initialize with a ContainerManager and reconciliation interval."""
        self._manager = container_manager
        self._evaluator = DeviceStateEvaluator()
        self._interval = interval
        self._trigger_event = asyncio.Event()

    def trigger(self) -> None:
        """Trigger an immediate reconciliation cycle (called by NudgeSubscriber)."""
        self._trigger_event.set()

    async def run(self) -> NoReturn:
        """Run the reconciliation loop until cancelled.

        On each cycle:
        1. Query DB for desired state (eligible devices).
        2. Query Podman for actual state (running containers).
        3. Reconcile: start missing, stop orphaned.
        """
        while True:
            try:
                await self._reconcile_once()
            except Exception:
                log.exception("reconciler.cycle_failed")

            # Wait for interval OR immediate trigger
            try:
                await asyncio.wait_for(
                    self._trigger_event.wait(),
                    timeout=self._interval,
                )
            except TimeoutError:
                pass
            finally:
                self._trigger_event.clear()

    async def _reconcile_once(self) -> None:
        """Execute a single reconciliation cycle."""
        async with get_session() as session:
            desired = await self._evaluator.evaluate(session)

        actual = await asyncio.to_thread(self._manager.list_managed)

        await asyncio.to_thread(
            self._manager.reconcile,
            desired,
            actual,
        )
