"""State reconciliation for Tier 2 containers (ADR-0017).

Implements the Kubernetes-inspired reconciliation pattern:

1. **DeviceStateEvaluator** — determines which devices should have Recorders.
2. **ReconciliationLoop** — periodic async task that compares desired vs. actual.

The Controller reads desired state from the database (``devices`` + ``microphone_profiles``)
and reconciles against actual state from Podman (running containers queried by label).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, NoReturn

import structlog
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    Tier2ServiceSpec,
    build_recorder_spec,
    generate_workspace_name,
)
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceScanner
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.worker_evaluator import SystemWorkerEvaluator
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import get_session
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from silvasonic.controller.controller_stats import ControllerStats
    from silvasonic.controller.device_scanner import DeviceInfo

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
        hardware_evaluator: DeviceStateEvaluator | None = None,
        sys_evaluator: SystemWorkerEvaluator | None = None,
        interval: float,
        grace_period_s: float = 3.0,
        redis_url: str | None = None,
        stale_timeout_s: float = 45.0,
    ) -> None:
        """Initialize with a ContainerManager and reconciliation interval."""
        self._manager = container_manager
        self._evaluator = hardware_evaluator or DeviceStateEvaluator()
        self._sys_evaluator = sys_evaluator or SystemWorkerEvaluator()
        self._scanner = device_scanner
        self._matcher = profile_matcher
        self._interval = interval
        self._grace_period_s = grace_period_s
        self._redis_url = redis_url
        self._stale_timeout_s = stale_timeout_s
        self._missing_devices: dict[str, float] = {}
        self._trigger_event = asyncio.Event()
        self._stats: ControllerStats | None = None

    def set_stats(self, stats: ControllerStats) -> None:
        """Wire a ControllerStats instance for cycle tracking."""
        self._stats = stats

    def trigger(self) -> None:
        """Trigger an immediate reconciliation cycle (called by NudgeSubscriber)."""
        self._trigger_event.set()

    async def _run_cycle_once(self) -> None:
        """Execute exactly one reconciliation cycle and record stats.

        This method encapsulates a single execution of the reconcile logic and
        the bookkeeping of success/error statistics. It ensures that the stats
        contracts can be tested in isolation from the infinite run loop and
        its timeout mechanics.
        """
        try:
            await self._reconcile_once()
            if self._stats is not None:
                self._stats.record_reconcile_cycle()
        except Exception:
            log.exception("reconciler.cycle_failed")
            if self._stats is not None:
                self._stats.record_reconcile_error()

    async def run(self) -> NoReturn:
        """Run the reconciliation loop until cancelled.

        On each cycle:
        1. Rescan hardware and sync device state to DB.
        2. Query DB for desired state (eligible devices).
        3. Query Podman for actual state (running containers).
        4. Reconcile: start missing, stop orphaned.
        """
        while True:
            await self._run_cycle_once()

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
        # Step 1: Rescan hardware → persist to DB
        if self._scanner is not None:
            await self._rescan_hardware()

        # Step 2: Evaluate desired state from DB
        desired: list[Tier2ServiceSpec] = []
        async with get_session() as session:
            try:
                hardware_specs = await self._evaluator.evaluate(session)
                desired.extend(hardware_specs)
            except Exception:
                log.exception("reconciler.hardware_evaluator_failed")

            try:
                worker_specs = await self._sys_evaluator.evaluate(session)
                desired.extend(worker_specs)
            except Exception:
                log.exception("reconciler.worker_evaluator_failed")

        # Step 3: Get actual running containers
        actual = await asyncio.to_thread(self._manager.list_managed)

        # Step 3.5: Health Evaluation (Issue 006)
        # Verify heartbeat freshness via Redis. If a container is "running" but its
        # heartbeat is missing or stale, it's unhealthy (e.g. deadlocked).
        # We actively stop it and exclude it from `actual`, so `sync_state` recreates it.
        if self._redis_url:
            import json

            from silvasonic.core.redis import get_redis_connection

            redis = await get_redis_connection(self._redis_url)
            if redis is not None:
                healthy_actual = []
                now = time.time()
                for c in actual:
                    name = str(c.get("name", ""))
                    labels = c.get("labels", {})
                    device_id = (
                        labels.get("io.silvasonic.device_id") if isinstance(labels, dict) else None
                    )
                    if not device_id:
                        healthy_actual.append(c)
                        continue

                    key = f"silvasonic:status:{device_id}"
                    val = await redis.get(key)
                    is_healthy = True

                    if not val:
                        # No heartbeat in Redis
                        log.warning(
                            "reconciler.heartbeat_missing", container=name, device_id=device_id
                        )
                        is_healthy = False
                    else:
                        try:
                            payload = json.loads(val)
                            timestamp = payload.get("timestamp", 0.0)
                            if now - timestamp > self._stale_timeout_s:
                                log.warning(
                                    "reconciler.heartbeat_stale",
                                    container=name,
                                    device_id=device_id,
                                    age_s=round(now - timestamp, 1),
                                )
                                is_healthy = False
                            elif payload.get("health", {}).get("status") not in ("ok", "starting"):
                                log.warning(
                                    "reconciler.heartbeat_reports_error",
                                    container=name,
                                    device_id=device_id,
                                )
                                is_healthy = False
                        except Exception:
                            log.warning("reconciler.heartbeat_invalid", container=name)
                            is_healthy = False

                    if is_healthy:
                        healthy_actual.append(c)
                    else:
                        # Actively kill the unhealthy container
                        await asyncio.to_thread(self._manager.stop_and_remove, name)

                await redis.aclose()
                actual = healthy_actual

        # Step 4: Track container actions in stats (before sync)
        if self._stats is not None:
            desired_specs = {spec.name: spec for spec in desired}
            actual_containers = {str(c.get("name", "")): c for c in actual}

            for name, spec in desired_specs.items():
                if name not in actual_containers:
                    self._stats.record_container_start(name)
                else:
                    # Check for config drift (re-create cycle)
                    c = actual_containers[name]
                    labels = c.get("labels", {})
                    actual_hash = ""
                    if isinstance(labels, dict):
                        actual_hash = labels.get("io.silvasonic.config_hash", "")

                    if actual_hash != spec.config_hash:
                        self._stats.record_container_stop(name)
                        self._stats.record_container_start(name)

            for name in actual_containers:
                if name not in desired_specs:
                    self._stats.record_container_stop(name)

        # Step 5: Reconcile desired vs. actual
        await asyncio.to_thread(
            self._manager.sync_state,
            desired,
            actual,
        )

    async def scan_and_sync_devices(self) -> int:
        """Scan USB devices, match profiles, and sync state to DB.

        Returns the number of devices found.  Reusable for both initial
        scan (during ``load_config``) and periodic rescans.
        """
        if self._scanner is None:
            return 0

        devices = await asyncio.to_thread(self._scanner.scan_all)

        async with get_session() as session:
            await self._upsert_detected_devices(devices, session)
            await self._mark_offline_devices(
                {d.stable_device_id for d in devices},
                session,
            )
            await session.commit()

        return len(devices)

    async def _upsert_detected_devices(
        self,
        devices: list[DeviceInfo],
        session: AsyncSession,
    ) -> None:
        """Match profiles and upsert each detected device into the DB."""
        # Pre-load all profiles once for the entire batch (M2 optimisation)
        from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB

        profiles: list[MicProfileDB] | None = None
        if self._matcher is not None:
            result = await session.execute(select(MicProfileDB))
            profiles = list(result.scalars().all())

        for device_info in devices:
            if self._matcher is not None:
                match_result = await self._matcher.match(
                    device_info,
                    session,
                    profiles=profiles,
                )
                profile_slug = match_result.profile_slug if match_result.auto_enroll else None
                enrollment = "enrolled" if match_result.auto_enroll else "pending"
            else:
                profile_slug = None
                enrollment = "pending"

            device = await upsert_device(
                device_info,
                session,
                profile_slug=profile_slug,
                enrollment_status=enrollment,
            )

            # Persist workspace_name for the Processor Indexer cross-service contract.
            # Only set when a profile is assigned (enrolled devices get workspace dirs).
            if device.profile_slug:
                ws = generate_workspace_name(device.profile_slug, device)
                if device.workspace_name != ws:
                    device.workspace_name = ws

    async def _mark_offline_devices(
        self,
        current_ids: set[str],
        session: AsyncSession,
    ) -> None:
        """Mark previously online devices as offline if no longer detected.

        Uses a time-based grace period (hysteresis) to debounce temporary
        USB hotplugging or flappying.
        """
        now = time.monotonic()

        # Reset grace period for devices that reappeared
        reappeared_ids = current_ids.intersection(self._missing_devices)
        for device_id in reappeared_ids:
            del self._missing_devices[device_id]
            log.info("reconciler.device_reappeared_in_grace", device_id=device_id)

        result = await session.execute(select(Device).where(Device.status == "online"))
        online_devices = result.scalars().all()
        online_names = {d.name for d in online_devices}

        # Clear orphaned state for devices that are no longer online in the DB
        # Use list(keys()) to prevent RuntimeError: dictionary changed size during iteration
        for device_id in list(self._missing_devices.keys()):
            if device_id not in online_names and device_id not in current_ids:
                del self._missing_devices[device_id]

        for device in online_devices:
            if device.name not in current_ids:
                if device.name not in self._missing_devices:
                    # First time missing -> start grace period
                    self._missing_devices[device.name] = now
                    log.debug("reconciler.device_missing_start_grace", device_id=device.name)
                elif now - self._missing_devices[device.name] >= self._grace_period_s:
                    # Grace period expired -> mark offline
                    device.status = "offline"
                    del self._missing_devices[device.name]
                    log.info("reconciler.device_offline", device_id=device.name)
                else:
                    # Missing but still within grace period -> do nothing
                    log.debug("reconciler.device_missing_in_grace", device_id=device.name)

    async def _rescan_hardware(self) -> None:
        """Rescan USB audio devices and sync state to DB.

        Delegates to ``scan_and_sync_devices()`` and logs the result.
        """
        count = await self.scan_and_sync_devices()
        log.debug("reconciler.hardware_rescan", devices_found=count)
