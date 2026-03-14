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
from silvasonic.controller.device_scanner import DeviceScanner, upsert_device
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import get_session
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# TODO(production): Consider increasing to 3.0s if CPU/DB load is too high.
# Each cycle does: procfs read + 2-3 DB roundtrips + 1 Podman API call.
# At 1s → ~180 DB queries/min.  At 3s → ~60.  UX difference is negligible.
# UI actions (enable/disable) are always instant via NudgeSubscriber (Redis).
DEFAULT_RECONCILE_INTERVAL_S: float = 1.0
"""Default interval (seconds) between reconciliation cycles."""


class DeviceStateEvaluator:
    """Evaluate which devices should have running Recorders.

    A device is eligible for recording when ALL conditions are met
    (Controller README §Device State Evaluation):

    - ``status == "online"``
    - ``enabled == True``
    - ``enrollment_status == "enrolled"``
    - ``profile_slug IS NOT NULL``
    """

    def __init__(self) -> None:
        """Initialize with empty rate-limiting set for missing profiles."""
        self._warned_profiles: set[str] = set()

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
                cache_key = f"{device.name}:{device.profile_slug}"
                if cache_key not in self._warned_profiles:
                    log.warning(
                        "reconciler.missing_profile",
                        device=device.name,
                        slug=device.profile_slug,
                    )
                    self._warned_profiles.add(cache_key)
                else:
                    log.debug(
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
    """Periodic reconciliation loop comparing desired vs. actual state.

    Follows the State Reconciliation Pattern (ADR-0017, messaging_patterns.md §6).
    Can be triggered immediately via the ``trigger()`` method (from NudgeSubscriber).

    Each cycle:
    1. Rescan hardware (scan_all → match → upsert) to keep the DB in sync.
    2. Evaluate desired state from DB (online + enrolled + profiled devices).
    3. Compare desired vs. actual Podman containers → start/stop as needed.
    """

    def __init__(
        self,
        container_manager: ContainerManager,
        *,
        device_scanner: DeviceScanner | None = None,
        profile_matcher: ProfileMatcher | None = None,
        interval: float = DEFAULT_RECONCILE_INTERVAL_S,
    ) -> None:
        """Initialize with a ContainerManager and reconciliation interval."""
        self._manager = container_manager
        self._evaluator = DeviceStateEvaluator()
        self._scanner = device_scanner
        self._matcher = profile_matcher
        self._interval = interval
        self._trigger_event = asyncio.Event()

    def trigger(self) -> None:
        """Trigger an immediate reconciliation cycle (called by NudgeSubscriber)."""
        self._trigger_event.set()

    async def run(self) -> NoReturn:
        """Run the reconciliation loop until cancelled.

        On each cycle:
        1. Rescan hardware and sync device state to DB.
        2. Query DB for desired state (eligible devices).
        3. Query Podman for actual state (running containers).
        4. Reconcile: start missing, stop orphaned.
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
        # Step 1: Rescan hardware → persist to DB (if scanner available)
        if self._scanner is not None:
            await self._rescan_hardware()

        # Step 2: Evaluate desired state from DB
        async with get_session() as session:
            desired = await self._evaluator.evaluate(session)

        # Step 3: Get actual running containers
        actual = await asyncio.to_thread(self._manager.list_managed)

        # Step 4: Reconcile desired vs. actual
        await asyncio.to_thread(
            self._manager.reconcile,
            desired,
            actual,
        )

    async def _rescan_hardware(self) -> None:
        """Rescan USB audio devices and sync state to DB.

        Detects newly connected and disconnected devices, updates their
        status in the database, and matches profiles for new devices.
        """
        if self._scanner is None:
            return

        devices = await asyncio.to_thread(self._scanner.scan_all)
        current_ids = {d.stable_device_id for d in devices}

        async with get_session() as session:
            # Upsert all detected devices
            for device_info in devices:
                if self._matcher is not None:
                    match_result = await self._matcher.match(device_info, session)
                    profile_slug = match_result.profile_slug if match_result.auto_enroll else None
                    enrollment = "enrolled" if match_result.auto_enroll else "pending"
                else:
                    profile_slug = None
                    enrollment = "pending"

                await upsert_device(
                    device_info,
                    session,
                    profile_slug=profile_slug,
                    enrollment_status=enrollment,
                )

            # Mark devices that are no longer detected as offline
            result = await session.execute(select(Device).where(Device.status == "online"))
            online_devices = result.scalars().all()

            for device in online_devices:
                if device.name not in current_ids:
                    device.status = "offline"
                    log.info("reconciler.device_offline", device_id=device.name)

            await session.commit()

        log.debug(
            "reconciler.hardware_rescan",
            devices_found=len(devices),
        )
